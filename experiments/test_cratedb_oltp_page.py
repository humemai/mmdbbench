"""The page sentences that CrateDB's transactional rows (landing round 2, comparator pin e85469273) turn wrong or leave blank (humemai/mmdbbench#59, refs #52).

CrateDB has no multi-statement transaction, so its new-order and payment are not expressible; its insert, read, update and delete run as single statements and
write the `l1tpc/<size>/cratedb_tpc/oltp` rows. The adapter declares the two transactions as `res_<query>_digest = unexpressible: <reason>`; the reason is followed by the
engine's own answer to the probe (`; the probe statement raised SyntaxError: ... io.crate.protocols.postgres.PostgresWireProtocol ...`, a Java stack trace). The preview
of the first rows (10 of 12) made `page_check` refuse the page with 72 `postgres` keys in prose, all from that stack trace.

Light: no files except one temporary runs.jsonl. Run with pytest, or as plain functions from this directory. What each test proves is in its docstring.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("BENCH_RESULTS_DIR", tempfile.mkdtemp(prefix="cratedb-page-"))
os.environ.setdefault("BENCH_ONLY_LANES", "l1tpc")
import export_web as EW  # noqa: E402
import page_check as PC  # noqa: E402

REASON = ("CrateDB has no multi-statement transaction (a statement is its unit; COMPARATORS.md 'CrateDB', "
          "https://cratedb.com/docs/crate/reference/en/latest/sql/statements/begin.html), so TPC-C's new-order and payment, "
          "each one ACID transaction over three statements, cannot be written for it")
TRACE = ("the probe statement raised SyntaxError: line 1:1: extraneous input 'ROLLBACK' expecting {<EOF>, 'SELECT'}\nCONTEXT: io.crate.sql.parser.SqlParser$1.syntaxError(SqlParser.java:80)\n"
         "io.crate.protocols.postgres.PostgresWireProtocol.handleSimpleQuery(PostgresWireProtocol.java:851)")
DIGEST = "unexpressible: " + REASON + "; " + TRACE


def _restore(name, old):
    setattr(EW, name, old)


# ---------------------------------------------------------------- (b) the reason, not the engine's answer
def test_a_declared_reason_stops_where_the_engines_own_answer_starts():
    assert EW._declared_reason(DIGEST) == REASON
    assert EW._declared_reason("unexpressible: no read; tried `SELECT 1` and the engine answered: parse error [1:8]") == "no read"
    assert EW._declared_reason("unexpressible: situation 'empty' issues no read") == "situation 'empty' issues no read"
    assert "postgres" not in EW._declared_reason(DIGEST) and "\n" not in EW._declared_reason(DIGEST)


def test_the_unexpressible_cells_read_the_reason_and_the_page_check_finds_no_raw_key_in_its_sentences():
    """The preview failed `page_check` with 72 raw keys; the sentences of `_unexpressible_notes` are the ones that carried them."""
    tmp = Path(tempfile.mkdtemp(prefix="cratedb-rows-"))
    row = {"lane": "l1tpc", "workload": "oltp", "backend": "cratedb_tpc", "scale": "tpch1", "rep": 1,
           "res_neworder_digest": DIGEST, "res_payment_digest": DIGEST, "res_stock_digest": DIGEST, "res_payments_digest": DIGEST}
    (tmp / "runs.jsonl").write_text(json.dumps(row) + "\n")
    old = (EW.RESULTS, EW._UNEXPRESSIBLE_CACHE, dict(EW._DECLARED_ABSENCES), EW._TABLE_LANE.get("docs_oltp"))
    try:
        EW.RESULTS, EW._UNEXPRESSIBLE_CACHE = tmp, None
        EW._DECLARED_ABSENCES.clear()
        cells = EW._unexpressible_cells()
        assert cells[("l1tpc", "oltp", "cratedb_tpc")] == {q: REASON for q in ("neworder", "payment", "payment" + "s", "stock")}
        notes = EW._unexpressible_notes("docs_oltp", [{"backend": "CrateDB", "backend_key": "cratedb_tpc", "scale": "tpch1"}])
        assert len(notes) == 1 and REASON in notes[0] and "postgres" not in notes[0].lower(), notes
        payload = {"tables": [{"id": "docs_oltp", "conditions": notes, "declared_absences": EW._DECLARED_ABSENCES["docs_oltp"], "entries": []}]}
        assert PC._check_raw_backend_keys(payload) == 0
    finally:
        EW.RESULTS, EW._UNEXPRESSIBLE_CACHE = old[0], old[1]
        EW._DECLARED_ABSENCES.clear()
        EW._DECLARED_ABSENCES.update(old[2])


# ---------------------------------------------------------------- (a) the declared absence of new-order and payment
def _table():
    cols = ["ingest s", "insert p50 ms", "new-order p50 ms", "new-order p99 ms", "payment p50 ms", "OLTP ops/s"]
    crate = {"ingest s": {"median": 185.0, "n": 3}, "insert p50 ms": {"median": 0.4, "n": 3}}
    pg = {c: {"median": 1.0, "n": 3} for c in cols}
    return {"id": "docs_oltp", "columns": cols, "entries": [
        {"backend": "CrateDB", "backend_key": "cratedb_tpc", "scale": "tpch1", "metrics": crate},
        {"backend": "PostgreSQL", "backend_key": "postgres", "scale": "tpch1", "metrics": pg}]}


def test_the_blank_transaction_cells_of_cratedb_are_declared_not_expressible_and_no_sentence_says_it_did_not_run_the_workload():
    """On main the four blank cells read 'CrateDB was not run on the transaction workload: it runs the analytics workload of this lane only', which is false
    once the insert, read, update and delete rows of the same table exist; the declaration is the adapter's reason, per column, kind 'unexpressible'."""
    old = (EW._UNEXPRESSIBLE_CACHE, EW._FROZEN_ROWS, dict(EW._DECLARED_ABSENCES))
    try:
        EW._UNEXPRESSIBLE_CACHE = {("l1tpc", "oltp", "cratedb_tpc"): {"neworder": REASON, "payment": REASON, "stock": REASON, "payments": REASON}}
        EW._FROZEN_ROWS = [{"lane": "l1tpc", "workload": "oltp", "backend": "cratedb_tpc", "scale": "tpch1"}]
        EW._DECLARED_ABSENCES.clear()
        t = _table()
        EW._declare_arm_runs_absences([t])
        EW._declare_unexpressible_columns([t])
        got = EW._DECLARED_ABSENCES["docs_oltp"]
        assert {(a["backend"], a["column"], a["kind"]) for a in got} == {("CrateDB", c, "unexpressible") for c in
                                                                        ("new-order p50 ms", "new-order p99 ms", "payment p50 ms", "OLTP ops/s")}, got
        assert all(REASON in a["why"] and "not run" not in a["why"] and "analytics" not in a["why"] for a in got), got
        assert not any(a["backend"] == "PostgreSQL" for a in got)
        # the arm that has no row on the workload at all keeps the old plain sentence
        EW._FROZEN_ROWS = []
        EW._DECLARED_ABSENCES.clear()
        EW._declare_arm_runs_absences([_table()])
        assert {a["kind"] for a in EW._DECLARED_ABSENCES["docs_oltp"]} == {"not measured"}
    finally:
        EW._UNEXPRESSIBLE_CACHE, EW._FROZEN_ROWS = old[0], old[1]
        EW._DECLARED_ABSENCES.clear()
        EW._DECLARED_ABSENCES.update(old[2])


