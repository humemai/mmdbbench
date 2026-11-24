"""The silent losses of the landing that the third rehearsal of the 26.12.1 landing found (humemai/mmdbbench#160), one group of tests per item.

The rehearsal (2026-11-23, a scratch copy of the store, small rows at a made-up new pin, large rows at the 26.11.1 commit, nothing pushed) ran the real
`land_stage.py` to the end of step 5 with every gate green and found: (1) a missing NATIVE overlay file, or a missing `tiny` file, is not a stop (9 of 22 `l3s`
entries lost their warm columns, 2 of 27 `l3d` entries left the page), (2) the equivalence registry is not in the procedure, (3) missing sparse files surface only
after the merge, (4) the e4 pre-read tells the reader to run a lane that has run, (5) the log shows expected `scp` misses as errors.

Plain functions with `unittest.mock`, temporary directories and synthetic rows and overlay files, so they run under the suite or as
`python test_silent_overlay_losses.py [name-substring ...]` from this directory. The exporter is imported, so numpy and pandas are needed, as everywhere else."""
import contextlib
import glob
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
os.environ.setdefault("BENCH_ONLY_LANES", "l3s,l3d")      # the exporter refuses to load without the E4 overlay unless the lanes are scoped

import land_stage as L  # noqa: E402
import native_overlay as NO  # noqa: E402
import size_classes as SC  # noqa: E402

OLD, NEW = "a3a5d1245", "0123abcde"      # the commit of 26.11.1 (the large rows), and a made-up commit for the 26.12.1 landing (the small rows)
COMP = "e85469273"                       # the comparators' own chain pin
TIERS = ("small", "tiny")
DENSE_ARMS = ("fp32", "int8", "arcsrv", "arcsrv_int8")
DENSE_KEYS = {"fp32": "arcadedb_dense_embedded", "int8": "arcadedb_dense_embedded_int8", "arcsrv": "arcadedb_dense_server", "arcsrv_int8": "arcadedb_dense_server_int8"}
_CLEAR = ("BENCH_ENGINE_COMMIT", SC.LARGE_PIN_VAR, SC.COMPARATOR_PIN_VAR, "BENCH_LAND_PULLED_FILE", "BENCH_INSTRUMENT", "BENCH_ONLY_LANES", "BENCH_MP_BUILDS",
          "BENCH_MP_ARMS", "BENCH_ENGINE_BACKEND")


def _refusal(fn, *args, **kw):
    try:
        fn(*args, **kw)
    except SystemExit as e:
        return str(e.code)
    raise AssertionError(f"{getattr(fn, '__name__', fn)} did not refuse")


def _row(lane, scale, backend, build, commit=NEW):
    return {"instrument": "2026-11", "lane": lane, "scale": scale, "backend": backend, "engine_backend": build, "engine_commit": commit, "engine_version": "26.12.1",
            "rc": 0, "rep": 1}


def _sparse_passes(backend, tier, build=None):
    base = {"backend": backend, "scale": tier, "lane": "l3s_mp", "build_s": 100.0, "n_docs": 1000, "n_queries": 500, "query_n": 500, "engine_version": "26.12.1"}
    if build:
        base["engine_backend"] = build
    return [dict(base, rep=i, query_p50_ms=80.0 if i == 0 else 10.0 + i, query_p99_ms=300.0 if i == 0 else 20.0 + i) for i in range(6)]


def _dense_passes(arm, build=None):
    base = {"backend": arm, "build_s": 10.0, "recall_at_10": 0.95, "engine_version": "26.12.1"}
    if build:
        base["engine_backend"] = build
    return [dict(base, p50=9.0 if i == 0 else 1.0, p99=12.0) for i in range(5)]


def _arc_arms(X):
    """The ArcadeDB arms of the sparse overlay that the page requires: (arm token, backend key)."""
    return [(a, b) for a, b, _l in X.SPARSE_MP_ARMS if a.startswith("arc_")]


