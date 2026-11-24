"""The page says which size of a table is the small one and which is the large one (mmdbbench#131).

- one table gives every size id its class (export_web.SIZE_CLASS), and no size with a label is without one;
- a row carries the class as a field and its Size label starts with the word, while the corpus alone stays beside it;
- a table whose large size has no rows says so in a generated sentence: graph analytics, whose large size has no id yet, and any table
  whose large size is simply not there; a size the table withholds is not called "not run";
- a size outside the pair stays on the table, labelled as extra, and the table names it;
- each table names the ArcadeDB version of its rows by size, and the page says once how the two sizes are run and what the small one cannot show;
- a table whose Size column is not a corpus size carries no class, and a size with no class is refused.
Light: dictionaries only, no rows are read. Run with pytest, or as plain functions from this directory.
"""
import copy
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("BENCH_RESULTS_DIR", tempfile.mkdtemp(prefix="small-and-large-"))
os.environ.setdefault("BENCH_ONLY_LANES", "l2,l3d")   # the exporter refuses to load without the E4 overlay unless the lanes are scoped
import export_web as EW  # noqa: E402
import page_check as PC  # noqa: E402

OLD, NEW = "arcadedb 26.11.1 · a3a5d1245", f"arcadedb {EW.FINAL_SMALL_RELEASE} · 0123abcde"


def _row(scale, label, version=OLD, arcadedb=True, **more):
    return {"backend": "ArcadeDB (embedded)" if arcadedb else "Neo4j", "is_arcadedb": arcadedb, "scale": scale, "scale_label": label,
            "version_name": version if arcadedb else "neo4j 2026.08.1", "metrics": {}, **more}


def _table(tid, rows, **more):
    return {"id": tid, "conditions": [], "entries": rows, "withheld_scales": [], **more}


def _classified(*tables):
    payload = {"conditions": ["A condition that was there before."], "tables": [copy.deepcopy(t) for t in tables]}
    EW._classify_sizes(payload)
    return payload


GRAPH = _table("l2", [_row("sf1", "SF1 (10k people, 181k friendships)"), _row("sf10", "SF10 (66k people, 1.9M friendships)"),
                      _row("sf1", "SF1 (10k people, 181k friendships)", arcadedb=False)])
ANALYTICS = _table("l2olap", [_row("sf1full", EW.scale_label("l2", "sf1full"))])
NOT_RUN = "Large size ({}): no rows yet, planned for 2027 on the new host."


def test_every_size_with_a_label_has_a_class():
    assert set(EW.SIZE_CLASS) == set(EW.SCALE_LABELS), sorted(set(EW.SIZE_CLASS) ^ set(EW.SCALE_LABELS))
    assert set(EW.SIZE_CLASS.values()) <= set(EW.SIZE_CLASSES), set(EW.SIZE_CLASS.values())
    # The size ids the lanes define themselves are all there.
    from e2_hybrid import SCALE_PRODUCTS
    from l4_tsbs import SCALE_POINTS
    from ldbc_snb import FULL_NETWORK_COUNTS
    for lane, ids in (("e2", SCALE_PRODUCTS), ("l4", SCALE_POINTS), ("l2", FULL_NETWORK_COUNTS)):
        for sid in ids:
            assert EW.size_class(lane, sid) in ("small", "large"), (lane, sid)
    # Every table that prints a lane's sizes has a small size, and a large one: by id, or planned and named.
    for tid, (lane, _wl) in EW._TABLE_LANE.items():
        only = EW._table_scales(tid)
        ids = [sid for (ln, sid) in EW.SIZE_CLASS if ln == lane and (not only or sid in only)]
        small = [sid for sid in ids if EW.SIZE_CLASS[(lane, sid)] == "small"]
        large = [sid for sid in ids if EW.SIZE_CLASS[(lane, sid)] == "large"]
        assert small, tid
        assert large or all((lane, sid) in EW.PLANNED_LARGE for sid in small), (tid, small)
    # The full SF1 network is graph analytics' SMALL size, and the stage generator's list of long cells does not decide that.
    assert EW.size_class("l2", "sf1full") == "small"
    assert EW.size_label("l3d", "deep10m") == "Large: " + EW.scale_label("l3d", "deep10m")


