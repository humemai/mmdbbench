"""The gaps of the landing procedure that the second rehearsal of the 26.12.1 landing found (humemai/mmdbbench#157), one group of tests per item.

The rehearsal (2026-11-23, a scratch copy of the store, small rows relabelled to a made-up release, large rows at the 26.11.1 commit, nothing pushed) ran the real
`land_stage.py` and found: (1) the comparators' chain pin is in no procedure document and a failed comparator cell at it is dropped without a word, (2) a forgotten
large pin refuses after the merge, (3) a large tier with no rows at all refuses the landing, (4) the small sparse tier needs six arms and the pull takes one directory,
(5) `current_pin()` answers with the OLD commit before the first landing of a release, (6) one sentence is printed once per row. Item 7 (a scope without l3s still reads
`sparse_mp_<pin>`) is not fixed here: see the pull request.

Plain functions with `unittest.mock`, temporary directories and synthetic rows, so they run under the suite or as
`python test_landing_procedure_gaps.py [name-substring ...]` from this directory. The exporter is imported, so numpy and pandas are needed, as everywhere else;
`make_paper_figures` draws with matplotlib, which is stubbed when it is not installed (the one function under test draws nothing)."""
import contextlib
import glob
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import land_stage as L  # noqa: E402
import size_classes as SC  # noqa: E402

OLD, NEW = "a3a5d1245", "0123abcde"      # the commit of 26.11.1 (the large rows), and a made-up commit for the 26.12.1 landing (the small rows)
COMP = "e85469273"                       # the comparators' own chain pin
VAR, CVAR = SC.LARGE_PIN_VAR, SC.COMPARATOR_PIN_VAR
ARM = "arcadedb_sparse_embedded"
TIERS = ("tiny", "small", "medium")
WARM = ("warm p50 ms", "warm p99 ms", "gain")
_CLEAR = ("BENCH_ENGINE_COMMIT", VAR, CVAR, "BENCH_LAND_PULLED_FILE", "BENCH_INSTRUMENT", "BENCH_ONLY_LANES", "BENCH_MP_BUILDS", "BENCH_ENGINE_BACKEND")


def _refusal(fn, *args, **kw):
    try:
        fn(*args, **kw)
    except SystemExit as e:
        return str(e.code)
    raise AssertionError(f"{getattr(fn, '__name__', fn)} did not refuse")


# ------------------------------------------------------------------------------------------------ land_stage.main() with every command recorded
class _Stop(Exception):
    """Raised by the recording shell when a test says no command may run: a refusal that comes first leaves nothing of this behind."""


def _land(argv, payload=None, harness=None, store=None, pulled=None, env=None, stop_on_command=True):
    """(outcome, the commands `land_stage` ran, the printed text) for land_stage.main() with `argv`, in a scratch results tree, with a recording shell in place of `sh`.

    `payload` is the published page (the site's payload, the one `land_stage` reads the large entries from), `harness` the harness' own web_benchmarks.json,
    `store` the rows of results/runs.jsonl, `pulled` the rows of the landing (BENCH_LAND_PULLED_FILE). With `stop_on_command` the first command stops the run
    (outcome 'ran a command'); without it every command succeeds and does nothing. The outcome is 'returned <rc>', 'ran a command' or 'refused: <text>'."""
    cmds = []

    def fake_sh(cmd, **_kw):
        cmds.append(" ".join(str(c) for c in cmd))
        if stop_on_command:
            raise _Stop()
        return subprocess.CompletedProcess(cmd, 0, "", "")

    out = io.StringIO()
    with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ), mock.patch.object(sys, "argv", ["land_stage.py", *argv]), \
            mock.patch.object(L, "PY", sys.executable), mock.patch.object(L.os, "execv", lambda *a, **k: None), mock.patch.object(L, "sh", fake_sh), \
            mock.patch.object(L, "SCRATCH", Path(t) / "scratch"), mock.patch.object(L, "RESULTS", Path(t) / "results"), \
            mock.patch.object(L, "SITE_PAYLOAD", Path(t) / "site.json"), mock.patch.object(L, "PAYLOAD", Path(t) / "harness.json"), contextlib.redirect_stdout(out):
        t = Path(t)
        (t / "results").mkdir()
        for k in _CLEAR:
            os.environ.pop(k, None)
        os.environ.update(env or {})
        if payload is not None:
            (t / "site.json").write_text(json.dumps(payload))
        if harness is not None:
            (t / "harness.json").write_text(json.dumps({"arcadedb_commits": harness}))
        if store is not None:
            (t / "results" / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in store))
        if pulled is not None:
            (t / "pulled.jsonl").write_text("".join(json.dumps(r) + "\n" for r in pulled))
            os.environ["BENCH_LAND_PULLED_FILE"] = str(t / "pulled.jsonl")
        before = (t / "results" / "runs.jsonl").read_bytes() if store is not None else None
        try:
            rc = L.main()
            outcome = f"returned {rc}"
        except _Stop:
            outcome = "ran a command"
        except SystemExit as e:
            outcome = f"refused: {e.code}"
        if before is not None:
            assert (t / "results" / "runs.jsonl").read_bytes() == before, "the store was written"
    return outcome, cmds, out.getvalue()