# ---------------------------------------------------------------- (c) the JVM memory sentence
def _mem_table(arms):
    """arms: {label: [(scale, GiB, heap)]}"""
    return {"id": "docs_oltp", "entries": [{"backend": label, "backend_key": label, "scale": s, "scale_label": {"tpch1": "TPC-H SF1 (6.0M line items)", "tpch10": "TPC-H SF10 (60.0M line items)"}.get(s, s), "heap": h, "metrics": {"peak memory GiB": {"median": g}}}
                                           for label, rows in arms.items() for s, g, h in rows]}


def test_the_memory_example_is_one_cell_with_its_own_heap_and_names_its_size():
    """Every JVM arm of the real tables ran a different heap at each size (the heap follows the memory cap: CrateDB 4g and 8g, ArcadeDB 8g and 16g), so an example
    that required one heap on the whole table was dropped from docs_oltp, docs_olap, l2 and e2. The example is one cell of the column, read against the heap that cell ran,
    and named by its size when the table has several. An arm that ran one heap on the table comes first, the highest per cent of its heap; with none, the highest cell."""
    old = (EW._entry_heaps, EW._heap_not_pinned)
    try:
        EW._entry_heaps = lambda e, lane, wl, exact_only=False: {e["heap"]}
        EW._heap_not_pinned = lambda e, lane, wl: False
        both = EW._jvm_memory_note_fixed_heap(_mem_table({"CrateDB": [("tpch1", 5.72, "4g"), ("tpch10", 10.9, "8g")],
                                                           "ArcadeDB (server)": [("tpch1", 3.27, "8g"), ("tpch10", 5.2, "8g")]}))
        assert "ArcadeDB (server) and CrateDB run on a JVM" in both
        assert "ArcadeDB (server)'s 5.20 GiB at TPC-H SF10 is about 65 per cent of its 8g heap" in both and "CrateDB's" not in both, both      # one heap first
        none = EW._jvm_memory_note_fixed_heap(_mem_table({"CrateDB": [("tpch1", 5.72, "4g"), ("tpch10", 10.9, "8g")]}))
        assert none.startswith("CrateDB runs on a JVM") and "CrateDB's 5.72 GiB at TPC-H SF1 is about 143 per cent of its 4g heap" in none, none   # no arm of one heap
        one = EW._jvm_memory_note_fixed_heap(_mem_table({"CrateDB": [("tpch1", 5.72, "4g"), ("tpch10", 10.9, "4g")]}))
        assert "CrateDB's 10.90 GiB at TPC-H SF10 is about 272 per cent of its 4g heap" in one, one
        single = EW._jvm_memory_note_fixed_heap(_mem_table({"Neo4j": [("sf1", 13.81, "12g")]}))
        assert "Neo4j's 13.81 GiB here is about 115 per cent of its 12g heap" in single, single      # a table of one size is unchanged
        # the figures of the sentence are the cells': the GiB, the heap and the per cent are computed from them, never typed
        assert all(rec["values"] for rec in EW._GENERATED if rec["text"] == both)
    finally:
        EW._entry_heaps, EW._heap_not_pinned = old