def test_a_row_says_small_or_large_and_its_label_starts_with_the_word():
    payload = _classified(GRAPH)
    rows = payload["tables"][0]["entries"]
    assert [(e["size_class"], e["scale_label"]) for e in rows] == [
        ("small", "Small: SF1 (10k people, 181k friendships)"), ("large", "Large: SF10 (66k people, 1.9M friendships)"),
        ("small", "Small: SF1 (10k people, 181k friendships)")], rows
    assert rows[0]["size_corpus"] == "SF1 (10k people, 181k friendships)"      # the corpus alone, as the sentences under the table say it
    sizes = payload["tables"][0]["sizes"]
    assert [(s["id"], s["class"], s["rows"]) for s in sizes] == [("sf1", "small", 2), ("sf10", "large", 1)], sizes
    EW._classify_sizes(payload)                                                # a second pass adds no second word
    assert rows[1]["scale_label"] == "Large: SF10 (66k people, 1.9M friendships)", rows[1]
    # Both sizes have rows: nothing is called not run.
    assert not [c for c in payload["tables"][0]["conditions"] if "no rows yet" in c], payload["tables"][0]["conditions"]


def test_graph_analytics_says_its_large_size_is_not_run():
    table = _classified(ANALYTICS)["tables"][0]
    assert table["entries"][0]["scale_label"].startswith("Small: SF1, full network ("), table["entries"][0]
    want = NOT_RUN.format("the full SF10 network")
    assert want in table["conditions"], table["conditions"]
    assert {"id": None, "class": "large", "label": "Large: the full SF10 network", "rows": 0} in table["sizes"], table["sizes"]
    assert any(g["text"] == want and EW.LARGE_RUN_YEAR in g["values"] and EW.LARGE_RUN_HOST in g["values"] for g in EW._GENERATED)   # generated, with the year and the host as its values


def test_a_large_size_without_rows_is_said_and_a_withheld_one_is_not():
    small_only = _table("l3d", [_row("small", "1M vectors")])
    table = _classified(small_only)["tables"][0]
    assert NOT_RUN.format(EW.scale_label("l3d", "deep10m")) in table["conditions"], table["conditions"]
    assert [(s["id"], s["rows"]) for s in table["sizes"]] == [("small", 1), ("deep10m", 0)], table["sizes"]
    withheld = _classified(_table("l3d", [_row("small", "1M vectors")], withheld_scales=["deep10m"]))["tables"][0]
    assert not [c for c in withheld["conditions"] if "no rows yet" in c], withheld["conditions"]   # "Not shown" says it, with its reason


def test_an_extra_size_stays_on_the_table_and_is_named():
    sparse = _table("l3s", [_row(sid, EW.scale_label("l3s", sid)) for sid in ("tiny", "small", "medium")])
    table = _classified(sparse)["tables"][0]
    assert [e["scale_label"] for e in table["entries"]] == ["Extra: 100k vectors", "Small: 1M vectors", "Large: 8.84M vectors"], table["entries"]
    assert "Beside its small and its large size, this table has an extra size: 100k vectors." in table["conditions"], table["conditions"]