def _entry(scale, commit, arcadedb=True, label="ArcadeDB (embedded)"):
    return {"is_arcadedb": arcadedb, "scale": scale, "backend": label, "version_name": f"arcadedb 26.11.1 · {commit}" if commit else None}


# ------------------------------------------------------------------------------------------------ 1. the comparators' chain pin
def _failed(backend, lane, scale, workload="oltp", commit=COMP, error="out of memory", instrument="2026-11"):
    return {"instrument": instrument, "lane": lane, "scale": scale, "workload": workload, "backend": backend, "rep": 1, "rc": 1, "error": error,
            "engine_commit": commit}


def test_a_failed_comparator_cell_at_an_unlisted_commit_is_named_with_its_cells():
    store = [_failed("duckpgq_graph", "l2", "sf1"), _failed("duckpgq_graph", "l2", "sf10"), _failed("surrealdb_graph", "l2", "sf1full", "olap")]
    with mock.patch.dict(os.environ):
        for k in _CLEAR:
            os.environ.pop(k, None)
        found = L.unlisted_comparator_commits(store, [], NEW)
        assert list(found) == [COMP] and len(found[COMP]) == 3 and "l2 sf1full olap surrealdb_graph" in found[COMP], found
        assert L.unlisted_comparator_commits(store, [], NEW, comparator_pins=[COMP]) == {}              # the variable lists it
        assert L.unlisted_comparator_commits(store, [], NEW, comparator_pins=[COMP[:7]]) == {}          # a prefix of it, as the exporter reads it
        assert list(L.unlisted_comparator_commits(store, [], NEW, comparator_pins=["ffffffff1"])) == [COMP]
        assert L.unlisted_comparator_commits(store, [], NEW, scope={"l3s"}) == {}                       # a lane out of the landing's scope is not read
        assert L.unlisted_comparator_commits([], store, NEW) == found                                   # the rows about to merge count too
        msg = L.format_unlisted_comparator_commits(found, NEW, NEW)
    assert msg.startswith("REFUSING:") and COMP in msg and "3 cell(s)" in msg and f"{CVAR}={COMP}" in msg and "unset" in msg and "Nothing was merged" in msg, msg


def test_only_failed_comparator_rows_of_the_publishing_instrument_are_read():
    rows = [dict(_failed("duckpgq_graph", "l2", "sf1"), error=None, rc=0),                       # a row that ran is not a failed cell
            _failed("arcadedb_graph_embedded", "l2", "sf1", commit="d36b4ca3a"),                  # ArcadeDB's own failed cells are the small-cell warning's, not this one's
            _failed("duckpgq_graph", "l2", "sf10", instrument="2026-10"),                         # a retired instrument never reaches the page
            _failed("duckpgq_graph", "l2", "sf1", commit=NEW)]                                    # at the pin
    with mock.patch.dict(os.environ):
        for k in _CLEAR:
            os.environ.pop(k, None)
        assert L.unlisted_comparator_commits(rows, [], NEW) == {}


def test_a_failed_comparator_cell_is_read_at_the_pin_of_its_size_class():
    large = _failed("duckpgq_graph", "l2", "sf10", commit=OLD)
    small = _failed("duckpgq_graph", "l2", "sf1", commit=OLD)
    with mock.patch.dict(os.environ):
        for k in _CLEAR:
            os.environ.pop(k, None)
        assert list(L.unlisted_comparator_commits([large, small], [], NEW)) == [OLD]                   # no large pin: both are at another commit
        os.environ[VAR] = OLD
        assert L.unlisted_comparator_commits([large], [], NEW) == {}                                   # a large cell at the large pin is the cell's note
        found = L.unlisted_comparator_commits([large, small], [], NEW)
        assert list(found) == [OLD] and found[OLD] == ["l2 sf1 oltp duckpgq_graph"], found           # a small cell at the large pin is not at its own pin