def _write_sparse(root, X, tiers=TIERS, native=True, skip=()):
    """A sparse directory as the rerun leaves it: the plain file of every required arm at each tier (the page's six, less Elasticsearch and Milvus, which no chain
    of the rerun runs) and, with `native`, the native file of every ArcadeDB arm."""
    root.mkdir(parents=True, exist_ok=True)
    for arm, backend, _l in X.SPARSE_MP_ARMS:
        if arm in ("elastic", "milvus"):
            continue
        for tier in tiers:
            (root / f"sp_{arm}_{tier}.json").write_text(json.dumps(_sparse_passes(backend, tier)))
            if native and arm.startswith("arc_"):
                (root / f"sp_{arm}_native_{tier}.json").write_text(json.dumps(_sparse_passes(backend, tier, "native")))
    for name in skip:
        (root / name).unlink()


def _write_dense(root, native=True, skip=()):
    root.mkdir(parents=True, exist_ok=True)
    for arm in DENSE_ARMS:
        for k in (1, 2, 3):
            (root / f"mp_{arm}_b{k}.json").write_text(json.dumps(_dense_passes(arm)))
            if native:
                (root / f"mp_{arm}_native_b{k}.json").write_text(json.dumps(_dense_passes(arm, "native")))
    for name in skip:
        (root / name).unlink()


def _sparse_rows(X, builds=("jvm", "native"), tiers=TIERS):
    return [_row("l3s", t, b, bld) for t in tiers for _a, b in _arc_arms(X) for bld in builds]


def _dense_rows(builds=("jvm", "native")):
    return [_row("l3d", "small", DENSE_KEYS[a], bld) for a in DENSE_ARMS for bld in builds]


@contextlib.contextmanager
def _landing(rows=(), sparse=True, dense=True, native_files=True, skip=()):
    """(exporter, scratch results dir) for a landing at the NEW pin whose large rows are on the OLD one, with the frozen rows `rows`, `sparse_mp_<NEW>` and
    `dense_mp5_small_<NEW>` complete (or less the file names in `skip`, which name a file of either directory). Everything it moves is put back."""
    import export_web as X
    import make_paper_tables as M
    with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ), mock.patch.object(M, "RESULTS", d), mock.patch.object(X, "RESULTS", Path(d)), \
            mock.patch.object(X, "_SPLIT", True), mock.patch.object(X, "_FROZEN_ROWS", list(rows)):
        for k in _CLEAR:
            os.environ.pop(k, None)
        os.environ["BENCH_ENGINE_COMMIT"] = NEW
        os.environ[SC.LARGE_PIN_VAR] = OLD
        os.environ["BENCH_MP_ARMS"] = ",".join(DENSE_ARMS)
        d = Path(d)
        if sparse:
            _write_sparse(d / f"sparse_mp_{NEW}", X, native=native_files, skip=[n for n in skip if n.startswith("sp_")])
        if dense:
            _write_dense(d / f"dense_mp5_small_{NEW}", native=native_files, skip=[n for n in skip if n.startswith("mp_")])
        yield X, d


# ------------------------------------------------------------------------------------------------ 1. a missing native or tiny file is a stop
def test_a_complete_overlay_with_native_rows_reads_both_builds_of_both_tables():
    import export_web as X
    with _landing(_sparse_rows(X) + _dense_rows()) as (X, _d):
        sp = X._sparse_multipass_table()["entries"]
        assert {t: sum(1 for e in sp if e["scale"] == t and e.get("build") == "native") for t in TIERS} == {"small": 3, "tiny": 3}
        dn = X._dense_overlay_entries("small")
        assert sum(1 for e in dn if e.get("build") == "native") == 4, [e["backend"] for e in dn]


def test_each_missing_native_sparse_file_refuses_and_names_the_file():
    import export_web as X
    for tier in TIERS:
        for arm, _b in _arc_arms(X):
            name = f"sp_{arm}_native_{tier}.json"
            with _landing(_sparse_rows(X), dense=False, skip=[name]) as (X, d):
                msg = _refusal(X._sparse_multipass_table)
                assert name in msg and "1 of 3 native overlay files are missing" in msg and f"sparse_mp_{NEW}" in msg and "l3s" in msg, (name, msg)