def test_each_table_names_the_arcadedb_version_of_its_rows_by_size():
    dense = _table("l3d", [_row("small", "1M vectors", version=NEW), _row("deep10m", "9.99M vectors"),
                           _row("small", "1M vectors", arcadedb=False)])
    payload = _classified(dense)
    want = f"Engine version of the ArcadeDB rows: small size, {EW.FINAL_SMALL_RELEASE}; large size, 26.11.1."
    assert want in payload["tables"][0]["conditions"], payload["tables"][0]["conditions"]
    # The page says it once, first among its own conditions, and keeps what was there.
    first = payload["conditions"][0]
    assert first.startswith("Every table measured on a dataset has a small size and a large size"), first
    assert f"The small sizes are measured on ArcadeDB {EW.FINAL_SMALL_RELEASE}." in first, first
    assert "The large rows are from the ArcadeDB 26.11.1 campaign" in first and first.endswith("planned for 2027."), first
    assert payload["conditions"][1:] == ["A condition that was there before."], payload["conditions"]
    # The same paragraph says what the small sizes cannot show, with no number and no engine in it; "about ten times" is the lanes' own ratio.
    limits = EW.SMALL_SIZE_LIMITS
    assert limits in first and "do not show" in limits and "the large sizes are for that" in limits, first
    assert not any(ch.isdigit() for ch in limits) and not any(name in limits for name in set(EW.DISPLAY_NAMES.values())), limits
    from e2_hybrid import SCALE_PRODUCTS
    from l4_tsbs import SCALE_POINTS
    assert SCALE_PRODUCTS["e2_500k"] == 10 * SCALE_PRODUCTS["e2"] and SCALE_POINTS["ts1000"] == 10 * SCALE_POINTS["ts100"]
    # Before the rerun lands both sizes are the old release, and the paragraph says what the final numbers will be.
    before = _classified(GRAPH)["conditions"][0]
    assert (f"The final numbers, on ArcadeDB {EW.FINAL_SMALL_RELEASE}, will be the small size of every table; "
            "the small rows on this page are from ArcadeDB 26.11.1.") in before, before


def test_a_table_without_corpus_sizes_carries_no_class_and_an_unknown_size_is_refused():
    durability = _table("durability", [_row("doc_insert", "one record inserted (documents)")])
    payload = _classified(durability)
    row = payload["tables"][0]["entries"][0]
    assert row["size_class"] is None and row["scale_label"] == "one record inserted (documents)" and "size_corpus" not in row, row
    assert payload["tables"][0]["sizes"] == [] and payload["conditions"] == ["A condition that was there before."], payload
    try:
        _classified(_table("l3d", [_row("huge", "99M vectors")]))
    except SystemExit as exc:
        assert "SIZE_CLASS" in str(exc), exc
    else:
        raise AssertionError("a size with no class reached the page")
    # The time-series table's `scale` is the printed corpus, so its rows name the lane's size id beside it.
    series = _classified(_table("l4", [_row("2.59M points", "2.59M points", size_id="ts100")]))["tables"][0]
    assert series["entries"][0]["size_class"] == "small" and series["entries"][0]["scale_label"] == "Small: 2.59M points", series["entries"]


def test_every_number_in_the_new_sentences_has_a_source():
    sparse = _table("l3s", [_row(sid, EW.scale_label("l3s", sid)) for sid in ("tiny", "small")])
    payload = _classified(GRAPH, ANALYTICS, sparse, _table("l3d", [_row("small", "1M vectors", version=NEW)]))
    payload["conditions"] = payload["conditions"][:1]              # the paragraph alone: the sentence typed for this test has no registry entry
    payload["condition_provenance"] = {"generated": list(EW._GENERATED)}
    assert sum(len(t["conditions"]) for t in payload["tables"]) >= 7, [t["conditions"] for t in payload["tables"]]
    assert PC._check_conditions(payload, []) == 0                  # the gate the publish runs: generated, and no number without a source


if __name__ == "__main__":
    test_every_size_with_a_label_has_a_class()
    test_a_row_says_small_or_large_and_its_label_starts_with_the_word()
    test_graph_analytics_says_its_large_size_is_not_run()
    test_a_large_size_without_rows_is_said_and_a_withheld_one_is_not()
    test_an_extra_size_stays_on_the_table_and_is_named()
    test_each_table_names_the_arcadedb_version_of_its_rows_by_size()
    test_a_table_without_corpus_sizes_carries_no_class_and_an_unknown_size_is_refused()
    test_every_number_in_the_new_sentences_has_a_source()
    print("ok")