def test_the_exporter_and_the_landing_read_a_row_by_the_same_test():
    src = (HERE / "export_web.py").read_text(encoding="utf-8")
    assert "return _SC.row_at_pin(r, comparator_pins=_comparator_pins)" in src and "_comparator_pins = _SC.comparator_pins()" in src
    lander = (HERE / "land_stage.py").read_text(encoding="utf-8")
    assert "size_classes.row_at_pin(r, landing=pin, comparator_pins=comparator_pins)" in lander
    with mock.patch.dict(os.environ):
        os.environ["BENCH_ENGINE_COMMIT"] = NEW
        os.environ[VAR] = OLD
        os.environ[CVAR] = f" {COMP}, ,ffffffff1 "
        assert SC.comparator_pins() == [COMP, "ffffffff1"]
        row = lambda lane, scale, commit: {"lane": lane, "scale": scale, "engine_commit": commit}      # noqa: E731
        at = lambda r, **kw: SC.row_at_pin(r, comparator_pins=SC.comparator_pins(), **kw)      # noqa: E731
        assert at(row("l2", "sf1", NEW)) and at(row("l2", "sf1", NEW + "0" * 31)) and at(row("l2", "sf1", NEW[:5]))   # either prefix
        assert at(row("l2", "sf10", OLD)) and not at(row("l2", "sf10", NEW))                                          # the large class reads the large pin
        assert at(row("l2", "sf1", COMP)) and at(row("l2", "sf10", COMP)) and not at(row("l2", "sf1", OLD))           # a comparator pin is read for every size
        assert at(row("nolane", "x", NEW)) and not at(row("nolane", "x", OLD))                                        # a pair that is not classed is small
        assert not at(row("l2", "sf1", None)) and not at(row("l2", "sf1", ""))                                        # a row with no commit is at no pin
        assert at(row("l2", "sf10", OLD), landing=NEW) and at(row("l2", "sf1", "bbbbbbbb2"), landing="bbbbbbbb2")


def test_the_landing_refuses_before_the_merge_for_an_unlisted_comparator_commit_and_the_variable_lets_it_through():
    store = [_failed("duckpgq_graph", "l2", "sf1")]
    pulled = [{"instrument": "2026-11", "engine_commit": NEW, "lane": "l2", "scale": "sf1", "workload": "oltp", "backend": "arcadedb_graph_embedded", "rep": 1, "rc": 0}]
    argv = ["--pin", NEW, "--only-lanes", "l2", "--message", "m", "--dry-run"]
    outcome, cmds, _text = _land(argv, store=store, pulled=pulled, stop_on_command=False)
    assert outcome.startswith("refused: REFUSING: the store holds failed comparator cells") and COMP in outcome and f"{CVAR}={COMP}" in outcome, outcome
    assert not any("merge_campaign" in c for c in cmds), cmds                                  # before the merge: nothing reached the store (the harness checks its bytes too)
    outcome, cmds, text = _land(argv, store=store, pulled=pulled, env={CVAR: COMP}, stop_on_command=False)
    assert outcome == "returned 0" and "DRY RUN" in text, (outcome, text[-300:])               # the comparators' chain pin listed: the check does not fire


# ------------------------------------------------------------------------------------------------ 2. a forgotten large pin
def test_the_large_commits_of_the_published_page_are_the_large_arcadedb_entries_at_another_commit():
    payload = {"tables": [
        {"id": "l2", "entries": [_entry("sf1", NEW), _entry("sf10", OLD), _entry("sf10", OLD, label="ArcadeDB (server)"), _entry("sf10", OLD, arcadedb=False, label="Neo4j")]},
        {"id": "l3d", "entries": [_entry("small", OLD), _entry("deep10m", OLD), _entry("deep10m", None)]},      # a small entry, a large one, and one whose version names no commit
        {"id": "l3s", "entries": [_entry("medium", OLD + "0" * 31), _entry("medium", NEW)]},                      # the long form of the pin is the pin
        {"id": "durability", "entries": [_entry("500k", OLD)]},                                                   # a table with no lane in the exporter's map
    ]}
    with tempfile.TemporaryDirectory() as t:
        p = Path(t) / "site.json"
        p.write_text(json.dumps(payload))
        assert L.published_large_commits(p, NEW) == {OLD: 4}, L.published_large_commits(p, NEW)    # sf10 twice, deep10m once, l3s medium at the long form of OLD
        assert L.published_large_commits(p, OLD) == {NEW: 1}                                       # at the old pin the l3s entry at the new one is the odd one
        assert L.published_large_commits(p, OLD[:6]) == {NEW: 1}
        assert L.published_large_commits(Path(t) / "absent.json", NEW) == {}                      # a first landing has no page to read
        p.write_text("not json")
        assert L.published_large_commits(p, NEW) == {}