def test_every_native_sparse_file_removed_refuses_and_a_tier_that_has_none_is_the_tier_with_native_rows():
    import export_web as X
    with _landing(_sparse_rows(X), dense=False, native_files=False) as (X, _d):          # the rehearsal's case: all of them gone, the all-or-none rule passes it
        msg = _refusal(X._sparse_multipass_table)
        assert "3 of 3 native overlay files are missing" in msg and "sp_arc_int8_native_small.json" in msg, msg
    with _landing(_sparse_rows(X, tiers=("tiny",)), dense=False, native_files=False) as (X, d):
        msg = _refusal(X._sparse_multipass_table)
        assert "native overlay files are missing" in msg and "sp_arc_int8_native_tiny.json" in msg and "native_small" not in msg, msg    # the rows decide the tier


def test_a_missing_tiny_file_refuses_when_the_rows_hold_tiny_and_names_the_file():
    import export_web as X
    with _landing(_sparse_rows(X, builds=("jvm",)), dense=False, skip=["sp_arc_int8_tiny.json"]) as (X, _d):
        msg = _refusal(X._sparse_multipass_table)
        assert f"sparse_mp_{NEW} has 1 of 4 files missing (sp_arc_int8_tiny.json); no fallback" in msg, msg
    with _landing(_sparse_rows(X, builds=("jvm",)), dense=False) as (X, d):              # all there: it reads
        assert {e["scale"] for e in X._sparse_multipass_table()["entries"]} == {"small", "tiny"}


def test_a_tier_with_no_row_and_no_file_is_absent_and_a_tier_with_files_and_no_row_is_read():
    import export_web as X
    with _landing(_sparse_rows(X, builds=("jvm",), tiers=("small",)), dense=False, skip=["sp_arc_int8_tiny.json"]) as (X, d):
        assert {e["scale"] for e in X._sparse_multipass_table()["entries"]} == {"small", "tiny"}      # no tiny row: the tiny file is optional as before (the other arms' files are read)
    with _landing(_sparse_rows(X, builds=("jvm",), tiers=("small",)), dense=False) as (X, d):
        for f in d.glob(f"sparse_mp_{NEW}/sp_*_tiny.json"):
            f.unlink()
        assert {e["scale"] for e in X._sparse_multipass_table()["entries"]} == {"small"}              # no tiny row, no tiny file: absent, nothing to refuse
    with _landing(_sparse_rows(X, builds=("jvm",)), sparse=False, dense=False) as (X, d):
        assert X._sparse_multipass_table() is None                                                    # no directory at all: the lane has not run


def test_each_missing_native_dense_file_of_the_small_overlay_refuses_and_names_the_file():
    import export_web as X
    for arm in DENSE_ARMS:
        name = f"mp_{arm}_native_b2.json"
        with _landing(_dense_rows(), sparse=False, skip=[name]) as (_x, _d):
            msg = _refusal(X._dense_overlay_entries, "small")
            assert name in msg and "1 of 12 native overlay files are missing" in msg and f"dense_mp5_small_{NEW}" in msg and "l3d" in msg, (name, msg)
    with _landing(_dense_rows(), sparse=False, native_files=False) as (X, _d):                    # the rehearsal's case: the native files of the new small overlay gone
        msg = _refusal(X._dense_overlay_entries, "small")
        assert "12 of 12 native overlay files are missing" in msg and "mp_fp32_native_b1.json" in msg, msg


def test_a_table_with_no_native_rows_requires_no_native_file():
    import export_web as X
    rows = _sparse_rows(X, builds=("jvm",)) + _dense_rows(builds=("jvm",))
    with _landing(rows, native_files=False) as (X, _d):
        assert len(X._sparse_multipass_table()["entries"]) == 8                                   # the plain files only: four arms per tier
        assert len(X._dense_overlay_entries("small")) == 4
    with _landing([], native_files=False) as (X, _d):                                             # no frozen rows at all (every older test of the exporter)
        assert X._sparse_multipass_table() and X._dense_overlay_entries("small")