# ---------------------------------------------------------------- (d) the cold column
def test_the_cold_column_names_cratedbs_first_query_by_its_display_name():
    """CrateDB's first query is the insert (no new-order): the sentence printed the harness field 'crud_insert' in prose."""
    lane, wl = EW.OCT_COLD_SOURCE["docs_oltp"]
    rows = [{"lane": lane, "workload": wl, "cold_first_query_name": "new-order"}, {"lane": lane, "workload": wl, "cold_first_query_name": "crud_insert"}]
    text = EW._cold_note("docs_oltp", rows)
    assert "crud_insert" not in text and "insert / new-order" in text, text


# ---------------------------------------------------------------- (d) the settings of the single-statement table
def test_the_settings_read_back_from_cratedbs_single_statement_table_are_declared_not_printed():
    """The preview made page_check A2 say 'UNCOVERED l1tpc: 2 measured field(s) are neither a column nor declared: cratedb_crud_refresh_interval_ms, cratedb_crud_shards'."""
    import re
    for field in ("cratedb_crud_shards", "cratedb_crud_refresh_interval_ms"):
        assert any(re.search(pat, field) for pat, _why in PC.NOT_PRINTED), field
    assert not any(re.search(pat, "crud_insert_p50_ms") for pat, _why in PC.NOT_PRINTED)      # a result field is not swallowed


