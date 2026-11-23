"""The small-size tables print peak memory per million records, with the two limits written under them (humemai/mmdbbench#133, Decision 2).

- the value of a small-size row is its peak memory (MiB) over the records of the table's own ingest count, in GiB per million: worked by hand below;
- a large-size row and an extra-size row get no value, and a row with no count of records (or no peak) is a dash, nothing estimated;
- the unit of the records ends the header, the column is a lower-is-better column that sits right after `peak memory GiB`, and every table that
  prints a peak memory column and an ingest rate has one, over the rows its rate counts (the one table where the two differ is pinned);
- the two limits are generated sentences under a table that prints the column and under no other table, the engines that have a second size
  to read a slope from are named from the payload, and the publish gate that holds every sentence to the registry accepts them.
Light: dictionaries only, no rows are read. The arithmetic and the sentences are in memory_per_million.py, which needs no overlay; the wiring is read
through export_web as the other page tests do. Run with pytest, or as plain functions from this directory.
"""
import copy
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("BENCH_RESULTS_DIR", tempfile.mkdtemp(prefix="memory-per-million-"))
os.environ.setdefault("BENCH_ONLY_LANES", "l2,l3d")   # the exporter refuses to load without the E4 overlay unless the lanes are scoped
import export_web as EW  # noqa: E402
import memory_per_million as MPM  # noqa: E402
import page_check as PC  # noqa: E402

LABEL = "peak memory GiB per million "


def _row(lane, scale, peak_mib, **counts):
    return {"lane": lane, "scale": scale, "peak_owned_mib_sum": str(peak_mib), **{k: str(v) for k, v in counts.items()}}


def _cell(table_id, rows):
    """What the exporter prints for the column of one cell: the aggregate of its rows, or None."""
    return EW._agg(rows, EW._per_million(table_id))


def test_a_small_size_row_gets_gib_per_million_from_its_memory_and_its_record_count():
    # Graph: 300,000 persons and 200,000 edges are 0.5 million records. 3,072 MiB is 3 GiB, so 6 GiB per million; the three
    # repetitions hold 2,048, 3,072 and 4,096 MiB: 4, 6 and 8 GiB per million, median 6.
    graph = [_row("l2", "sf1", mib, n_persons_ingested=300_000, n_edges_ingested=200_000) for mib in (2048, 3072, 4096)]
    assert _cell("l2", graph) == {"median": 6.0, "min": 4.0, "max": 8.0, "n": 3}, _cell("l2", graph)
    # Documents: 900,000 line items and 100,000 parts are one million documents; 2,048 MiB is 2 GiB per million.
    assert _cell("l1tpc", [_row("l1tpc", "tpch1", 2048, n_lineitem=900_000, n_part=100_000)]) == {"median": 2.0, "min": 2.0, "max": 2.0, "n": 1}
    # Vectors: one million, 8,192 MiB is 8 GiB per million. Sparse vectors read the same count.
    assert _cell("l3d", [_row("l3d", "small", 8192, n_docs=1_000_000)])["median"] == 8.0
    assert _cell("l3s", [_row("l3s", "small", 4096, n_docs=2_000_000)])["median"] == 2.0          # 4 GiB over two million
    # Points: 2,000,000 points, 1,024 MiB is half a GiB per million.
    assert _cell("l4", [_row("l4", "ts100", 1024, n_points=2_000_000)])["median"] == 0.5
    # Cross-model: 50,000 products and 150,000 edges are 0.2 million records; 1,024 MiB is 5 GiB per million.
    assert _cell("e2", [_row("e2", "e2", 1024, n_products=50_000, n_edges=150_000)])["median"] == 5.0
    # Graph analytics counts the whole network it loads: 10,000 persons, 190,000 friendships, 3,000,000 message vertices and 13,000,000
    # message edges are 16.2 million records, and 16,588.8 MiB (16.2 GiB) is 1 GiB per million.
    full = _row("l2", "sf1full", 16588.8, n_persons_ingested=10_000, n_edges_ingested=190_000, msg_vertices=3_000_000, msg_edges=13_000_000)
    assert _cell("l2olap", [full])["median"] == 1.0, _cell("l2olap", [full])