def test_an_arm_the_native_chain_did_not_run_owes_no_native_file():
    import export_web as X
    rows = [r for r in _sparse_rows(X) if not (r["engine_backend"] == "native" and r["backend"] != "arcadedb_sparse_embedded")] + \
           [r for r in _dense_rows() if not (r["engine_backend"] == "native" and r["backend"] != "arcadedb_dense_embedded")]
    keep_sparse = {f"sp_arc_int8_native_{t}.json" for t in TIERS}
    keep_dense = {f"mp_fp32_native_b{k}.json" for k in (1, 2, 3)}
    with _landing(rows) as (X, d):
        for f in list(d.glob(f"sparse_mp_{NEW}/sp_*_native_*.json")) + list(d.glob(f"dense_mp5_small_{NEW}/mp_*_native_*.json")):
            if f.name not in keep_sparse | keep_dense:
                f.unlink()
        assert sum(1 for e in X._sparse_multipass_table()["entries"] if e.get("build") == "native") == 2
        assert sum(1 for e in X._dense_overlay_entries("small") if e.get("build") == "native") == 1


def test_the_large_dense_overlay_is_not_held_to_native_files_and_one_helper_serves_both_tables():
    import export_web as X
    with _landing(_sparse_rows(X) + _dense_rows() + [_row("l3d", "deep10m", "arcadedb_dense_embedded", "native", OLD)]) as (X, d):
        _write_dense(d / f"dense_mp5_{OLD}", native=False)                                          # the 9.99M overlay holds the JVM files only: the large class is the gate's
        assert X._dense_overlay_entries("deep10m")
        seen = []
        with mock.patch.object(NO, "refuse_missing_native", side_effect=lambda root, owed, lane, tier, label: seen.append((lane, tier, len(owed)))):
            X._sparse_multipass_table()
            X._dense_overlay_entries("small")
            X._dense_overlay_entries("deep10m")
        assert seen == [("l3s", "small", 3), ("l3s", "tiny", 3), ("l3d", "small", 12)], seen    # one function, the sparse tiers and the dense small size, never the large size
    assert (HERE / "export_web.py").read_text(encoding="utf-8").count("_NO.refuse_missing_native(") == 2                  # no third copy of the rule


# ------------------------------------------------------------------------------------------------ 2. the equivalence registry
def _served(backend, rep, server_commit="6c9f2d8e3aaa"):
    return {"lane": "e2", "scale": "e2", "workload": "hybrid", "backend": backend, "rep": rep, "engine_backend": "native", "engine_commit": "5b8e1c7d2a94",
            "server_engine_commit": server_commit, "engine_version": "server:26.12.1 (build 6c9f2d8e3)", "server_settings": {"arcadedb.txWalFlush": "0"},
            "server_mode": "development", "server_cpus": 4, "server_max_heap_bytes": 2 << 30}


def test_the_refusal_without_a_registry_entry_ends_with_the_registry_and_the_generator_once():
    import arm_identity as AI
    rows = [_served(b, rep) for b in ("arcadedb_e2_server", "arcadedb_graph_server") for rep in (1, 2, 3)]
    problems = AI.server_settings_problems(rows)
    assert [p for p in problems if "reports engine commit" in p] == [
        f"{b}: the native server reports engine commit 6c9f2d8e3 and the row names 5b8e1c7d2" for b in ("arcadedb_e2_server", "arcadedb_graph_server")]      # the sentences as before
    hint = AI.registry_hint(problems)
    assert hint.count("engine_commit_equiv.json") == 1 and hint.count("make_engine_commit_equiv.py") == 1 and "PUBLISHING.md" in hint, hint
    assert AI.registry_hint([p for p in problems if "no read-back" in p]) == "" and AI.registry_hint([]) == ""      # other problems carry no hint
    src = (HERE / "export_web.py").read_text(encoding="utf-8")
    assert 'raise SystemExit("REFUSING: " + "; ".join(_bad) + _AI.registry_hint(_bad))' in src