def test_a_forgotten_large_pin_refuses_before_anything_is_pulled_and_names_the_commit():
    page = {"tables": [{"id": "l2", "entries": [_entry("sf1", NEW), _entry("sf10", OLD)]}]}
    argv = ["--pin", NEW, "--message", "m"]
    outcome, cmds, _text = _land(argv, payload=page)
    assert outcome.startswith("refused: REFUSING: the published page holds 1 large-size ArcadeDB entry at engine commit " + OLD) and cmds == [], (outcome, cmds)
    assert f"--large-pin <commit of the large rows> (here {OLD})" in outcome and f"dense_mp5_{NEW}" in outcome and "Nothing was pulled or merged" in outcome, outcome
    assert f"--large-pin {NEW}" in outcome                                                    # a landing of rerun large rows says so
    for how, args_, env in (("flag", argv + ["--large-pin", OLD], None), ("variable", argv, {VAR: OLD}),
                            ("rerun at the pin", argv + ["--large-pin", NEW], None)):
        outcome, cmds, _text = _land(args_, payload=page, env=env)
        assert outcome == "ran a command" and cmds and "runs_page_" + NEW in cmds[0], (how, outcome, cmds)        # past the check: the first command is the pull of the rows
    outcome, cmds, _text = _land(argv)                                                        # no page yet
    assert outcome == "ran a command", outcome
    outcome, cmds, _text = _land(argv, payload={"tables": [{"id": "l2", "entries": [_entry("sf1", NEW), _entry("sf10", NEW)]}]})   # large rows already at the pin
    assert outcome == "ran a command", outcome


def test_the_both_builds_refusal_of_the_paper_path_names_the_large_pin_too():
    import make_paper_tables as M
    rows = [{"lane": "l3s", "backend": ARM, "scale": t, "rep": rep, "engine_commit": OLD if t == "medium" else NEW, "engine_version": "26.11.1" if t == "medium" else "26.12.1",
             "engine_backend": b, "query_p50_ms": 10.0 + rep, "query_p99_ms": 30.0, "recall_at_10": 0.95}
            for b in ("jvm", "native") for t in TIERS for rep in (1, 2, 3)]
    for large, named in ((None, True), (OLD, False)):
        err = io.StringIO()
        with mock.patch.dict(os.environ), mock.patch.object(M, "load_canonical", lambda: rows), contextlib.redirect_stderr(err):
            for k in _CLEAR:
                os.environ.pop(k, None)
            os.environ["BENCH_ENGINE_COMMIT"] = NEW
            if large:
                os.environ[VAR] = large
            res = M._pinned_sparse_rows(ARM, "all")
        if named:                                                                              # medium rows at the old pin only, no large pin: the freeze refuses and says how to fix it
            assert res is None and "build are incomplete or span two identities" in err.getvalue(), err.getvalue()
            assert VAR in err.getvalue() and "land_stage.py --large-pin" in err.getvalue(), err.getvalue()
        else:
            assert res is not None, err.getvalue()


# ------------------------------------------------------------------------------------------------ 3. an absent large tier
def _rows(builds=("jvm",), n=3, tiers=TIERS, medium_pin=OLD):
    """Synthetic l3s rows of the arm: `n` reps per tier and build, `tiny` and `small` at the NEW pin and `medium` at `medium_pin`."""
    out = []
    for b in builds:
        for t in tiers:
            pin = medium_pin if t == "medium" else NEW
            for rep in range(1, n + 1):
                out.append({"lane": "l3s", "backend": ARM, "scale": t, "rep": rep, "engine_commit": pin, "engine_version": "26.11.1" if pin == OLD else "26.12.1",
                            "engine_backend": b, "query_p50_ms": 10.0 + rep, "query_p99_ms": 30.0, "recall_at_10": 0.95})
    return out


@contextlib.contextmanager
def _env(large=OLD):
    with mock.patch.dict(os.environ):
        for k in _CLEAR:
            os.environ.pop(k, None)
        os.environ["BENCH_ENGINE_COMMIT"] = NEW
        if large:
            os.environ[VAR] = large
        yield


def _freeze(rows, large=OLD, build=None):
    import make_paper_tables as M
    err = io.StringIO()
    with _env(large), mock.patch.object(M, "load_canonical", lambda: rows), contextlib.redirect_stderr(err):
        res = M._pinned_sparse_rows(ARM, build)
    return res, err.getvalue()


