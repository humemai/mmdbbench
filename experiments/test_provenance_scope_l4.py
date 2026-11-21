"""provenance_check and the l4 (time-series) rows under a scoped landing (humemai/mmdbbench#30).

A landing scoped with `--only-lanes` (BENCH_ONLY_LANES) freezes and gates the lanes it carries. The l4 requirement of the paper-table
audit ("no arcadedb_ts_native rows at the pin; no fallback") is for a freeze that holds l4, so:

1. scope `e2,l2`, rows without l4: the repetition audit is skipped with a printed reason that names the lanes it did not look at, and
   make_paper_tables' time-series block is omitted, not refused;
2. empty scope, rows without l4: the refusal is unchanged (release artifacts or nothing);
3. scope names l4, rows without l4: make_paper_tables still refuses, the lane is in the landing and its rows are absent.

Light: a temp results directory with two rows, no engine. Run with pytest, or as plain functions from this directory."""
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_RES = tempfile.mkdtemp(prefix="provenance-scope-l4-")
Path(_RES, "runs.jsonl").write_text("")
os.environ.setdefault("BENCH_RESULTS_DIR", _RES)
os.environ.setdefault("BENCH_ENGINE_COMMIT", "abc123def")
import make_paper_tables as MPT  # noqa: E402
import provenance_check as PC  # noqa: E402

L4_REFUSAL = "no arcadedb_ts_native rows at the pin; no fallback"


def _row(lane, scale, backend):
    return {"lane": lane, "scale": scale, "workload": "oltp", "backend": backend, "instrument": "2026-11", "cpuset": "0-11",
            "rep": 1, "rc": 0, "ts_utc": "2026-11-01T00:00:00Z", "engine_commit": "abc123def"}


ROWS_WITHOUT_L4 = [_row("e2", "e2", "arcadedb_embedded"), _row("l2", "sf1", "arcadedb_graph_embedded")]


@contextlib.contextmanager
def _scope(lanes):
    """BENCH_ONLY_LANES = lanes, in the environment (read by caption_n) and in make_paper_tables (read at its import), on a results
    directory that holds rows without l4. Everything is put back."""
    tmp = tempfile.mkdtemp(prefix="provenance-scope-l4-run-")
    Path(tmp, "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in ROWS_WITHOUT_L4))
    saved = (os.environ.get("BENCH_ONLY_LANES"), os.environ.get("BENCH_RUNS_JSONL"), MPT.RESULTS, set(MPT._ONLY_LANES))
    os.environ["BENCH_ONLY_LANES"] = ",".join(lanes)
    os.environ.pop("BENCH_RUNS_JSONL", None)
    MPT.RESULTS = tmp
    MPT._ONLY_LANES.clear()
    MPT._ONLY_LANES.update(lanes)
    try:
        yield
    finally:
        for key, val in (("BENCH_ONLY_LANES", saved[0]), ("BENCH_RUNS_JSONL", saved[1])):
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val
        MPT.RESULTS = saved[2]
        MPT._ONLY_LANES.clear()
        MPT._ONLY_LANES.update(saved[3])


def _caption_n():
    out = io.StringIO()
    refused = None
    bad = None
    with contextlib.redirect_stdout(out):
        try:
            bad = PC.caption_n()
        except SystemExit as e:
            refused = str(e)
    return bad, refused, out.getvalue()


def _dense_ts_table():
    """make_paper_tables.dense_ts_table on the rows without l4, its file writes captured instead of made."""
    written = {}
    real = MPT.write
    MPT.write = lambda name, body: written.__setitem__(name, body)
    out = io.StringIO()
    refused = None
    try:
        with contextlib.redirect_stdout(out):
            try:
                MPT.dense_ts_table(MPT.load_canonical())
            except SystemExit as e:
                refused = str(e)
    finally:
        MPT.write = real
    return refused, out.getvalue()


def test_scope_without_l4_skips_the_audit_and_names_the_lanes_not_checked():
    with _scope(["e2", "l2"]):
        bad, refused, text = _caption_n()
    assert refused is None and bad == 0
    assert "SKIPPED: this landing is scoped to e2,l2" in text
    line = [ln for ln in text.splitlines() if "not checked, out of scope:" in ln]
    assert len(line) == 1
    named = {x.strip() for x in line[0].split(":", 1)[1].split(",")}
    assert "l4" in named and "e4" in named and "l3d" in named
    assert "e2" not in named and "l2" not in named


def test_scope_without_l4_omits_the_time_series_block_it_does_not_refuse():
    with _scope(["e2", "l2"]):
        refused, text = _dense_ts_table()
    assert refused is None
    assert "l4 is not in this landing's lanes (e2,l2)" in text


def test_empty_scope_without_l4_refuses_as_before():
    with _scope([]):
        bad, refused, text = _caption_n()
    assert refused == L4_REFUSAL and bad is None
    assert "SKIPPED: this landing is scoped" not in text


def test_a_scope_that_names_l4_still_refuses_when_its_rows_are_absent():
    with _scope(["e2", "l4"]):
        refused, _text = _dense_ts_table()
    assert refused == L4_REFUSAL
