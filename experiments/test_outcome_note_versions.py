"""The note of a cell with no result names the engine version the cell ran on (humemai/mmdbbench#205, decided 2026-11-27).

A rerun that leaves a failed or censored cell out keeps its old outcome on the page, while the engine's other rows move to a new version: DuckPGQ's
transaction cells ran out of memory on DuckDB 1.5.6 and its analytics row moves to 2.0.1. A failed run records no `engine_version` (the runner
writes its row, not the engine), so `export_web._outcome_version` reads it from the finished runs of the log on the same engine.
Light: rows in memory. Run with pytest, or as plain functions from this directory.
"""
import pytest

import export_web as E

OLD, NEW = "e85469273", "a3a5d1245"
DUCK_OLD, DUCK_NEW = "duckdb:1.5.6 + duckpgq:61f5d082", "duckdb:2.0.1 + duckpgq:7e300af593"


def _failed(backend, lane="l2", scale="sf1", workload="oltp", commit=OLD, image=None, **kw):
    row = {"lane": lane, "scale": scale, "workload": workload, "backend": backend, "engine_commit": commit, "rep": 1, "rc": -1,
           "error": "timeout_after_7200s", "topology": "client_server" if image else "embedded", "run_id": f"{lane}_{backend}_{scale}"}
    if image:
        row["server_image"] = image
    row.update(kw)
    return row


def _finished(backend, version, lane="l2", scale="sf1full", workload="olap", commit=OLD, image=None):
    row = {"lane": lane, "scale": scale, "workload": workload, "backend": backend, "engine_commit": commit, "rep": 1, "rc": 0,
           "engine_version": version, "topology": "client_server" if image else "embedded"}
    if image:
        row["server_image"] = image
    return row


@pytest.fixture()
def notes(monkeypatch):
    """`notes(table_id, rows)` -> the outcome sentences the exporter writes for a table from a run log holding `rows`."""
    monkeypatch.setattr(E, "_rule_censored", lambda taken, clean: {})      # the cap rule is another test's business
    monkeypatch.delenv("BENCH_ENGINE_COMMIT", raising=False)
    monkeypatch.delenv("BENCH_COMPARATOR_PIN", raising=False)

    def run(table_id, rows):
        monkeypatch.setattr(E, "_run_log_rows", lambda: rows)
        monkeypatch.setattr(E, "_CENSORED_CACHE", None)
        return E._censored_notes(table_id)
    return run


def test_an_old_outcome_names_the_old_version_while_the_engine_has_moved(notes):
    (note,) = notes("l2", [_failed("duckpgq_graph"),
                           _finished("duckpgq_graph", DUCK_OLD),
                           _finished("duckpgq_graph", DUCK_NEW, commit=NEW)])
    assert note.endswith("The run used DuckDB 1.5.6 + DuckPGQ 61f5d082."), note
    assert "2.0.1" not in note, note
    (record,) = [r for r in E._GENERATED if r["text"] == note]
    assert "DuckDB 1.5.6 + DuckPGQ 61f5d082" in record["values"], record["values"]     # page_check: every digit is a registered value


def test_the_failed_runs_own_version_wins(notes):
    (note,) = notes("l2", [_failed("duckpgq_graph", engine_version=DUCK_NEW), _finished("duckpgq_graph", DUCK_OLD)])
    assert "The run used DuckDB 2.0.1 + DuckPGQ 7e300af593." in note, note


def test_a_served_arm_with_no_finished_run_reads_the_engine_of_its_server_image(notes):
    (note,) = notes("l3d", [_failed("cratedb_dense", lane="l3d", scale="small", workload="search", image="sha256:aaa"),
                            _finished("cratedb_tpc", "CrateDB 6.4.6", lane="l1tpc", scale="tpch1", image="sha256:aaa"),
                            _finished("cratedb_tpc", "CrateDB 6.4.7", lane="l1tpc", scale="tpch1", commit=NEW, image="sha256:bbb")])
    assert "The run used CrateDB 6.4.6." in note, note


def test_an_in_process_arm_with_no_finished_run_reads_the_engine_at_its_harness_commit(notes):
    (note,) = notes("l3d", [_failed("surrealdb_dense", lane="l3d", scale="small", workload="search"),
                            _finished("surrealdb_tpc", "surrealdb-embedded:2.3.10 (sdk 2.0.0)", lane="l1tpc", scale="tpch1"),
                            _finished("surrealdb_tpc", "surrealdb-embedded:9.9.9 (sdk 2.0.0)", lane="l1tpc", scale="tpch1", commit=NEW),
                            _finished("surrealdb_tpc_server", "surrealdb-server:3.2.4+20260803.93ab219", lane="l1tpc", scale="tpch1", image="sha256:ccc")])
    assert "The run used SurrealDB 2.3.10." in note, note


def test_engines_that_share_a_sentence_are_each_named_with_their_version(notes):
    (note,) = notes("l2olap", [
        _failed("surrealdb_graph", scale="sf1full", workload="olap"),
        _failed("surrealdb_graph_server", scale="sf1full", workload="olap", image="sha256:ccc"),
        _finished("surrealdb_graph", "surrealdb-embedded:2.3.10 (sdk 2.0.0)", scale="sf1", workload="oltp"),
        _finished("surrealdb_graph_server", "surrealdb-server:3.2.4+20260803.93ab219", scale="sf1", workload="oltp", image="sha256:ccc")])
    assert "SurrealDB 2.3.10 for SurrealDB (embedded)" in note and "SurrealDB 3.2.4 for SurrealDB (server)" in note, note
    assert "The runs used " in note, note


def test_the_engines_own_words_stay_last_in_a_failed_note(notes):
    (note,) = notes("l2", [_failed("duckpgq_graph", error="ValueError: boom"), _finished("duckpgq_graph", DUCK_OLD)])
    assert "The run used DuckDB 1.5.6 + DuckPGQ 61f5d082. What it reported: " in note, note


def test_an_arcadedb_outcome_names_the_release(notes):
    (note,) = notes("l2", [_failed("arcadedb_graph_server", commit=NEW, image="sha256:ddd",
                                   server_engine_version="26.11.1 (build 0f3bb2238c3cfc79c4a1c2cf2d8c5e36489652c0/1/UNKNOWN)")])
    assert "The run used ArcadeDB 26.11.1." in note, note


def test_an_export_with_no_version_to_name_is_refused(notes):
    with pytest.raises(SystemExit, match="names the engine version"):
        notes("l2", [_failed("duckpgq_graph"), _finished("duckpgq_graph", DUCK_NEW, commit=NEW)])


def test_two_versions_for_one_run_are_refused(notes):
    with pytest.raises(SystemExit, match="DuckDB 1.5.6"):
        notes("l2", [_failed("duckpgq_graph"), _finished("duckpgq_graph", DUCK_OLD), _finished("duckpgq_graph", DUCK_NEW)])