def _sparse_table(rows, large=OLD):
    import make_paper_tables as M
    written, stop = {}, None
    with _env(large), mock.patch.object(M, "load_canonical", lambda: rows), mock.patch.object(M, "write", lambda name, body: written.update({name: body})), \
            contextlib.redirect_stderr(io.StringIO()):
        try:
            M.sparse_table([])
        except SystemExit as e:
            stop = str(e.code)
    return written, stop


def test_a_tier_with_no_row_at_all_is_absent_and_the_other_tiers_freeze():
    res, err = _freeze(_rows(tiers=("tiny", "small")))                                          # the landing state: the rerun is the small sizes, the large pin is named
    assert res is not None and {t: len(res[t]) for t in res} == {"tiny": 3, "small": 3} and "medium" not in res, (res, err)
    assert f"medium has no rows at {OLD}: absent" in err and "tiny has no rows" not in err and "small has no rows" not in err, err
    one, err = _freeze(_rows(tiers=("tiny", "small")), large=None)                              # with no large pin the same state is absent at the landing's pin
    assert one is not None and "medium" not in one and f"medium has no rows at {NEW}: absent" in err, (one, err)
    both, err = _freeze(_rows(builds=("jvm", "native"), tiers=("tiny", "small")), build="all")
    assert both is not None and {t: len(both[t]) for t in both} == {"tiny": 6, "small": 6}, (both, err)


def test_a_partial_tier_still_refuses_and_a_partial_large_tier_names_the_variable_and_the_flag():
    one_of_three = [r for r in _rows() if not (r["scale"] == "medium" and r["rep"] > 1)]
    res, err = _freeze(one_of_three)
    assert res is None and f"incomplete at ['medium']: medium has 1 of 3 rows at {OLD}" in err and VAR in err and "land_stage.py --large-pin" in err, err
    _written, stop = _sparse_table(one_of_three)
    assert stop is not None and "no fallback" in stop and VAR in stop and "land_stage.py --large-pin" in stop and "medium has 1 of 3 rows" in stop, stop
    short_small = [r for r in _rows(tiers=("tiny", "small")) if not (r["scale"] == "small" and r["rep"] == 3)]
    res, err = _freeze(short_small)
    assert res is None and f"incomplete at ['small']: small has 2 of 3 rows at {NEW}" in err and VAR not in err, err            # all-or-nothing per size class
    two_builds = [r for r in _rows(builds=("jvm", "native"), tiers=("tiny", "small")) if not (r["engine_backend"] == "native" and r["scale"] == "small" and r["rep"] == 3)]
    res, err = _freeze(two_builds, build="all")
    assert res is None and "native build are incomplete" in err, err                           # a short build is not published beside a full one


def test_a_tier_with_rows_only_at_another_commit_is_not_absent():
    res, err = _freeze(_rows(), large=None)                                                    # medium rows at the old pin, no large pin: the forgotten-pin shape
    assert res is None and VAR in err and "land_stage.py --large-pin" in err, err
    res, err = _freeze(_rows(medium_pin="ffffffff1"))                                          # medium rows at a third commit, the large pin named
    assert res is None and VAR in err and f"medium has 0 of 3 rows at {OLD}" in err, err


def test_the_sparse_table_prints_a_dash_for_an_absent_tier_and_numbers_for_the_rest():
    written, stop = _sparse_table(_rows(tiers=("tiny", "small")))
    assert stop is None and list(written) == ["t4_sparse.tex"], stop
    body = written["t4_sparse.tex"].splitlines()
    medium = [ln for ln in body if " & 8.84M & " in ln]
    assert len(medium) == 4 and all("-- & -- & --" in ln for ln in medium), medium              # one line per system, all dashes
    for label in ("100k", "1M"):                                                                 # ArcadeDB's block is the first of each tier: numbers; the comparators have no row here
        lines = [ln for ln in body if f" & {label} & " in ln]
        assert len(lines) == 4 and "-- & -- & --" not in lines[0] and all("-- & -- & --" in ln for ln in lines[1:]), lines