def test_a_large_size_row_and_an_extra_size_row_get_no_value():
    counts = dict(n_docs=1_000_000)
    assert _cell("l3d", [_row("l3d", "small", 8192, **counts)]) is not None
    assert _cell("l3d", [_row("l3d", "deep10m", 8192, **counts)]) is None                       # large
    assert _cell("l3s", [_row("l3s", "medium", 8192, **counts)]) is None                        # large
    assert _cell("l3s", [_row("l3s", "tiny", 8192, **counts)]) is None                          # extra
    assert _cell("l3s", [_row("l3s", "small", 8192, **counts)]) is not None                     # the pair's small size, with the same count
    assert _cell("l2", [_row("l2", "sf10", 3072, n_persons_ingested=1, n_edges_ingested=1)]) is None
    assert _cell("l4", [_row("l4", "ts1000", 1024, n_points=1)]) is None
    assert _cell("e2", [_row("e2", "e2_500k", 1024, n_products=1, n_edges=1)]) is None
    assert _cell("l1tpc", [_row("l1tpc", "tpch10", 1024, n_lineitem=1, n_part=1)]) is None
    # a row whose size has no class (the table cannot place it) has none either
    assert _cell("l3d", [_row("l3d", "unknown", 8192, **counts)]) is None
    # the overlay path: the dense table's small size is scaled by the corpus, its large size is not asked
    assert MPM.scale_stat({"median": 8.0, "min": 6.0, "max": 10.0, "n": 3}, 1_000_000) == {"median": 8.0, "min": 6.0, "max": 10.0, "n": 3}
    assert MPM.scale_stat({"median": 8.0, "min": 6.0, "max": 10.0, "n": 3}, 2_000_000) == {"median": 4.0, "min": 3.0, "max": 5.0, "n": 3}
    assert MPM.scale_stat(None, 1_000_000) is None and MPM.scale_stat({"median": 1.0, "min": 1.0, "max": 1.0, "n": 1}, 0) is None


def test_a_row_without_a_record_count_has_a_dash_and_nothing_is_estimated():
    full = dict(n_persons_ingested=10_000, n_edges_ingested=190_000, msg_vertices=3_000_000, msg_edges=13_000_000)
    assert _cell("l2olap", [_row("l2", "sf1full", 16588.8, **full)]) is not None
    # one count missing or blank: the cell is a dash, not a smaller count (the message half is most of the full network)
    for field in full:
        row = _row("l2", "sf1full", 16588.8, **full)
        row[field] = ""
        assert _cell("l2olap", [row]) is None, field
        del row[field]
        assert _cell("l2olap", [row]) is None, field
    assert _cell("l3d", [_row("l3d", "small", 8192)]) is None                                    # no count at all
    assert _cell("l3d", [_row("l3d", "small", 8192, n_docs=0)]) is None                          # a count of nothing
    assert _cell("l3d", [{"lane": "l3d", "scale": "small", "n_docs": "1000000"}]) is None        # no peak memory
    # a cell with one good row and one row without a count keeps the good one: the median is over the rows that have a value
    good, bad = _row("l3d", "small", 8192, n_docs=1_000_000), _row("l3d", "small", 4096)
    assert _cell("l3d", [good, bad]) == {"median": 8.0, "min": 8.0, "max": 8.0, "n": 1}
    # the value falls back to the anonymous peak exactly as `peak memory GiB` does
    anon = {"lane": "l3d", "scale": "small", "peak_anon_mib_sum": "2048", "n_docs": "1000000"}
    assert _cell("l3d", [anon])["median"] == 2.0


def test_the_unit_is_in_the_header_and_the_column_is_lower_is_better_right_after_peak_memory():
    assert {tid: MPM.column_label(tid) for tid in MPM.RECORDS} == {
        "l1tpc": LABEL + "documents", "l2": LABEL + "vertices+edges", "l2olap": LABEL + "vertices+edges", "e2": LABEL + "vertices+edges",
        "l3d": LABEL + "vectors", "l3s": LABEL + "vectors", "l4": LABEL + "points"}
    assert MPM.unit_of(LABEL + "vectors") == "vectors" and MPM.unit_of("peak memory GiB") is None and MPM.unit_of("disk GiB") is None
    label = MPM.column_label("l1tpc")
    row = {"lane": "l1tpc", "scale": "tpch1", "workload": "oltp", "backend": "postgres", "rep": 1, "durability_class": "relaxed"}
    entry = {"backend": EW.display_name("postgres"), "backend_key": "postgres", "scale": "tpch1",
             "metrics": {"ingest s": {"median": 5.0, "n": 3}, "peak memory GiB": {"median": 1.5, "n": 3}, label: {"median": 0.25, "n": 3}}}
    old = list(EW._FROZEN_ROWS)
    try:
        EW._FROZEN_ROWS[:] = [row]
        table = EW._finish_table({"id": "docs_oltp", "columns": ["ingest s", label, "peak memory GiB"], "entries": [entry]})
    finally:
        EW._FROZEN_ROWS[:] = old
    assert table["directions"][label] == "down", table["directions"]
    cols = table["columns"]
    assert cols.index("peak memory GiB") + 1 == cols.index(label), cols


