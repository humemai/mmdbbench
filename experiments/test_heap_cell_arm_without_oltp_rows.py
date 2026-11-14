"""The JVM heap cell follows the rows the memory cell reads, also for an arm that has no transactional rows (2026-11-14, numbers verification).

On the document tables the memory cell is the transactional run's, and an arm with no transactional rows keeps what it has (`[oltp rows] or rs`
in export_web.main). The heap column asked for the transactional rows only, so CrateDB, which has analytics rows only in the n=3 landing, printed
its peak memory with no heap beside it, at both sizes of both document tables (4g at tpch1, 8g at tpch10 in its rows). The heap now reads the
same rows as the memory cell: the transactional ones where the arm has them, else the arm's own rows of the table's lane. This does not depend
on the CrateDB transactional rows that are being added.
Light: no files. Run with pytest, or as plain functions from this directory.
"""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("BENCH_RESULTS_DIR", tempfile.mkdtemp(prefix="heap-no-oltp-"))
os.environ.setdefault("BENCH_ONLY_LANES", "l1tpc")
import export_web as EW  # noqa: E402


def _row(backend, workload, scale, heap, rep=1):
    return {"lane": "l1tpc", "scale": scale, "workload": workload, "backend": backend, "rep": rep, "durability_class": "relaxed",
            "heap": heap, "server_heap": heap}


def _entry(backend, scale):
    return {"backend": EW.display_name(backend), "backend_key": backend, "scale": scale,
            "metrics": {"ingest s": {"median": 5.0, "n": 3}, "peak memory GiB": {"median": 1.5, "n": 3}}}


def _finished(table_id, rows, entries):
    old = list(EW._FROZEN_ROWS)
    try:
        EW._FROZEN_ROWS[:] = rows
        table = {"id": table_id, "columns": ["ingest s", "peak memory GiB"], "entries": entries}
        return EW._finish_table(table)
    finally:
        EW._FROZEN_ROWS[:] = old


def test_an_arm_with_analytics_rows_only_gets_its_heap_on_both_document_tables():
    rows = [_row("cratedb_tpc", "olap", "tpch1", "4g"), _row("cratedb_tpc", "olap", "tpch10", "8g")]
    for table_id in ("docs_oltp", "docs_olap"):
        table = _finished(table_id, rows, [_entry("cratedb_tpc", "tpch1"), _entry("cratedb_tpc", "tpch10")])
        heaps = {e["scale"]: (e["metrics"].get("JVM heap") or {}).get("text") for e in table["entries"]}
        assert heaps == {"tpch1": "4g", "tpch10": "8g"}, (table_id, heaps)
        assert "JVM heap" in table["columns"], table["columns"]


def test_where_an_arm_has_transactional_rows_they_decide_the_heap_as_before():
    # the memory cell reads the transactional run, so the heap printed beside it is that run's, not the analytics run's
    rows = [_row("arcadedb_server", "oltp", "tpch1", "8g"), _row("arcadedb_server", "olap", "tpch1", "16g")]
    table = _finished("docs_oltp", rows, [_entry("arcadedb_server", "tpch1")])
    assert table["entries"][0]["metrics"]["JVM heap"] == {"text": "8g"}, table["entries"][0]["metrics"]


def test_an_arm_that_records_no_heap_prints_none():
    rows = [_row("postgres", "olap", "tpch1", None)]
    table = _finished("docs_oltp", rows, [_entry("postgres", "tpch1")])
    assert "JVM heap" not in table["entries"][0]["metrics"], table["entries"][0]["metrics"]
    assert "JVM heap" not in table["columns"], table["columns"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
