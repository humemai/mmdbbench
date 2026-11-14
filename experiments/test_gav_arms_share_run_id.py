"""The two arms of ArcadeDB's Graph Analytical View (l2 olap) write the same run_id for one rep (humemai/mmdbbench#77, refs #52).

The landing of round 2 had none of the 18 GAV-on rows of l2 olap sf1full: the four-arm merge keyed on (engine_backend, run_id), and the answer check's newest_per_cell on run_id,
so the later no-GAV row replaced the GAV-on row. Every other key of the pipeline already carries the arm (merge_campaign.key, make_paper_tables' freeze, post1_rows); the tests
below pin that too, so a rerun on a later wheel replaces the row of the SAME arm only. Light: no files except a temporary results directory.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("BENCH_ONLY_LANES", "l2")
import equivalence_check as EQ  # noqa: E402
import merge_campaign as MC  # noqa: E402

BASE = {"lane": "l2", "backend": "arcadedb_graph_embedded", "workload": "olap", "scale": "sf1full", "rep": 1, "engine_backend": "jvm", "instrument": "2026-11",
        "engine_version": "26.11.1", "engine_commit": "a3a5d1245", "rc": 0, "run_id": "l2_arcadedb_graph_embedded_olap_sf1full_r1"}


def on(ts="2026-11-07T22:46:15+00:00", **kw):
    return dict(BASE, gav=True, ts_utc=ts, **kw)


def off(ts="2026-11-07T22:50:54+00:00", **kw):
    return dict(BASE, gav=False, backend_arm="nogav", ts_utc=ts, **kw)


POST2 = {"engine_version": "26.11.1.post2", "wheel_label": "26.11.1.post2"}


def test_the_answer_check_keeps_both_arms_of_a_rep_and_the_newest_row_of_each():
    rows = EQ.newest_per_cell([on(q=1), off(q=2), on(ts="2026-11-13T01:00:00+00:00", q=3)])
    assert sorted((r["gav"], r["q"]) for r in rows) == [(False, 2), (True, 3)], rows
    both = EQ.newest_per_cell([on(), dict(on(), engine_backend="native")])
    assert len(both) == 2                                                    # the JVM and the native chain share the run_id too


def test_the_canonical_key_keeps_both_arms_and_a_post_row_replaces_only_its_own_arm():
    """Regression guard: this key already carries gav. The post2 GAV-on row (later ts) replaces the 26.11.1 GAV-on row and leaves the no-GAV row alone."""
    best = MC.canonicalise([on(q=1), off(q=2), on(ts="2026-11-13T01:00:00+00:00", q=3, **POST2)])
    assert sorted((r["gav"], r["q"]) for r in best.values()) == [(False, 2), (True, 3)], best


def test_the_freeze_keeps_both_arms_and_a_post_row_replaces_only_its_own_arm():
    """The freeze (make_paper_tables.load_canonical) on a results directory holding the two arms of rep 1 and a post2 row of the GAV-on arm."""
    import make_paper_tables as M
    d = Path(tempfile.mkdtemp(prefix="gav-freeze-"))
    rows = [on(q=1), off(q=2), on(ts="2026-11-13T01:00:00+00:00", q=3, **POST2)]
    (d / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    old = M.RESULTS
    try:
        M.RESULTS = str(d)
        got = [r for r in M.load_canonical() if r.get("lane") == "l2" and r.get("workload") == "olap"]
    finally:
        M.RESULTS = old
    assert sorted((str(r.get("gav")), r.get("q")) for r in got) == [("False", 2), ("True", 3)], got
    assert {r["engine_version"] for r in got if r.get("gav") is not False} <= {"26.11.1", "26.11.1.post2"}
    assert [r["gav"] for r in got].count(False) == 1 and any(r.get("backend_arm") == "nogav" for r in got if r.get("gav") is False)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