def test_a_row_that_claims_the_equivalence_with_no_registry_entry_names_the_generator_too():
    import export_web as X
    row = dict(_served("arcadedb_e2_server", 1), server_engine_commit_equiv="6c9f2d8e3aaa")
    tables = [{"entries": [{"backend_key": "arcadedb_e2_server"}]}]
    with mock.patch.object(X._EP, "_equiv_registry", return_value={}):
        msg = _refusal(X._native_server_equiv_note, tables, [row])
    assert "engine_commit_equiv.json has no release pair for it" in msg and "make_engine_commit_equiv.py" in msg, msg


def test_the_registry_file_is_in_the_list_step_6_commits():
    got = L.tracked_artifacts(None)
    assert "experiments/engine_commit_equiv.json" in got and got[0] == "experiments/results/runs_paper.csv", got
    assert L.tracked_artifacts(L.REPO / "experiments" / "results" / "pycost.json")[0] == "experiments/results/pycost.json"
    assert "tracked = tracked_artifacts(_pycost)" in (HERE / "land_stage.py").read_text(encoding="utf-8")
    for doc in ("PUBLISHING.md", "CAMPAIGN.md"):
        text = (HERE / doc).read_text(encoding="utf-8")
        assert "engine_commit_equiv.json" in text and "make_engine_commit_equiv.py" in text, doc


# ------------------------------------------------------------------------------------------------ 3. the files the exporter will need, before the merge
def _gaps(X, rows, d, scope=(), comparator_pins=()):
    return L.overlay_gaps([], rows, NEW, scope=scope, results=d, comparator_pins=comparator_pins)


def test_the_pre_merge_check_lists_the_missing_sparse_files_and_the_step_that_makes_each():
    import export_web as X
    rows = _sparse_rows(X)
    with _landing(rows, dense=False, skip=["sp_qdrant_small.json", "sp_qdrant_tiny.json"]) as (X, d):                     # the comparators' files are not on the host
        got = _gaps(X, rows, d)
        assert got == {f"sparse_mp_{NEW}": ["sp_qdrant_small.json", "sp_qdrant_tiny.json"]}, got
        text = L.format_overlay_gaps(got)
        assert "made by: the comparators' chain" in text and "BENCH_COMPARATOR_PIN" in text and "Nothing was merged" in text and "sp_qdrant_small.json" in text, text
    with _landing(rows, dense=False, skip=[f"sp_arc_{a}_{t}.json" for a in ("int8", "fp32", "srv") for t in ("small",)] + ["sp_arc_srv_native_small.json"]) as (X, d):
        got = _gaps(X, rows, d)                                                          # the union not pre-created: the comparator copy made the directory
        assert got[f"sparse_mp_{NEW}"] == ["sp_arc_int8_small.json", "sp_arc_fp32_small.json", "sp_arc_srv_small.json", "sp_arc_srv_native_small.json"], got
        text = L.format_overlay_gaps(got)
        assert "made by: the ArcadeDB chains" in text and "union" in text and "Two chains, one pin, one landing" in text, text
    with _landing(rows, dense=False) as (X, d):
        assert _gaps(X, rows, d) == {}                                                    # complete: nothing to say


def test_the_pre_merge_check_reads_the_dense_overlays_and_the_native_files_the_rows_call_for():
    import export_web as X
    rows = _dense_rows()
    with _landing(rows, sparse=False, skip=["mp_fp32_native_b1.json", "mp_arcsrv_b3.json"]) as (_x, d):
        _write_dense(d / f"dense_mp5_{OLD}", native=False, skip=["mp_int8_b1.json"])           # the large overlay: the plain list only, at the large pin
        got = _gaps(X, rows, d)
        assert got == {f"dense_mp5_{OLD}": ["mp_int8_b1.json"], f"dense_mp5_small_{NEW}": ["mp_arcsrv_b3.json", "mp_fp32_native_b1.json"]}, got
        text = L.format_overlay_gaps(got)
        assert "--overlay-merge" in text and "mp_fp32_native_b1.json" in text and text.count("made by:") == 2, text      # one step for the dense files of each directory
    with _landing(rows, sparse=False) as (X, d):                                          # an absent directory is a lane that has not run, as for the exporter
        shutil.rmtree(d / f"dense_mp5_small_{NEW}")
        assert _gaps(X, rows, d) == {}