# ---------------------------------------------------------------- (d) one version string per engine
def test_cratedb_prints_the_same_version_string_on_the_document_tables_and_the_durability_table():
    """The preview made version_consistency_check fail: 'CrateDB publishes 2 different version strings: crate 6.4.6, cratedb 6.4.6'. The document tables name the engine from
    its server image repo (`crate`, the pin table's version), the durability table from the row's own string ('CrateDB 6.4.6', no image). The rows record the product name,
    and every other engine spells its product name (the image 'mongo' prints as 'mongodb', 'postgres' as 'postgresql': _ENGINE_SPELLING), so CrateDB is 'cratedb'."""
    image = "crate@sha256:e7bded344df487e2595f59d7edaa0cf96979a00ba51f12ee66d7fcf8cd65f5f4"
    docs = EW._engine_version("CrateDB", "6.4.6", image=image, commit=None)                  # the call of the document tables: the image's pinned version
    durability = EW._engine_version("CrateDB", "CrateDB 6.4.6", image=None)                  # the call of the durability table: the row's own string
    assert docs == durability == "cratedb 6.4.6", (docs, durability)
    mongo_docs = EW._engine_version("MongoDB", "9.0.4", image="mongo@sha256:" + "0" * 64, commit=None)
    assert mongo_docs == EW._engine_version("MongoDB", "mongodb 9.0.4", image=None) == "mongodb 9.0.4"    # the precedent this follows


# ---------------------------------------------------------------- the declared reason, said once
QUERIES = ("neworder", "payment", "payments", "stock")
ONCE = ("CrateDB cannot express new-order and payment (and the payments and stock checks that read their end state) on this table: the adapter declared them "
        "not expressible rather than leaving them blank (" + REASON + ").")


def test_the_declared_reason_is_said_once_per_engine_and_the_structured_absences_are_unchanged():
    """The four digests of CrateDB carry one reason; the page said it four times, once per raw query key ('does not answer neworder', 'payments', 'stock')."""
    old = (EW._UNEXPRESSIBLE_CACHE, dict(EW._DECLARED_ABSENCES), list(EW._GENERATED))
    try:
        EW._UNEXPRESSIBLE_CACHE = {("l1tpc", "oltp", "cratedb_tpc"): {q: REASON for q in QUERIES}}
        EW._DECLARED_ABSENCES.clear()
        notes = EW._unexpressible_notes("docs_oltp", [{"backend": "CrateDB", "backend_key": "cratedb_tpc", "scale": "tpch1"}])
        assert notes == [ONCE], notes
        assert "neworder" not in notes[0] and notes[0].count(REASON) == 1
        got = EW._DECLARED_ABSENCES["docs_oltp"]                                  # one per query, exactly as before (the reason text is the adapter's)
        assert [(a["backend"], a["column"], a["kind"], a["query"]) for a in got] == [("CrateDB", None, "unexpressible", q) for q in QUERIES[:0] + ("neworder", "payment", "payments", "stock")]
        for a in got:
            assert a["why"] == (f"CrateDB does not answer {a['query']} on this table: the engine's own language cannot express it, declared by the adapter "
                                f"rather than left blank ({REASON}).")
        assert not any("does not answer" in r["text"] for r in EW._GENERATED[len(old[2]):])      # the per-query lines are no longer page conditions
    finally:
        EW._UNEXPRESSIBLE_CACHE = old[0]
        EW._DECLARED_ABSENCES.clear()
        EW._DECLARED_ABSENCES.update(old[1])


def test_the_answer_check_sentence_says_the_reason_once_with_the_queries_named_as_the_table_names_them():
    import equivalence_check as EQ
    row = {"lane": "l1tpc", "scale": "tpch1", "workload": "oltp", "backend": "cratedb_tpc", "rc": 0, "instrument": EQ.REQUIRED_INSTRUMENT}
    row.update({f"res_{q}_digest": DIGEST for q in QUERIES})
    text = EW._equivalence_notes([row])["docs_oltp"]
    assert text.count(REASON) == 1 and "neworder" not in text, text
    assert "CrateDB cannot express new-order and payment (and the payments and stock checks that read their end state): " + REASON in text, text


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