@contextlib.contextmanager
def _results(tiers_by_dir):
    """A scratch results tree for the exporter and the paper path with `sparse_mp_<pin>` directories holding six arms' files for the tiers given:
    {pin: tiers}. Yields (exporter, make_paper_figures, directory). matplotlib is stubbed when it is not installed."""
    import export_web as X
    import make_paper_tables as M
    if importlib.util.find_spec("matplotlib") is not None:
        stub = contextlib.nullcontext()
    else:
        stub = mock.patch.dict(sys.modules, {n: mock.MagicMock() for n in ("matplotlib", "matplotlib.pyplot", "matplotlib.ticker")})
    with tempfile.TemporaryDirectory() as d, stub, mock.patch.dict(os.environ), mock.patch.object(M, "RESULTS", d), mock.patch.object(X, "RESULTS", Path(d)), \
            mock.patch.object(X, "_SPLIT", False):
        for k in _CLEAR:
            os.environ.pop(k, None)
        os.environ["BENCH_ENGINE_COMMIT"] = NEW
        os.environ[VAR] = OLD
        for pin, tiers in tiers_by_dir.items():
            root = Path(d) / f"sparse_mp_{pin}"
            root.mkdir()
            for arm, backend, _label in X.SPARSE_MP_ARMS:
                for tier in tiers:
                    passes = [{"backend": backend, "scale": tier, "lane": "l3s_mp", "rep": i, "build_s": 100.0, "n_docs": 1000, "engine_version": "26.12.1",
                               "query_p50_ms": 80.0 if i == 0 else 10.0 + i, "query_p99_ms": 300.0 if i == 0 else 20.0 + i} for i in range(6)]
                    (root / f"sp_{arm}_{tier}.json").write_text(json.dumps(passes))
        import make_paper_figures as F
        yield X, F, Path(d)


def test_the_figure_and_the_second_pass_table_have_nothing_to_stop_on_when_the_medium_tier_was_not_run():
    with _results({NEW: ("small", "tiny")}) as (X, F, d):
        assert not (d / f"sparse_mp_{OLD}").exists()                                           # land_stage removes an empty pull directory: the large directory is absent
        assert F._sparse_overlay_pass("medium", "arc_int8", warm=True) is None                  # no file at the large pin: no value, not an error
        assert F._sparse_overlay_pass("small", "arc_int8", warm=True) == 13.0                   # median of the five warm passes 11..15
        assert F._sparse_overlay_pass("tiny", "qdrant", warm=False) == 80.0
        by_tier = {}
        for e in X._sparse_multipass_table()["entries"]:
            by_tier.setdefault(e["scale"], []).append(e)
        assert {t: len(v) for t, v in by_tier.items()} == {"small": 6, "tiny": 6}, {t: len(v) for t, v in by_tier.items()}
        lane = [{"backend": label, "backend_key": backend, "build": None, "precision": X.SPARSE_PRECISION.get(backend), "scale": tier, "is_arcadedb": "arcade" in backend,
                 "metrics": {"p50 ms": {"median": 80.0}, "p99 ms": {"median": 300.0}}} for tier in ("tiny", "small") for _a, backend, label in X.SPARSE_MP_ARMS]
        tables = [{"id": "l3s", "entries": lane, "columns": ["p50 ms", "p99 ms"], "conditions": [], "source_paths": [], "source_urls": []}, X._sparse_multipass_table()]
        X._restructure_tables(tables, [])                                                       # the page entries: rows of the lane and the second pass folded in, no medium anywhere
        entries = [e for t in tables if t["id"] == "l3s" for e in t["entries"]]
        assert len(entries) == 12 and {e["scale"] for e in entries} == {"small", "tiny"}
        assert all(all(k in e["metrics"] for k in WARM) for e in entries if e["scale"] == "small")


def test_the_landing_state_without_any_medium_row_passes_the_table_the_figure_and_the_page():
    """The rehearsal state: tiny and small at the new pin, the large pin named, no l3s row at all at the old pin and no medium files anywhere."""
    with _results({NEW: ("small", "tiny")}) as (X, F, d):
        import make_paper_tables as M
        written, stop = {}, None
        rows = _rows(tiers=("tiny", "small"))
        with mock.patch.object(M, "load_canonical", lambda: rows), mock.patch.object(M, "write", lambda name, body: written.update({name: body})), \
                contextlib.redirect_stderr(io.StringIO()):
            try:
                M.sparse_table([])
            except SystemExit as e:
                stop = str(e.code)
            assert stop is None and "t4_sparse.tex" in written, stop                            # the paper table
            assert M._sparse_2681_rows(build="all").keys() == {"tiny", "small"}                  # what the figures' own readers get
        assert F._sparse_overlay_pass("medium", "arc_int8", warm=True) is None                  # the figure's overlay pass
        assert {e["scale"] for e in X._sparse_multipass_table()["entries"]} == {"small", "tiny"}      # the page's second-pass table
        os.environ.pop(VAR)                                                                      # and a landing with no large pin names none of it absent for a missing directory
        stop = _refusal(X._sparse_multipass_table)
        assert f"sparse_mp_{NEW} has 6 of 6 files missing" in stop and VAR in stop             # the forgotten-large-pin guard of the exporter is unchanged


