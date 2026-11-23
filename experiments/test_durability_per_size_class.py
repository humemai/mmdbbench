"""The durability table respects the size class (mmdbbench#145).

The durability table pools the rows of operations that have no scale of their own (one record inserted, one person and one edge inserted) from the
lanes that time them, at every size they ran. Until the large sizes are rerun, the small rows of an ArcadeDB arm are on one release and its large rows on
another, and an entry prints one release beside one median, so the table makes one entry per size class: the class is in the grouping key, in the
Size label (`Small: ...`, `Large: ...`) and in the entry's `size_class`, which `version_consistency_check` reads per class.

Held here, with synthetic frozen rows and a small synthetic payload (no data, no engine):

- small rows on the new release and large rows on the old one make two entries per operation, each with its own release, and every gate passes:
  the exporter's `_one_version`, `version_consistency_check` and `page_check._check_build_pair`;
- two releases inside one size class are still refused by each of them, with the table, the size class and both values in the message;
- the table still counts its operations once (not once per size class), the page names the release of its rows by size, and the comparators, whose
  rows are the same release at both sizes, still print one entry per size class and nothing is pooled across classes;
- a row at a size with no class is refused, like on every table that prints a size.
Light: dictionaries and a temporary payload file only. Run with pytest, or as plain functions from this directory.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("BENCH_RESULTS_DIR", tempfile.mkdtemp(prefix="durability-per-size-"))
os.environ.setdefault("BENCH_ONLY_LANES", "l2,l3d")   # the exporter refuses to load without the E4 overlay unless the lanes are scoped
import arm_identity as AI  # noqa: E402
import export_web as EW  # noqa: E402
import page_check as PC  # noqa: E402
import size_classes as SC  # noqa: E402
import version_consistency_check as VC  # noqa: E402

OLD, OLD_SHA = "26.11.1", "a3a5d1245"
NEW, NEW_SHA = EW.FINAL_SMALL_RELEASE, "0123abcde"


# ------------------------------------------------------------------ synthetic frozen rows of the lanes that time a write
def _row(lane, scale, workload, backend, release, sha, cls, rep, p50, build=None, field="neworder_p50_ms"):
    row = {"lane": lane, "scale": scale, "workload": workload, "backend": backend, "rep": rep, "durability_class": cls, field: p50,
           "engine_version": release, "engine_commit": sha, "host": "bench-host", "image": None,
           "durability": "fsync at commit" if cls == "strict" else "no flush at commit"}
    if build:
        row["engine_backend"] = build
    return row


def _arcadedb_rows(scale, release, sha, p50):
    """The one-record insert of the document lane at one size: two builds, both durability classes, two repetitions."""
    return [_row("l1tpc", scale, "oltp", "arcadedb_embedded", release, sha, cls, rep, p50 * (4 if cls == "strict" else 1), build=build,
                 field="crud_insert_p50_ms")
            for build in AI.BUILDS for cls in ("relaxed", "strict") for rep in (1, 2)]


def _comparator_rows(scale, p50):
    return [_row("l1tpc", scale, "oltp", "sqlite", "sqlite 3.46.1", None, cls, rep, p50 * (3 if cls == "strict" else 1), field="crud_insert_p50_ms")
            for cls in ("relaxed", "strict") for rep in (1, 2)]


def _table(rows):
    """The durability table the exporter builds from these rows, as a split page (both ArcadeDB builds side by side)."""
    was = EW._SPLIT
    EW._SPLIT = True
    try:
        return EW._durability_table(rows)
    finally:
        EW._SPLIT = was


def _inserts(table):
    return [e for e in table["entries"] if e["operation"] == "doc_insert"]


SMALL_NEW_LARGE_OLD = (_arcadedb_rows("tpch1", NEW, NEW_SHA, 0.2) + _arcadedb_rows("tpch10", OLD, OLD_SHA, 0.3)
                       + _comparator_rows("tpch1", 0.25) + _comparator_rows("tpch10", 0.26))


# ------------------------------------------------------------------ the table: one entry per size class
def test_small_rows_on_one_release_and_large_rows_on_another_are_two_entries_each_with_its_release():
    table = _table(SMALL_NEW_LARGE_OLD)                    # before the change this refused: the pooled group named two releases
    arcadedb = [e for e in _inserts(table) if e["is_arcadedb"]]
    assert len(arcadedb) == 4, [(e["backend"], e["scale"]) for e in arcadedb]                  # two builds at two size classes
    for e in arcadedb:
        want = (NEW, NEW_SHA) if e["size_class"] == "small" else (OLD, OLD_SHA)
        assert e["version_name"] == f"arcadedb {want[0]} · {want[1]}", e
        assert e["scale_label"].startswith(f"{e['size_class'].capitalize()}: one record inserted (documents)"), e["scale_label"]
        assert e["size_corpus"] == "one record inserted (documents)" and e["operation"] == "doc_insert", e
    assert {e["scale"] for e in arcadedb} == {"doc_insert_small", "doc_insert_large"}
    # The comparator's rows are one release at both sizes, and are not pooled across the two classes either: one entry per class, the numbers its own.
    sqlite = [e for e in _inserts(table) if e["backend"] == "SQLite"]
    assert [e["size_class"] for e in sqlite] == ["small", "large"], sqlite
    assert [e["metrics"]["no wait ms"]["median"] for e in sqlite] == [0.25, 0.26]
    # Small before large inside the operation, so the page reads down one size class at a time.
    assert [e["size_class"] for e in _inserts(table) if e["backend"] == "SQLite"] == ["small", "large"]
    assert [e["size_class"] for e in arcadedb][:2] == ["small", "small"] and [e["size_class"] for e in arcadedb][2:] == ["large", "large"]


def test_the_table_still_counts_its_operations_once_and_names_the_release_of_its_rows_by_size():
    table = _table(SMALL_NEW_LARGE_OLD)
    scope = next(c for c in table["conditions"] if c.startswith("This table holds"))
    assert scope.startswith("This table holds 1 document operation."), scope              # one operation at two size classes is one operation
    payload = {"conditions": ["A condition that was there before."], "tables": [table]}
    EW._classify_sizes(payload)
    want = f"Engine version of the ArcadeDB rows: small size, {NEW}; large size, {OLD}."
    assert want in table["conditions"], table["conditions"]
    assert {e["size_class"] for e in table["entries"]} == {"small", "large"}              # `_classify_sizes` keeps the class the table gave
    assert table["sizes"] == []                                                          # the Size column is an operation, not a corpus


def test_a_row_at_a_size_without_a_class_is_refused():
    rows = _arcadedb_rows("tpch1", NEW, NEW_SHA, 0.2) + _arcadedb_rows("tpch1000", OLD, OLD_SHA, 0.3)
    try:
        _table(rows)
    except SystemExit as exc:
        assert "SIZE_CLASS" in str(exc) and "tpch1000" in str(exc), exc
    else:
        raise AssertionError("a size with no class reached the durability table")


def test_the_cross_model_transaction_keeps_one_entry_per_catalog_size_and_names_its_class():
    rows = [dict(_row("e2", scale, "hybrid", "arcadedb_e2", release, sha, cls, rep, p50 * (4 if cls == "strict" else 1), field="hybrid_p50_ms"))
            for scale, release, sha, p50 in (("e2", NEW, NEW_SHA, 7.0), ("e2_500k", OLD, OLD_SHA, 8.0))
            for cls in ("relaxed", "strict") for rep in (1, 2)]
    table = _table(rows)
    entries = [e for e in table["entries"] if e["operation"] == "crossmodel_txn"]
    assert [(e["scale"], e["size_class"]) for e in entries] == [("crossmodel_txn_50k", "small"), ("crossmodel_txn_500k", "large")], entries
    assert [e["version_name"] for e in entries] == [f"arcadedb {NEW} · {NEW_SHA}", f"arcadedb {OLD} · {OLD_SHA}"]
    assert entries[0]["scale_label"] == "Small: one transaction across three models (cross-model, 50k products)", entries[0]["scale_label"]


# ------------------------------------------------------------------ the gates, with a durability table in the payload
def _payload(table):
    return {"conditions": ["A condition that was there before."], "tables": [table]}


def _version_consistency(payload):
    with tempfile.TemporaryDirectory() as d:
        path = Path(d, "payload.json")
        path.write_text(json.dumps(payload))
        with contextlib.redirect_stdout(io.StringIO()):
            return VC.check(str(path))


def _page_check_pair(payload, rows):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        bad = PC._check_build_pair(payload, rows)
    return bad, out.getvalue()


def test_every_gate_passes_small_rows_on_the_new_release_and_large_rows_on_the_old_one():
    table = _table(SMALL_NEW_LARGE_OLD)
    payload = _payload(table)
    EW._classify_sizes(payload)
    failures = _version_consistency(payload)
    assert failures == [], failures                                              # before the change: "arcadedb wears 2 versions on one page"
    bad, text = _page_check_pair(payload, SMALL_NEW_LARGE_OLD)
    assert bad == 0, text
    # The same payload with the class taken off the entries (what the exporter wrote before): the gate sees one pooled group and fails.
    flat = json.loads(json.dumps(payload))
    for e in flat["tables"][0]["entries"]:
        e["size_class"] = None
    assert any("arcadedb wears 2 versions" in f for f in _version_consistency(flat))


def test_two_releases_inside_one_size_class_are_refused_by_the_exporter_with_the_table_the_class_and_both_values():
    rows = _arcadedb_rows("tpch1", NEW, NEW_SHA, 0.2) + [dict(r, engine_version=OLD, engine_commit=OLD_SHA) for r in _arcadedb_rows("tpch1", NEW, NEW_SHA, 0.2)
                                                          if r["rep"] == 2]
    try:
        _table(rows)
    except SystemExit as exc:
        text = str(exc)
        assert "table durability" in text and "small size" in text and NEW in text and OLD in text, text
    else:
        raise AssertionError("one size class pooled two releases")
    # The large class alone: the same refusal names the large size.
    rows = [dict(r, engine_version=OLD if r["rep"] == 1 else "26.10.2") for r in _arcadedb_rows("tpch10", OLD, OLD_SHA, 0.3)]
    try:
        _table(rows)
    except SystemExit as exc:
        assert "large size" in str(exc) and "26.10.2" in str(exc) and OLD in str(exc), exc
    else:
        raise AssertionError("one size class pooled two releases")


def test_two_releases_inside_one_size_class_fail_the_version_consistency_check_and_the_page_check():
    entry = lambda release, sha, cls: {"backend": "ArcadeDB (embedded)", "version_name": f"arcadedb {release} · {sha}", "size_class": cls}   # noqa: E731
    table = {"id": "durability", "entries": [entry(NEW, NEW_SHA, "small"), entry(OLD, OLD_SHA, "small"), entry(OLD, OLD_SHA, "large")]}
    failures = _version_consistency({"tables": [table]})
    family = [f for f in failures if f.startswith("arcadedb wears 2 versions")]
    assert len(family) == 1 and "in the small size" in family[0] and "table durability" in family[0] and NEW in family[0] and OLD in family[0], failures
    label = [f for f in failures if "publishes 2 different version strings" in f]
    assert len(label) == 1 and "in the small size (table durability)" in label[0] and NEW_SHA in label[0] and OLD_SHA in label[0], failures
    # The page check reads the frozen rows the table is built from: two releases inside the small class of the document lane.
    rows = _arcadedb_rows("tpch1", NEW, NEW_SHA, 0.2) + [dict(r, engine_version=OLD, engine_commit=OLD_SHA, engine_backend="jvm")
                                                         for r in _arcadedb_rows("tpch1", NEW, NEW_SHA, 0.2) if r["engine_backend"] == "jvm"]
    payload = _payload({"id": "durability", "entries": [dict(entry(NEW, NEW_SHA, "small"), backend_key="arcadedb_embedded", is_arcadedb=True,
                                                          build="native", scale="doc_insert_small", backend="ArcadeDB (embedded, native build)"),
                                                        dict(entry(OLD, OLD_SHA, "small"), backend_key="arcadedb_embedded", is_arcadedb=True,
                                                          build="jvm", scale="doc_insert_small", backend="ArcadeDB (embedded, JVM build)")]})
    bad, text = _page_check_pair(payload, rows)
    assert bad >= 2 and "COMMIT  in the small size (table docs_oltp)" in text and NEW in text and OLD in text and NEW_SHA in text and OLD_SHA in text, (bad, text)


def test_the_exporter_and_the_page_check_hold_the_class_of_the_durability_rows_to_the_one_table():
    # The lanes the durability table reads are all in SIZE_CLASS, so a frozen row of them always has a class for the gates to group by.
    for lane, _workload, _field, _op, _label in EW.DURABILITY_WRITES:
        classes = {cls for (ln, _sid), cls in SC.SIZE_CLASS.items() if ln == lane}
        assert {"small", "large"} <= classes, (lane, classes)


if __name__ == "__main__":
    test_small_rows_on_one_release_and_large_rows_on_another_are_two_entries_each_with_its_release()
    test_the_table_still_counts_its_operations_once_and_names_the_release_of_its_rows_by_size()
    test_a_row_at_a_size_without_a_class_is_refused()
    test_the_cross_model_transaction_keeps_one_entry_per_catalog_size_and_names_its_class()
    test_every_gate_passes_small_rows_on_the_new_release_and_large_rows_on_the_old_one()
    test_two_releases_inside_one_size_class_are_refused_by_the_exporter_with_the_table_the_class_and_both_values()
    test_two_releases_inside_one_size_class_fail_the_version_consistency_check_and_the_page_check()
    test_the_exporter_and_the_page_check_hold_the_class_of_the_durability_rows_to_the_one_table()
    print("ok")
