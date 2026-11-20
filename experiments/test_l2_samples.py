"""The l2 oltp cell can write its per-start latencies and answers to a side file, opt-in (mmdbbench#102).

Run with `python -m pytest test_l2_samples.py -q -rs` from this directory.

A maintainer asked whether every start of the three-hop read is slow or a few outliers lift the median. The lane kept every start's latency
in memory and wrote only p50, p95, p99 and the count into the row. `BENCH_GRAPH_SAMPLES_OUT=<path>` makes the cell also write one JSON-lines
file: a header record, then one record per timed start of every read in both passes (start id, latency in ms as the timer measured it,
pass, position, the answer the lane collected after the clock stopped). Unset, the cell is what it was.

This file pins four things, with no engine and no JVM (the lane runs in-process against a stand-in adapter, as in test_graph_read_warmup.py):
the file's shape and its pure writer; that unset writes nothing and calls nothing; that the file holds the very latencies the row's
percentiles came from, so no second clock exists; and that the writer is called once, after the last adapter call, and never from the read
loop. An unwritable path is refused before the connect.
"""
import ast
import decimal
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import graph_common as G  # noqa: E402
import l2_graph as L  # noqa: E402

OPS = ("point", "hop1", "hop2", "hop3f")
EVENTS = []
SAMPLE_KEYS = {"record", "op", "pass", "position", "start_id", "latency_ms", "answer", "discarded"}


def _answer(op, pid):
    """What the stand-in returns for a start: the columns graph_common.READ_DIGEST names, with values that depend on the start."""
    pid = int(pid)
    return {"point": [{"name": f"p{pid}", "age": 40 + pid % 5}], "hop1": [{"n": pid % 97, "a": 41.0}],
            "hop2": [{"n": pid % 97}], "hop3f": [{"n": pid % 97}]}[op]


# ---- the pure writer, on fake latencies ---------------------------------------------------------------------------

def test_the_records_of_a_fake_pass_have_the_documented_shape(tmp_path):
    lat = [0.1 + 0.2, 1.0 / 3.0, 12.345678901234, 4.0, 5.5, 6.25, 7.125]           # unrounded on purpose
    answers = [{"n": 4}, {"n": 5}, {"n": 6}, {"n": 7}, {"n": 8}]                 # flat: start 1 returned nothing, start 3 two rows
    bounds = [1, 1, 2, 4, 5, 5, 5]
    ids = [101, 102, 103, 104, 105, 106, 107]
    passes = [(1, "hop3f", lat, answers, bounds), (2, "hop3f", lat[:3], answers, bounds[:3])]
    path = tmp_path / "s.jsonl"
    L.write_samples(str(path), {"lane": "l2", "backend": "fake"}, passes, ids)

    recs = [json.loads(line) for line in path.read_text().splitlines()]
    head, samples = recs[0], recs[1:]
    assert head == {"record": "header", "format": L.SAMPLES_FORMAT, "lane": "l2", "backend": "fake"}
    assert len(samples) == 7 + 3 and all(set(s) == SAMPLE_KEYS and s["record"] == "sample" for s in samples)
    first = samples[:7]
    assert [s["position"] for s in first] == list(range(7)) and {s["pass"] for s in first} == {1}
    assert [s["start_id"] for s in first] == ids
    assert [s["latency_ms"] for s in first] == lat                                # exact: the float the timer produced, not rounded
    assert [s["answer"] for s in first] == [[{"n": 4}], [], [{"n": 5}], [{"n": 6}, {"n": 7}], [{"n": 8}], [], []]
    assert [s["discarded"] for s in first] == [True] * 5 + [False] * 2            # the first five starts, which the percentiles leave out
    assert {s["pass"] for s in samples[7:]} == {2} and [s["position"] for s in samples[7:]] == [0, 1, 2]


def test_an_answer_json_cannot_hold_is_written_as_text_not_lost(tmp_path):
    path = tmp_path / "s.jsonl"
    L.write_samples(str(path), {}, [(1, "point", [1.0], [{"v": decimal.Decimal("1.5")}], [1])], [7])
    assert json.loads(path.read_text().splitlines()[1])["answer"] == [{"v": "1.5"}]