def test_the_pre_merge_check_reads_the_rows_at_the_pins_only_and_is_silent_when_it_cannot_decide():
    import export_web as X
    old_native = [_row("l3s", "small", b, "native", OLD) for _a, b in _arc_arms(X)]          # a native row of the old release (the store's, at a pin of no table here)
    with _landing([], dense=False, native_files=False) as (X, d):
        assert _gaps(X, old_native, d) == {}                                              # not at the pin of its size class: owes nothing
        assert _gaps(X, [], d) == {}
        assert list(_gaps(X, _sparse_rows(X), d)) == [f"sparse_mp_{NEW}"]
        assert _gaps(X, _sparse_rows(X), d, scope={"l2", "e2"}) == {}                      # a scope without l3s and l3d: nothing of this check is owed
        with mock.patch.dict(sys.modules, {"export_web": None}):
            assert L.overlay_gaps([], _sparse_rows(X), NEW, results=d) is None            # the exporter cannot be read: silent, not a finding


def _land(argv, prep, store, pulled, env=None):
    """(outcome, the commands the landing ran, the bytes of the store before and after) for land_stage.main() in a scratch tree: `prep(results)` builds the overlay
    directories, every command succeeds and does nothing."""
    cmds = []

    def fake_sh(cmd, **_kw):
        cmds.append(" ".join(str(c) for c in cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ), mock.patch.object(sys, "argv", ["land_stage.py", *argv]), \
            mock.patch.object(L, "PY", sys.executable), mock.patch.object(L.os, "execv", lambda *a, **k: None), mock.patch.object(L, "sh", fake_sh), \
            mock.patch.object(L, "SCRATCH", Path(t) / "scratch"), mock.patch.object(L, "RESULTS", Path(t) / "results"), \
            mock.patch.object(L, "SITE_PAYLOAD", Path(t) / "site.json"), mock.patch.object(L, "PAYLOAD", Path(t) / "harness.json"), \
            contextlib.redirect_stdout(io.StringIO()) as out:
        t = Path(t)
        (t / "results").mkdir()
        for k in _CLEAR:
            os.environ.pop(k, None)
        os.environ.update(env or {})
        (t / "results" / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in store))
        (t / "pulled.jsonl").write_text("".join(json.dumps(r) + "\n" for r in pulled))
        os.environ["BENCH_LAND_PULLED_FILE"] = str(t / "pulled.jsonl")
        prep(t / "results")
        before = (t / "results" / "runs.jsonl").read_bytes()
        try:
            outcome = f"returned {L.main()}"
        except SystemExit as e:
            outcome = f"refused: {e.code}"
        after = (t / "results" / "runs.jsonl").read_bytes()
    return outcome, cmds, (before, after), out.getvalue()


def test_the_landing_refuses_before_the_merge_for_missing_overlay_files_and_writes_nothing():
    import export_web as X
    rows = _sparse_rows(X)
    argv = ["--pin", NEW, "--large-pin", OLD, "--only-lanes", "l3s", "--message", "m"]

    def union_only(res):                                                                   # the ArcadeDB union is pre-created, the comparators' files are not on the host
        _write_sparse(res / f"sparse_mp_{NEW}", X, skip=["sp_qdrant_small.json", "sp_qdrant_tiny.json"])

    outcome, cmds, (before, after), _text = _land(argv, union_only, [], rows)
    assert outcome.startswith("refused: REFUSING: the exporter reads overlay files that are not in experiments/results/"), outcome
    assert f"sparse_mp_{NEW}: 2 file(s), sp_qdrant_small.json, sp_qdrant_tiny.json" in outcome and "made by: the comparators' chain" in outcome, outcome
    assert not any("merge_campaign" in c or "refresh_web_page" in c for c in cmds) and before == after, (cmds, outcome)       # nothing reached the store, no gate ran
    outcome, cmds, _b, text = _land(argv + ["--dry-run"], lambda res: _write_sparse(res / f"sparse_mp_{NEW}", X), [], rows)    # complete: the check says nothing
    assert outcome == "returned 0" and "DRY RUN" in text, (outcome, text[-300:])
    outcome, cmds, (before, after), text = _land(argv + ["--dry-run"], union_only, [], rows)                                  # a dry run says it, and stops as it always does, with rc 1 (#163)
    assert outcome == "returned 1" and "WOULD REFUSE (the run without --dry-run stops here): the exporter reads overlay files" in text and "sp_qdrant_small.json" in text, (outcome, text[-400:])
    assert "would refuse (WOULD REFUSE above), so this dry run exits 1." in text and "DRY RUN" in text, text[-400:]
    assert before == after


