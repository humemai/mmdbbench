"""land_stage names a failed or missing small ArcadeDB cell before the merge (humemai/mmdbbench#147).

Run with `python -m pytest test_land_stage_small_cells.py -q` from this directory. Synthetic rows only: no store, no host.

The freeze drops every row with rc != 0 BEFORE it keeps the newest row of a key, so a repetition that failed at the new pin, or never ran
at it, keeps the row of the older release, and the pair gate refuses the size class naming its tables and not the cell. `stale_small_cells`
lists those cells (lane, scale, workload, arm, build) and the repetitions, from the store and the rows about to merge; the landing prints it
as a warning and goes on.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import land_stage as L  # noqa: E402

NEW, OLD = "d1ce4d8c0", "a3a5d1245"


def _row(lane="l3d", scale="small", workload="search", backend="arcadedb_dense_embedded", build="native", rep=1, commit=NEW,
         version="26.12.1", rc=0, ts="2026-12-05T10:00:00+00:00", **extra):
    r = {"instrument": "2026-11", "lane": lane, "scale": scale, "workload": workload, "backend": backend, "engine_backend": build,
         "rep": rep, "engine_commit": commit, "engine_version": version, "rc": rc, "ts_utc": ts}
    r.update(extra)
    return r


def _old(**kw):
    return _row(commit=OLD, version="26.11.1", ts="2026-11-10T10:00:00+00:00", **kw)


def _cell_rows(commit_kw, **cell):
    """Three repetitions of one cell, as the old release or the new one measured them."""
    return [(_old if commit_kw == "old" else _row)(rep=rep, **cell) for rep in (1, 2, 3)]


def _names(stale):
    return [(name[:5], sorted(why)) for name, why in stale]


def test_a_cell_with_an_rc0_row_at_the_pin_for_every_repetition_is_not_listed():
    store = _cell_rows("old")
    landing = _cell_rows("new")
    assert L.stale_small_cells(store, landing, NEW) == []
    assert L.format_stale_small_cells([], NEW) == []


def test_a_repetition_that_failed_at_the_pin_is_named_and_the_older_row_the_freeze_keeps_is_said():
    store = _cell_rows("old")
    landing = [_row(rep=1), _row(rep=2), _row(rep=3, rc=1)]
    stale = L.stale_small_cells(store, landing, NEW)
    assert _names(stale) == [(("l3d", "small", "search", "arcadedb_dense_embedded", "native"), [3])]
    assert stale[0][1][3] == f"failed at the pin (rc=1), the freeze keeps 26.11.1 at {OLD}"


def test_a_cell_that_never_ran_at_the_pin_is_named_for_every_repetition_the_old_release_measured():
    store = _cell_rows("old") + _cell_rows("old", backend="arcadedb_dense_server", build="jvm")
    landing = _cell_rows("new", backend="arcadedb_dense_server", build="jvm")
    stale = L.stale_small_cells(store, landing, NEW)
    assert _names(stale) == [(("l3d", "small", "search", "arcadedb_dense_embedded", "native"), [1, 2, 3])]
    assert set(stale[0][1].values()) == {f"no row at the pin, the freeze keeps 26.11.1 at {OLD}"}


def test_a_failed_cell_with_nothing_older_says_so():
    stale = L.stale_small_cells([], [_row(rep=1, rc=137), _row(rep=2), _row(rep=3)], NEW)
    assert stale[0][1] == {1: "failed at the pin (rc=137), no rc=0 row at any pin"}


def test_the_two_builds_of_one_arm_are_two_cells_and_the_newest_row_at_the_pin_is_the_one_read():
    store = _cell_rows("old", build="jvm") + _cell_rows("old", build="native")
    landing = _cell_rows("new", build="native") + [_row(build="jvm", rep=1), _row(build="jvm", rep=2), _row(build="jvm", rep=3, rc=1)]
    stale = L.stale_small_cells(store, landing, NEW)
    assert _names(stale) == [(("l3d", "small", "search", "arcadedb_dense_embedded", "jvm"), [3])]
    # a retry that succeeded after a failure at the pin leaves nothing to name
    landing.append(_row(build="jvm", rep=3, ts="2026-12-05T12:00:00+00:00"))
    assert L.stale_small_cells(store, landing, NEW) == []


def test_the_view_arm_that_ran_without_the_view_is_its_own_cell():
    store = _cell_rows("old", lane="l2", scale="sf1full", workload="olap", backend="arcadedb_graph_embedded", build="jvm") + \
        _cell_rows("old", lane="l2", scale="sf1full", workload="olap", backend="arcadedb_graph_embedded", build="jvm", gav=False)
    landing = _cell_rows("new", lane="l2", scale="sf1full", workload="olap", backend="arcadedb_graph_embedded", build="jvm")
    stale = L.stale_small_cells(store, landing, NEW)
    assert [(n[4], n[6]) for n, _w in stale] == [("jvm", "nogav")]
    assert any("(no view)" in line for line in L.format_stale_small_cells(stale, NEW))


def test_the_durability_class_is_part_of_the_cell_and_a_relaxed_row_does_not_stand_in_for_a_failed_strict_one():
    store = _cell_rows("old", durability_class="strict") + _cell_rows("old")                       # a row with no class is relaxed
    landing = [_row(rep=rep, durability_class="strict", rc=1 if rep == 2 else 0) for rep in (1, 2, 3)] + _cell_rows("new")
    stale = L.stale_small_cells(store, landing, NEW)
    assert [(n[5], sorted(w)) for n, w in stale] == [("strict", [2])]
    assert "arcadedb_dense_embedded [native] strict: rep 2 failed at the pin (rc=1)" in L.format_stale_small_cells(stale, NEW)[1]


def test_a_row_of_a_retired_corpus_in_the_store_is_not_a_second_cell():
    """n_docs is in the freeze's key but not in the cell: a retired corpus that shares a scale name never reaches the freeze (PAPER_CORPUS)."""
    store = _cell_rows("old", n_docs=1_000_000, dims=100) + _cell_rows("old", n_docs=1_000_000, dims=30_109)    # two corpora, one cell
    assert len(L.stale_small_cells(store, [], NEW)) == 1
    assert L.stale_small_cells(store, _cell_rows("new", n_docs=1_000_000, dims=30_109), NEW) == []