def test_the_variable_is_off_unless_set_and_only_oltp_uses_it():
    assert L.SAMPLES_ENV == "BENCH_GRAPH_SAMPLES_OUT"
    assert L.samples_target("oltp", {}) == (None, None)
    assert L.samples_target("oltp", {L.SAMPLES_ENV: ""}) == (None, None)
    assert L.samples_target("oltp", {L.SAMPLES_ENV: "/x/s.jsonl"}) == ("/x/s.jsonl", None)
    path, note = L.samples_target("olap", {L.SAMPLES_ENV: "/x/s.jsonl"})
    assert path is None and L.SAMPLES_ENV in note


def test_the_path_check_refuses_what_cannot_be_written_and_leaves_nothing_behind(tmp_path):
    with pytest.raises(SystemExit) as e:
        L.check_samples_path(str(tmp_path / "missing-dir" / "s.jsonl"))
    assert L.SAMPLES_ENV in str(e.value)
    with pytest.raises(SystemExit):
        L.check_samples_path(str(tmp_path))                                       # a directory
    fresh = tmp_path / "fresh.jsonl"
    L.check_samples_path(str(fresh))
    assert not fresh.exists()                                                     # the empty file the check made is removed again
    old = tmp_path / "old.jsonl"
    old.write_text("kept\n")
    L.check_samples_path(str(old))
    assert old.read_text() == "kept\n"                                            # an existing file is neither truncated nor removed


# ---- the lane, end to end, on a stand-in adapter -------------------------------------------------------------------

class _Stub(L.Base):
    name = "stub_samples"
    version = "stub"
    QUERY_LANGUAGE = "stub"

    def connect(self):
        EVENTS.append("connect")

    def build(self, n):
        for _ in L.gen_persons(n):
            pass
        for _ in L.gen_edges(n):
            pass

    def run_read(self, op, pid):
        EVENTS.append(("read", op, int(pid)))
        return _answer(op, pid)

    def run_visited(self, pid):
        return [{"n": 3}]

    def run_write(self, pid, new_id):
        EVENTS.append("write")

    def run_update(self, new_id):
        EVENTS.append("update")

    def run_delete(self, new_id):
        EVENTS.append("delete")

    def person_scan(self, id_from):
        return []

    def edge_scan(self, id_from):
        return []

    def close(self):
        EVENTS.append("close")


@pytest.fixture
def cell(monkeypatch, tmp_path):
    monkeypatch.setitem(L.ADAPTERS, "stub_samples", _Stub)
    monkeypatch.setenv("BENCH_CRUD_OPS", "10")
    monkeypatch.setattr(L, "CRUD_OPS", 10)
    monkeypatch.delenv(L.SAMPLES_ENV, raising=False)
    EVENTS.clear()

    def run(samples=None):
        if samples is not None:
            monkeypatch.setenv(L.SAMPLES_ENV, str(samples))
        out = tmp_path / "row.json"
        monkeypatch.setattr(sys, "argv", ["l2_graph.py", "--backend", "stub_samples", "--workload", "oltp",
                                           "--scale", "micro", "--out", str(out)])
        L.main()
        return json.loads(out.read_text())
    return run


def _read_file(path):
    recs = [json.loads(line) for line in Path(path).read_text().splitlines()]
    return recs[0], recs[1:]


def _timed_ids():
    return G.pick_query_ids(G.SCALE_PERSONS["micro"], G.SCALE_OLTP_QUERIES["micro"])


def test_unset_writes_nothing_and_calls_none_of_the_sample_code(cell, monkeypatch, tmp_path):
    def boom(*_a, **_k):
        raise AssertionError("sample code ran with BENCH_GRAPH_SAMPLES_OUT unset")
    for name in ("write_samples", "check_samples_path", "samples_header", "sample_records"):
        monkeypatch.setattr(L, name, boom)
    cell()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["row.json"]