def test_every_table_with_a_peak_memory_and_an_ingest_rate_has_the_column_over_the_rows_its_rate_counts():
    for tid, spec in EW.OCT_TABLE_METRICS.items():
        labels = [lab for _f, lab in spec]
        if "peak memory GiB" not in labels or not any(lab.startswith("ingest") and "/s" in lab for lab in labels):
            continue
        assert tid in MPM.RECORDS, f"{tid} prints a peak memory column and an ingest rate and has no record definition"
        assert MPM.column_label(tid) in labels, (tid, labels)
        assert labels.index(MPM.column_label(tid)) == labels.index("peak memory GiB") + 1, tid
    assert set(MPM.RECORDS) <= set(EW.OCT_TABLE_METRICS), sorted(set(MPM.RECORDS) - set(EW.OCT_TABLE_METRICS))

    def rate_fields(tid):
        fn = next(f for f, lab in EW.OCT_TABLE_METRICS[tid] if lab.startswith("ingest") and lab.endswith("/s") and callable(f))
        name = fn.__name__                                           # rate(n_lineitem+n_part)/build_s
        return tuple(name[len("rate("):name.index(")/")].split("+"))
    # "Records" is what the table's own ingest rate counts ...
    for tid in ("l1tpc", "l2", "e2"):
        assert MPM.RECORDS[tid][1] == rate_fields(tid), tid
    assert ("build_docs_per_s", "ingest+index vectors/s") in EW.OCT_TABLE_METRICS["l3d"] and MPM.RECORDS["l3d"][1] == ("n_docs",)
    assert ("build_docs_per_s", "ingest+index vectors/s") in EW.OCT_TABLE_METRICS["l3s"] and MPM.RECORDS["l3s"][1] == ("n_docs",)
    assert ("ingest_pts_per_s", "ingest points/s") in EW.OCT_TABLE_METRICS["l4"] and MPM.RECORDS["l4"][1] == ("n_points",)
    # ... except graph analytics, whose rate counts persons and friendships while its one size is the full network: the message half is added.
    assert rate_fields("l2olap") == ("n_persons_ingested", "n_edges_ingested")
    assert MPM.RECORDS["l2olap"][1] == rate_fields("l2olap") + ("msg_vertices", "msg_edges")
    # the units are the types the rate columns name
    for tid, word in (("l1tpc", "documents"), ("l2", "vertices+edges"), ("l2olap", "vertices+edges"), ("e2", "vertices+edges"),
                      ("l3d", "vectors"), ("l3s", "vectors"), ("l4", "points")):
        assert any(lab.startswith("ingest") and lab.endswith(f" {word}/s") for _f, lab in EW.OCT_TABLE_METRICS[tid]), (tid, word)


# ---------------------------------------------------------------------------------------------------------------------------------------
# The two limits, under the table that prints the column.

def _entry(engine, scale, label_size, gib, per_million=None):
    metrics = {"peak memory GiB": {"median": gib, "min": gib, "max": gib, "n": 3}}
    if per_million is not None:
        metrics[MPM.column_label("l3s")] = {"median": per_million, "min": per_million, "max": per_million, "n": 3}
    return {"backend": engine, "is_arcadedb": False, "scale": scale, "scale_label": label_size, "version_name": f"{engine} 1.0",
            "metrics": metrics}


def _sparse(with_column=True):
    """Every engine has a peak memory reading at the small size and at a second size: the table offers a slope."""
    rows = []
    for engine in ("Engine A", "Engine B"):
        rows += [_entry(engine, "tiny", "100k vectors", 1.0), _entry(engine, "small", "1M vectors", 3.0, 3.0 if with_column else None),
                 _entry(engine, "medium", "8.84M vectors", 20.0)]
    return {"id": "l3s", "title": "Sparse vector search", "conditions": [], "withheld_scales": [], "entries": rows,
            "columns": ["peak memory GiB"] + ([MPM.column_label("l3s")] if with_column else [])}


def _graph():
    """One engine has no reading at the second size (it failed there): the table offers no slope."""
    rows = [_entry("Engine A", "sf1", "SF1", 2.0, None), _entry("Engine A", "sf10", "SF10", 9.0),
            _entry("Engine B", "sf1", "SF1", 2.5, None)]
    for e in rows:
        e["metrics"][MPM.column_label("l2")] = {"median": 1.0, "min": 1.0, "max": 1.0, "n": 3}
    for e in rows[1:2]:
        del e["metrics"][MPM.column_label("l2")]
    return {"id": "l2", "title": "Graph OLTP", "conditions": [], "withheld_scales": [], "entries": rows,
            "columns": ["peak memory GiB", MPM.column_label("l2")]}


def _page(*tables):
    payload = {"conditions": [], "tables": [copy.deepcopy(t) for t in tables]}
    EW._classify_sizes(payload)
    EW._per_million_notes(payload)
    return payload


def _limits(table):
    unit = MPM.unit_of(MPM.column_of(table))
    got = [c for c in table["conditions"] if "overstates the cost" in c or "slope between two sizes" in c]
    return unit, got