def test_only_small_arcadedb_cells_of_the_instrument_in_scope_and_in_the_repetitions_that_land_are_read():
    store = (
        _cell_rows("old", scale="deep10m")                                              # a large size
        + _cell_rows("old", lane="l3s", scale="tiny", backend="arcadedb_sparse_embedded")  # an extra size
        + _cell_rows("old", backend="qdrant_dense", build=None)                         # a comparator
        + [dict(r, instrument="2026-10") for r in _cell_rows("old", workload="other")]  # another instrument
        + _cell_rows("old", lane="e2", scale="e2", workload="hybrid", backend="arcadedb_e2", build="jvm")   # a lane outside the scope below
        + [_old(workload="capped", rep=4)]                                              # a repetition that never lands
    )
    assert L.stale_small_cells(store, [], NEW, scope={"l3d"}, max_rep=3) == []
    unscoped = L.stale_small_cells(store, [], NEW, max_rep=3)
    assert [n[0] for n, _w in unscoped] == ["e2"]
    assert [n[0] for n, _w in L.stale_small_cells(store, [], NEW, scope={"e2", "l3d"}, max_rep=3)] == ["e2"]
    capped_off = L.stale_small_cells(store, [], NEW, scope={"l3d"}, max_rep=0)           # no cap: the rep 4 row counts
    assert [(n[2], sorted(w)) for n, w in capped_off] == [("capped", [4])]


def test_a_commit_stamp_shorter_or_longer_than_the_pin_is_at_the_pin():
    assert L.stale_small_cells([], [_row(rep=r, commit=c) for r, c in ((1, NEW[:6]), (2, NEW + "abcdef012"), (3, NEW))], NEW) == []
    # a row with no commit is not at the pin; it is the row the freeze would keep, and the warning says its commit is unknown
    assert L.stale_small_cells([], [_row(rep=1, commit=None)], NEW)[0][1] == {1: "no row at the pin, the freeze keeps 26.12.1 at ?"}


def test_the_warning_names_lane_scale_workload_arm_and_build_and_caps_a_long_list():
    store = [_old(workload=f"w{i}", rep=1) for i in range(5)]
    stale = L.stale_small_cells(store, [], NEW)
    lines = L.format_stale_small_cells(stale, NEW, limit=3)
    assert lines[0].lstrip().startswith("WARNING: 5 small-class ArcadeDB cell(s)") and NEW in lines[0]
    assert "naming its tables and not the cell" in lines[0]
    assert lines[1].strip().startswith("l3d small w0 arcadedb_dense_embedded [native]: rep 1 no row at the pin")
    assert len(lines) == 1 + 3 + 1 and lines[-1].strip() == "... and 2 more cell(s)"