def test_set_writes_one_file_with_a_record_per_timed_start(cell, tmp_path):
    path = tmp_path / "samples.jsonl"
    cell(samples=path)
    head, samples = _read_file(path)
    ids = _timed_ids()
    n = len(ids)

    assert head["record"] == "header" and head["format"] == L.SAMPLES_FORMAT
    assert (head["lane"], head["backend"], head["workload"], head["scale"]) == ("l2", "stub_samples", "oltp", "micro")
    assert head["cell"] == "l2_stub_samples_oltp_micro" and head["row_file"] == "row.json"
    assert head["engine_version"] == "stub" and head["n_persons"] == G.SCALE_PERSONS["micro"]
    for key in ("wheel_version", "engine_backend", "host", "cpuset", "heap", "engine_commit", "written_utc"):
        assert key in head, key

    assert len(samples) == 2 * len(OPS) * n                                       # two passes of four reads over every start
    assert [(s["pass"], s["op"]) for s in samples[::n]] == [(p, op) for p in (1, 2) for op in OPS]
    for (pass_no, op), start in zip([(p, o) for p in (1, 2) for o in OPS], range(0, len(samples), n)):
        block = samples[start:start + n]
        assert [s["position"] for s in block] == list(range(n)) and {(s["pass"], s["op"]) for s in block} == {(pass_no, op)}
        assert [s["start_id"] for s in block] == ids
        assert [s["answer"] for s in block] == [_answer(op, i) for i in ids]       # the answer of THAT start, as the adapter returned it
        assert [s["discarded"] for s in block] == [i < L.SAMPLES_DISCARDED_FIRST for i in range(n)]
        assert all(set(s) == SAMPLE_KEYS and isinstance(s["latency_ms"], float) and s["latency_ms"] >= 0 for s in block)


def test_the_file_holds_the_latencies_the_rows_percentiles_came_from(cell, tmp_path):
    """No second clock: the percentiles of the file's counted starts ARE the row's, so the file is the timer's own numbers."""
    path = tmp_path / "samples.jsonl"
    row = cell(samples=path)
    _head, samples = _read_file(path)
    for op in OPS:
        for pass_no, prefix in ((1, ""), (2, "warm_")):
            counted = sorted(s["latency_ms"] for s in samples if s["op"] == op and s["pass"] == pass_no and not s["discarded"])
            for q in (0.50, 0.95, 0.99):
                assert round(L.pct(counted, q), 3) == row[f"{prefix}{op}_p{int(q * 100)}_ms"], (op, pass_no, q)
            if pass_no == 1:
                assert len(counted) == row[f"{op}_iters"]


def test_the_row_is_the_same_with_and_without_the_file(cell, tmp_path):
    off = cell()
    on = cell(samples=tmp_path / "samples.jsonl")
    assert set(on) == set(off)                                                    # no field added, none dropped
    assert {k: v for k, v in on.items() if not isinstance(v, float)} == {k: v for k, v in off.items() if not isinstance(v, float)}


def test_the_writer_runs_once_after_the_last_adapter_call_and_the_path_is_checked_before_the_first(cell, monkeypatch, tmp_path):
    real_write, real_check = L.write_samples, L.check_samples_path

    def spy_write(*a, **k):
        EVENTS.append("write_samples")
        return real_write(*a, **k)

    def spy_check(*a, **k):
        EVENTS.append("check_samples_path")
        return real_check(*a, **k)
    monkeypatch.setattr(L, "write_samples", spy_write)
    monkeypatch.setattr(L, "check_samples_path", spy_check)
    cell(samples=tmp_path / "samples.jsonl")
    assert EVENTS[:2] == ["check_samples_path", "connect"]
    assert EVENTS.count("write_samples") == 1
    assert EVENTS[-2:] == ["close", "write_samples"]                              # after every read, write, update, delete and the close
    assert {"write", "update", "delete"} <= set(EVENTS)                           # (the stand-in really ran them, so "after" means something)


def test_the_read_loop_never_calls_the_writer_or_touches_a_file():
    tree = ast.parse((HERE / "l2_graph.py").read_text())
    main = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main")
    read_pass = next(n for n in ast.walk(main) if isinstance(n, ast.FunctionDef) and n.name == "_read_pass")

    def called(node):
        for c in ast.walk(node):
            if isinstance(c, ast.Call):
                f = c.func
                yield f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
    forbidden = {"write_samples", "sample_records", "samples_header", "check_samples_path", "open", "dump", "dumps", "write", "print"}
    assert not forbidden & set(called(read_pass)), sorted(forbidden & set(called(read_pass)))

    writes = [c for c in ast.walk(main) if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "write_samples"]
    row_dump = [c for c in ast.walk(main) if isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "dump"
                and getattr(c.func.value, "id", "") == "json"]
    assert len(writes) == 1 and len(row_dump) == 1
    assert writes[0].lineno > row_dump[0].lineno                                  # the row is on disk before the side file is written


def test_an_unwritable_path_refuses_before_the_cell_connects(cell, tmp_path):
    with pytest.raises(SystemExit) as e:
        cell(samples=tmp_path / "missing-dir" / "samples.jsonl")
    assert L.SAMPLES_ENV in str(e.value)
    assert EVENTS == []                                                           # nothing ran: not the connect, not a read
    assert not (tmp_path / "row.json").exists()