def test_a_partial_medium_overlay_still_refuses_and_names_its_directory():
    with _results({NEW: ("small", "tiny"), OLD: ("medium",)}) as (X, _F, d):
        assert len(X._sparse_multipass_table()["entries"]) == 18
        (d / f"sparse_mp_{OLD}" / "sp_qdrant_medium.json").unlink()
        msg = _refusal(X._sparse_multipass_table)
        assert f"sparse_mp_{OLD} has 1 of 6 files missing" in msg and "sp_qdrant_medium.json" in msg, msg


# ------------------------------------------------------------------------------------------------ 4. the comparators' sparse files
class _Host:
    """A fake bench host: `scp host:path dest` copies from a local directory, globs included, and records the commands."""

    def __init__(self, root):
        self.root, self.calls = Path(root), []

    def put(self, directory, **files):
        (self.root / directory).mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (self.root / directory / name).write_text(text)

    def scp(self, cmd, check=True):
        self.calls.append(cmd[-2].split(":", 1)[1].replace(str(self.root), "<host>"))
        for g in glob.glob(cmd[-2].split(":", 1)[1]):
            shutil.copy(g, cmd[-1])


def _pull(comparator_pins, large_pin=OLD, existing=None):
    with tempfile.TemporaryDirectory() as t, mock.patch.object(L, "HOST", "mini"):
        host, res = _Host(Path(t) / "host"), Path(t) / "results"
        res.mkdir()
        with mock.patch.object(L, "REMOTE", str(host.root)):
            # the ArcadeDB chain's directory at the landing's pin, the comparators' chain's at its own pin (old ArcadeDB files and the medium file included)
            host.put(L.host_name("sparse_mp", NEW), **{"sp_arc_int8_small.json": "arc new", "sp_arc_int8_tiny.json": "arc new"})
            host.put(L.host_name("sparse_mp", COMP), **{"sp_qdrant_small.json": "qdrant small", "sp_qdrant_tiny.json": "qdrant tiny", "sp_qdrant_medium.json": "qdrant medium",
                                                         "sp_arc_int8_small.json": "arc OLD", "sp_arc_int8_native_tiny.json": "arc OLD native", "sp_pgvector_small.json": "pg"})
            if existing:
                (res / f"sparse_mp_{NEW}").mkdir()
                for name, text in existing.items():
                    (res / f"sparse_mp_{NEW}" / name).write_text(text)
            L.pull_sparse_overlays(NEW, large_pin, results=res, scp=host.scp, comparator_pins=comparator_pins)
        got = {p.name: {f.name: f.read_text() for f in sorted(p.glob("*.json"))} for p in sorted(res.iterdir())}
        return got, host.calls


def test_the_comparators_sparse_files_are_copied_from_their_pins_directory_into_the_directory_of_their_class():
    got, calls = _pull([COMP])
    assert got[f"sparse_mp_{NEW}"] == {"sp_arc_int8_small.json": "arc new", "sp_arc_int8_tiny.json": "arc new", "sp_qdrant_small.json": "qdrant small",
                                       "sp_qdrant_tiny.json": "qdrant tiny", "sp_pgvector_small.json": "pg"}, got      # the old ArcadeDB files stay where they were measured
    assert got[f"sparse_mp_{OLD}"] == {"sp_qdrant_medium.json": "qdrant medium"}, got                                     # the medium file is in the large class's directory
    assert not [p for p in got if p.startswith(".")] and set(got) == {f"sparse_mp_{NEW}", f"sparse_mp_{OLD}"}, got      # no scratch directory is left
    assert any(f"sparse_mp_{COMP}" in c or L.host_name("sparse_mp", COMP) in c for c in calls), calls


def test_a_file_the_landing_already_holds_wins_and_a_pin_that_is_the_landings_adds_nothing():
    got, _calls = _pull([COMP], existing={"sp_qdrant_small.json": "the union the owner copied by hand"})
    assert got[f"sparse_mp_{NEW}"]["sp_qdrant_small.json"] == "the union the owner copied by hand" and got[f"sparse_mp_{NEW}"]["sp_qdrant_tiny.json"] == "qdrant tiny", got
    got, calls = _pull([NEW])
    assert set(got[f"sparse_mp_{NEW}"]) == {"sp_arc_int8_small.json", "sp_arc_int8_tiny.json"} and len(calls) == 3, (got, calls)     # the landing's own pull only
    got, calls = _pull([])
    assert set(got[f"sparse_mp_{NEW}"]) == {"sp_arc_int8_small.json", "sp_arc_int8_tiny.json"} and len(calls) == 3, (got, calls)     # no variable: as before
    got, calls = _pull([COMP], large_pin=NEW)                                                    # one release for both classes: one directory, every tier of the comparators
    assert set(got) == {f"sparse_mp_{NEW}"} and "sp_qdrant_medium.json" in got[f"sparse_mp_{NEW}"] and "sp_arc_int8_native_tiny.json" not in got[f"sparse_mp_{NEW}"], got