def test_the_two_limits_are_under_a_table_that_has_the_column_and_under_no_other():
    payload = _page(_sparse(), _sparse(with_column=False))
    with_column, without = payload["tables"]
    unit, got = _limits(with_column)
    assert unit == "vectors" and len(got) == 2, got
    first, second = got
    # limit 1: the small-size figure mixes the data's cost with a fixed cost, so dividing by records overstates it, most at the smallest sizes
    assert "fixed cost that does not depend on it (heap and cache defaults, buffers allocated up front)" in first, first
    assert "overstates the cost of one, most at the smallest sizes" in first and "small size only" in first, first
    # limit 2: the slope between two sizes; the column flags heavy engines and does not show behaviour at scale
    assert "The reliable comparison is the slope between two sizes" in second, second
    assert "flags heavy engines" in second and "does not show how an engine behaves at scale" in second, second
    # a table without the column carries neither, and no sentence of the new kind
    assert not [c for c in without["conditions"] if "overstates the cost" in c or "slope between two sizes" in c], without["conditions"]
    # the sentences come after the size sentences, and a second pass adds nothing
    EW._per_million_notes(payload)
    assert _limits(payload["tables"][0])[1] == got


def test_the_engines_that_have_a_second_size_are_read_from_the_payload():
    sparse, graph = _page(_sparse(), _graph())["tables"]
    # every engine of the sparse table has a reading at a second size (the extra size and the large size both count)
    assert MPM.second_size_engines(sparse) == (["Engine A", "Engine B"], []), MPM.second_size_engines(sparse)
    assert "Every engine on this table has one." in _limits(sparse)[1][1], _limits(sparse)[1][1]
    # one engine of the graph table has no reading at a second size: it is named, and the others are not
    assert MPM.second_size_engines(graph) == (["Engine A"], ["Engine B"]), MPM.second_size_engines(graph)
    assert "Every engine on this table has one except Engine B." in _limits(graph)[1][1], _limits(graph)[1][1]
    # a table with one size has none, and the sentence says so
    one = _sparse()
    one["entries"] = [e for e in one["entries"] if e["scale"] == "small"]
    table = _page(one)["tables"][0]
    assert MPM.second_size_engines(table) == ([], ["Engine A", "Engine B"])
    assert "No engine on this table has one." in _limits(table)[1][1], _limits(table)[1][1]
    # an entry that is a censored mark (no number) is not a reading, so an engine with a mark at its second size is named
    marked = _sparse()
    marked["entries"] = [e for e in marked["entries"] if not (e["backend"] == "Engine B" and e["scale"] != "small")]
    marked["entries"].append({"backend": "Engine B", "scale": "medium", "scale_label": "8.84M vectors", "outcome": "OOM",
                              "metrics": {"peak memory GiB": {"text": "OOM"}}})
    table = _page(marked)["tables"][0]
    assert MPM.second_size_engines(table) == (["Engine A"], ["Engine B"]), MPM.second_size_engines(table)
    assert "Every engine on this table has one except Engine B." in _limits(table)[1][1]
    # three or more engines are joined with the serial comma
    many = _graph()
    for name in ("Engine C", "Engine D"):
        many["entries"].append(_entry(name, "sf1", "SF1", 2.0))
    assert "except Engine B, Engine C, and Engine D." in _limits(_page(many)["tables"][0])[1][1]


def test_every_number_in_the_new_sentences_has_a_source():
    payload = _page(_sparse(), _graph())
    payload["condition_provenance"] = {"generated": list(EW._GENERATED)}
    mine = [c for t in payload["tables"] for c in t["conditions"] if "overstates the cost" in c or "slope between two sizes" in c]
    assert len(mine) == 4, mine
    assert not any(ch.isdigit() for c in mine for ch in c), mine             # no number to source: the sentences state the limits only
    assert all(any(g["text"] == c for g in EW._GENERATED) for c in mine)
    for t in payload["tables"]:
        t["conditions"] = [c for c in t["conditions"] if c in mine]       # the gate that runs at every publish: generated, and no number without a source
    payload["conditions"] = []
    assert PC._check_conditions(payload, []) == 0


if __name__ == "__main__":
    test_a_small_size_row_gets_gib_per_million_from_its_memory_and_its_record_count()
    test_a_large_size_row_and_an_extra_size_row_get_no_value()
    test_a_row_without_a_record_count_has_a_dash_and_nothing_is_estimated()
    test_the_unit_is_in_the_header_and_the_column_is_lower_is_better_right_after_peak_memory()
    test_every_table_with_a_peak_memory_and_an_ingest_rate_has_the_column_over_the_rows_its_rate_counts()
    test_the_two_limits_are_under_a_table_that_has_the_column_and_under_no_other()
    test_the_engines_that_have_a_second_size_are_read_from_the_payload()
    test_every_number_in_the_new_sentences_has_a_source()
    print("ok")