# ------------------------------------------------------------------------------------------------ 4. the e4 pre-read, 5. the log
def test_the_e4_pre_read_says_to_copy_the_directory_first_and_keeps_its_cause():
    with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ), mock.patch.dict(sys.modules):
        for k in [k for k in os.environ if k.startswith("BENCH_")]:
            del os.environ[k]
        os.environ["BENCH_RESULTS_DIR"] = t
        sys.modules.pop("export_web", None)
        payload = Path(t) / "site.json"
        payload.write_text(json.dumps({"tables": [{"id": "l3s"}]}))
        msg = _refusal(L._published_lanes, payload, pin=NEW, scope={"l3s", "e4"})
    assert msg.startswith("REFUSING: cannot read which lanes") and f"e4decomp_{NEW} missing; E4 is pinned only" in msg and "Nothing was pulled or merged." in msg, msg
    assert f"/e4decomp_{NEW}/: copy that directory into experiments/results/e4decomp_{NEW}/ first" in msg and "comes before the pull" in msg, msg
    assert "run the e4 lane" in msg                                                         # the exporter's own words stand; the copy is said after them


def test_the_log_says_which_scp_misses_are_expected_and_when_the_comparators_files_are_already_there():
    with tempfile.TemporaryDirectory() as t, mock.patch.object(L, "HOST", "mini"):
        root, res = Path(t) / "host", Path(t) / "results"
        (root / L.host_name("sparse_mp", COMP)).mkdir(parents=True)
        (root / L.host_name("sparse_mp", COMP) / "sp_qdrant_small.json").write_text("q")
        (res / f"sparse_mp_{NEW}").mkdir(parents=True)
        (res / f"sparse_mp_{NEW}" / "sp_qdrant_small.json").write_text("by hand")

        def scp(cmd, check=True):
            for g in glob.glob(cmd[-2].split(":", 1)[1]):
                shutil.copy(g, cmd[-1])

        other = Path(t) / "other"
        other.mkdir()
        out = io.StringIO()
        with mock.patch.object(L, "REMOTE", str(root)), contextlib.redirect_stdout(out):
            L.pull_sparse_overlays(NEW, OLD, results=res, scp=scp, comparator_pins=[COMP])                  # the landing holds the file the host has
            L.pull_sparse_overlays(NEW, OLD, results=other, scp=scp, comparator_pins=["ffffffff1"])         # the host holds nothing at that pin
        text = out.getvalue()
        assert "1 file(s) are already in the landing's directory, none to add" in text and "none to add from" not in text, text
        assert "none on mini:sparse_mp_ffffffff1" in text and "the check before the merge names what is then missing" in text, text
    src = (HERE / "land_stage.py").read_text(encoding="utf-8")
    assert "scp: No such file or directory lines for the sparse, medium and e4 directories are expected" in src


if __name__ == "__main__":
    names = [n for n in sorted(globals()) if n.startswith("test_") and (len(sys.argv) < 2 or any(a in n for a in sys.argv[1:]))]
    for n in names:
        globals()[n]()
        print("ok", n)
    print(len(names), "passed")
