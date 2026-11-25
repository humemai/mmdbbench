"""A comparator that no chain of the pass runs is declared, not owed (mmdbbench#21, decided 2026-11-24).

The 26.12.1 pass runs the ArcadeDB arms of the sparse, time-series, lifecycle and server restart tables, and the comparators of those lanes only where a chain
runs them. So their tables say "<engine> was not run at this release." for a comparator with no row, the roster gate takes that declaration, and the sparse second
pass asks for no Qdrant file when Qdrant has no row and no file. What stays strict is held here too: a partial engine, a lane that is rerun, and a Qdrant that ran.
Light: dictionaries only. Run with pytest from this directory.
"""
import contextlib
import io
from unittest import mock

import export_web as X
import page_check as PC
import runner as RN

NOT_RUN = "was not run at this release."
LANE_OF = {"l3s": "l3s", "l4": "l4", "lifecycle": "lifecycle", "restart": "restart"}


def _entry(key):
    return {"backend": X.display_name(key), "backend_key": key, "is_arcadedb": key.startswith("arcadedb"), "scale": "small", "metrics": {"p50 ms": {"median": 1.0}}}


def _table(tid, extra=()):
    """The table of a lane with its ArcadeDB arms, plus the arms `extra`, and the rows behind them."""
    lane = LANE_OF[tid]
    keys = [a for a in RN.LANES[lane][1] if a.startswith("arcadedb")] + list(extra)
    return ({"id": tid, "entries": [_entry(k) for k in keys], "columns": ["p50 ms"], "conditions": []},
            [{"lane": lane, "backend": k, "scale": "small"} for k in keys])


def _declare(table, rows):
    """(the "not run" sentences, the table with its declarations) as the exporter writes them."""
    with mock.patch.object(X, "_FROZEN_ROWS", rows), mock.patch.dict(X._DECLARED_ABSENCES, clear=True):
        _head, tail = X._oct_conditions(table)
        said = [t for t in tail if t.endswith(NOT_RUN)]
        return said, dict(table, declared_absences=list(X._DECLARED_ABSENCES[table["id"]]))


def _roster(tables):
    """(findings, output) of the roster gate over these tables only."""
    out = io.StringIO()
    lanes = {LANE_OF[t["id"]] for t in tables}
    with mock.patch.object(PC, "_ONLY_LANES", lanes), mock.patch.object(PC, "_lane_has_rows", lambda lane, wl: False), contextlib.redirect_stdout(out):
        _checked, bad = PC._check_lane_roster({"tables": tables})
    return bad, out.getvalue()


def test_every_comparator_with_no_row_is_declared_and_the_roster_gate_takes_it():
    done = []
    for tid in LANE_OF:
        table, rows = _table(tid)
        said, out = _declare(table, rows)
        assert said and len(said) == len(set(said)), (tid, said)
        done.append(out)
    bad, text = _roster(done)
    assert bad == 0, text
    by_id = {t["id"]: {a["backend"] for a in t["declared_absences"] if a["kind"] == "not measured"} for t in done}
    assert {"Qdrant", "pgvector"} <= by_id["l3s"] and "TimescaleDB" in by_id["l4"] and by_id["lifecycle"] == {"SurrealDB"} and "Neo4j" in by_id["restart"], by_id


def test_the_coverage_table_reads_the_declarations_and_names_them_in_its_legend():
    done = []
    for tid in LANE_OF:
        table, rows = _table(tid)
        done.append(dict(_declare(table, rows)[1], title=tid))
    with mock.patch.dict(X._DECLARED_ABSENCES, clear=True):
        coverage = X._multimodel_table(done)                           # it refuses a declared kind that its legend does not name
    surreal = next(e for e in coverage["entries"] if e["backend"] == "SurrealDB")
    assert surreal["metrics"]["l4"]["text"] == "declared, not measured", surreal["metrics"]
    assert "not measured, the engine was not run on that table" in coverage["conditions"][0], coverage["conditions"]


def test_without_the_declarations_the_roster_gate_refuses_the_same_tables():
    bad, text = _roster([dict(_table(tid)[0], declared_absences=[]) for tid in LANE_OF])
    assert bad > 0 and "no row and no declaration" in text, text


def test_a_comparator_with_a_row_is_not_declared_and_a_partial_engine_is_still_refused():
    table, rows = _table("l3s", extra=["qdrant_sparse"])
    said, out = _declare(table, rows)
    assert f"Qdrant {NOT_RUN}" not in said and f"pgvector {NOT_RUN}" in said, said
    bad, text = _roster([out])
    assert bad == 1 and "qdrant_sparse_uint8" in text, text                                    # one Qdrant arm ran and the other did not: a finding
    table, rows = _table("l4")
    with mock.patch.object(X, "_censored_cells", lambda: {("l4", "ts100", "timescaledb", "olap"): 3600.0}):
        said, _out = _declare(table, rows)                                                     # a cell that failed was run: no frozen row, an outcome of its own
    assert f"TimescaleDB {NOT_RUN}" not in said and f"DuckDB {NOT_RUN}" in said, said


def test_a_lane_with_no_row_and_a_lane_that_is_rerun_declare_nothing():
    table, _rows = _table("l4")
    assert X._unrun_comparators(table, []) == []
    assert X._unrun_comparators({"id": "l2", "entries": []}, [{"lane": "l2", "backend": "arcadedb_graph_server"}]) == []


def test_the_sparse_second_pass_holds_qdrant_to_its_files_only_when_it_was_run(tmp_path):
    ran = X.sparse_run_arms([tmp_path], [{"lane": "l3s", "backend": "arcadedb_sparse_server"}])
    assert "qdrant" not in ran and {"arc_int8", "arc_fp32", "arc_srv"} <= ran, ran
    assert not [f for f in X.sparse_files_owed("small", [], ran)[0] if "qdrant" in f]
    assert "qdrant" in X.sparse_run_arms([tmp_path], [{"lane": "l3s", "backend": "qdrant_sparse"}])      # its row owes the file
    (tmp_path / "sp_qdrant_uint8_small.json").write_text("[]")
    assert "qdrant" not in X.sparse_run_arms([tmp_path])                                                  # the uint8 arm's file is not Qdrant's
    (tmp_path / "sp_qdrant_tiny.json").write_text("[]")
    assert "qdrant" in X.sparse_run_arms([tmp_path])                                                      # one file at one tier owes the others