# ------------------------------------------------------------------------------------------------ 5. the pin of a landing is always given
def test_a_landing_without_a_pin_refuses_even_when_the_payload_names_one_commit():
    outcome, cmds, _text = _land(["--message", "m"], harness=[OLD])
    assert outcome.startswith("refused: REFUSING: no --pin and no BENCH_ENGINE_COMMIT. The current payload names " + OLD + " alone"), outcome
    assert "build already published" in outcome and "Pass --pin <commit>" in outcome and L.host_name("runs_page", OLD, ".jsonl") in outcome and cmds == [], (outcome, cmds)
    outcome, cmds, _text = _land(["--message", "m"], harness=[OLD, NEW])                         # two commits: the refusal of before, unchanged
    assert "does not name exactly one engine commit" in outcome and cmds == [], outcome
    outcome, cmds, _text = _land(["--message", "m"])                                             # no payload
    assert "no --pin, no BENCH_ENGINE_COMMIT" in outcome and cmds == [], outcome
    for argv, env in ((["--pin", NEW, "--message", "m"], None), (["--message", "m"], {"BENCH_ENGINE_COMMIT": NEW})):      # given: the pull of its rows file is the first command
        outcome, cmds, _text = _land(argv, harness=[OLD], env=env)
        assert outcome == "ran a command" and L.host_name("runs_page", NEW, ".jsonl") in cmds[0], (argv, outcome, cmds)


def test_the_pin_has_no_default_from_the_payload_in_the_help_text():
    out = io.StringIO()
    with mock.patch.dict(os.environ), mock.patch.object(sys, "argv", ["land_stage.py", "--help"]), mock.patch.object(L, "PY", sys.executable), \
            mock.patch.object(L.os, "execv", lambda *a, **k: None), contextlib.redirect_stdout(out):
        try:
            L.main()
        except SystemExit as e:
            assert e.code == 0
    text = " ".join(out.getvalue().split())
    assert "(default: BENCH_ENGINE_COMMIT; there is no other default" in text and "else the one commit the current payload was built from" not in text, text


# ------------------------------------------------------------------------------------------------ 6. one sentence once
def _served(backend, rep, server_commit="6c9f2d8e3aaa"):
    return {"lane": "e2", "scale": "e2", "workload": "hybrid", "backend": backend, "rep": rep, "engine_backend": "native", "engine_commit": "5b8e1c7d2a94",
            "server_engine_commit": server_commit, "engine_version": "server:26.12.1 (build 6c9f2d8e3)", "server_settings": {"arcadedb.txWalFlush": "0"},
            "server_mode": "development", "server_cpus": 4, "server_max_heap_bytes": 2 << 30}


def test_the_native_server_commit_sentence_is_printed_once_per_arm_in_the_order_it_first_appeared():
    import arm_identity as AI
    arms = ("arcadedb_e2_server", "arcadedb_graph_server", "arcadedb_sparse_server", "arcadedb_dense_server", "arcadedb_server", "arcadedb_tpc_server")
    rows = [_served(b, rep) for b in arms for rep in range(1, 8)]                                # 42 rows, the same sentence for the 7 repetitions of each arm
    got = [p for p in AI.server_settings_problems(rows) if "reports engine commit" in p]
    assert got == [f"{b}: the native server reports engine commit 6c9f2d8e3 and the row names 5b8e1c7d2" for b in arms], got
    assert AI.server_settings_problems(rows) == list(dict.fromkeys(AI.server_settings_problems(rows)))
    other = [dict(_served("arcadedb_e2_server", 1), server_cpus=None), _served("arcadedb_e2_server", 2, "deadbeef0"), _served("arcadedb_e2_server", 3, "deadbeef0")]
    mixed = AI.server_settings_problems(other)
    assert [("reports engine commit 6c9f2d8e3" in p, "start-line read-back" in p, "deadbeef0" in p) for p in mixed] == [
        (True, False, False), (False, True, False), (False, False, True)], mixed                                      # three sentences, the repeated one once, in the order they came


if __name__ == "__main__":
    names = [n for n in sorted(globals()) if n.startswith("test_") and (len(sys.argv) < 2 or any(a in n for a in sys.argv[1:]))]
    for n in names:
        globals()[n]()
        print("ok", n)
    print(len(names), "passed")
