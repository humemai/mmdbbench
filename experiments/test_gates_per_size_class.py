"""The gates hold ArcadeDB to one engine commit per size class, not per table (mmdbbench#134).

Until the large sizes are rerun after February 2027 the small rows of a table are on ArcadeDB 26.12.1 and its large rows on 26.11.1, so one table
holds two releases. Every gate that enforced "one release per table" reads the rule per size class now, and this file holds the two acceptance cases of
the issue against each of them with a small synthetic payload:

- small rows on 26.12.1 and large rows on 26.11.1 pass;
- two releases (or two engine commits) inside one size class are refused, with a sentence that names the size class, the table and both values.

The same two cases hold for every other engine's version since humemai/mmdbbench#192: one version per engine in each size class, and each table
names the versions of its rows by size.

One test per gate: `arm_identity.pair_problems` with the row classifier the exporter calls it with, `page_check._check_build_pair`,
`version_consistency_check`, `export_web._one_version` (already per entry, and so per size), and the page sentences the exporter generates from the
rows (`_classify_sizes`, `_native_server_equiv_note`). The strictness that stays is held here too: a comparator that wears two version strings
inside one size class, rows with no class, and the default `pair_problems` call (no grouping) all fail.
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
os.environ.setdefault("BENCH_RESULTS_DIR", tempfile.mkdtemp(prefix="gates-per-size-"))
os.environ.setdefault("BENCH_ONLY_LANES", "l2,l3d")   # the exporter refuses to load without the E4 overlay unless the lanes are scoped
import arm_identity as AI  # noqa: E402
import engine_pin  # noqa: E402
import export_web as EW  # noqa: E402
import page_check as PC  # noqa: E402
import size_classes as SC  # noqa: E402
import version_consistency_check as VC  # noqa: E402

OLD, OLD_SHA = "26.11.1", "a3a5d1245"
NEW, NEW_SHA = EW.FINAL_SMALL_RELEASE, "0123abcde"


# ------------------------------------------------------------------ frozen rows (what the exporter and the page check hold)
def frow(lane, scale, build, release, sha, workload="oltp", backend="arcadedb_graph_embedded"):
    return {"lane": lane, "scale": scale, "workload": workload, "backend": backend, "engine_backend": build,
            "engine_version": release, "engine_commit": sha}


def both_builds(lane, scale, release, sha, **kw):
    return [frow(lane, scale, b, release, sha, **kw) for b in ("native", "jvm")]


def pair_problems(rows):
    """The call the exporter and the page check make."""
    return AI.pair_problems(rows, group=SC.row_size_class, table_of=lambda r: SC.row_table(r, EW._TABLE_LANE))


# ------------------------------------------------------------------ the row classifier is the exporter's own table
def test_a_frozen_row_is_classified_by_the_one_size_class_table():
    assert EW.SIZE_CLASS is SC.SIZE_CLASS and EW.SIZE_CLASSES is SC.SIZE_CLASSES   # one table, two readers
    assert PC._table_lanes() == EW._TABLE_LANE                                    # the page check reads the exporter's table map by ast
    for (lane, sid), cls in EW.SIZE_CLASS.items():
        assert SC.row_size_class({"lane": lane, "scale": sid}) == cls == EW.size_class(lane, sid), (lane, sid)
    assert SC.row_size_class({"lane": "durability", "scale": "doc_insert"}) is None          # no corpus size: no class, one group
    assert SC.row_size_class({"lane": "l2"}) is None and SC.row_size_class({}) is None
    # The table a sentence names: lane and workload, as the exporter's _TABLE_LANE says; a lane with no table is named by itself.
    assert SC.row_table({"lane": "l2", "workload": "oltp"}, EW._TABLE_LANE) == "l2" and SC.row_table({"lane": "l2", "workload": "olap"}, EW._TABLE_LANE) == "l2olap"
    assert SC.row_table({"lane": "l1tpc", "workload": "olap"}, EW._TABLE_LANE) == "docs_olap" and SC.row_table({"lane": "l3d", "workload": "search"}, EW._TABLE_LANE) == "l3d"
    assert SC.row_table({"lane": "durability", "workload": "doc_insert"}, EW._TABLE_LANE) == "durability"


# ------------------------------------------------------------------ gate 1: arm_identity.pair_problems (the exporter's refusal, the page check's COMMIT line)
def test_pair_gate_accepts_small_on_one_release_and_large_on_another():
    rows = (both_builds("l2", "sf1", NEW, NEW_SHA) + both_builds("l2", "sf10", OLD, OLD_SHA)
            + both_builds("l3d", "small", NEW, NEW_SHA, workload="search") + both_builds("l3d", "deep10m", OLD, OLD_SHA, workload="search"))
    assert pair_problems(rows) == [], pair_problems(rows)
    # Without a grouping the whole freeze is one unit, exactly the old gate: engine_version and engine_commit both disagree.
    assert len(AI.pair_problems(rows)) == 2, AI.pair_problems(rows)


def test_pair_gate_refuses_two_releases_inside_one_size_class_and_names_the_table_the_class_and_both_values():
    # One table, one size class: the native build on the new release and the JVM build on the old one.
    rows = [frow("l2", "sf1", "native", NEW, NEW_SHA), frow("l2", "sf1", "jvm", OLD, OLD_SHA)] + both_builds("l2", "sf10", OLD, OLD_SHA)
    bad = pair_problems(rows)
    assert len(bad) == 2, bad                                       # one sentence for engine_version, one for engine_commit
    for sentence in bad:
        assert "in the small size" in sentence and "table l2" in sentence, sentence
    assert NEW in bad[0] and OLD in bad[0] and "engine_version" in bad[0], bad[0]
    assert NEW_SHA in bad[1] and OLD_SHA in bad[1] and "engine_commit" in bad[1], bad[1]
    # Two engine commits of one release inside one size class.
    commits = both_builds("l2", "sf10", OLD, OLD_SHA) + [frow("l2", "sf10", "jvm", OLD, "fff000999")]
    assert len(pair_problems(commits)) == 1 and "in the large size" in pair_problems(commits)[0]
    # Two tables on two releases inside one size class (as before: one release per size class across the page); both tables are named.
    across = both_builds("l2", "sf1", NEW, NEW_SHA) + both_builds("l3d", "small", OLD, OLD_SHA, workload="search")
    bad = pair_problems(across)
    assert len(bad) == 2 and all("in the small size (table l2, l3d)" in s for s in bad), bad


def test_pair_gate_keeps_what_it_enforced_before():
    # Rows with no class are one group, as before: two releases among them are refused.
    unclassified = both_builds("durability", "doc_insert", NEW, NEW_SHA) + [frow("durability", "doc_insert", "jvm", OLD, OLD_SHA)]
    bad = pair_problems(unclassified)
    assert bad and all("no size class" in s for s in bad), bad
    # A page of one build has nothing to compare, with or without a grouping.
    assert pair_problems([frow("l2", "sf1", "native", NEW, NEW_SHA), frow("l2", "sf10", "native", OLD, OLD_SHA)]) == []
    # The server settings of the two builds are still compared across the whole freeze (arm_identity.server_settings_problems).
    served = [frow("l2", "sf1", b, NEW, NEW_SHA, backend="arcadedb_graph_server") for b in ("native", "jvm")]
    assert pair_problems(served) == AI.pair_problems(served) == AI.server_settings_problems(served)


# ------------------------------------------------------------------ gate 2: page_check._check_build_pair
def _entry(table_scale, size_class, build, release, sha, label="ArcadeDB (embedded)"):
    return {"is_arcadedb": True, "backend_key": "arcadedb_graph_embedded", "backend": AI.build_label(label, build), "build": build,
            "scale": table_scale, "size_class": size_class, "version_name": f"arcadedb {release} · {sha}", "metrics": {}}


def _check_pair(payload, rows):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        bad = PC._check_build_pair(payload, rows)
    return bad, out.getvalue()


def test_page_check_pair_gate_accepts_two_releases_in_two_size_classes_of_one_table():
    payload = {"tables": [{"id": "l2", "entries": [_entry("sf1", "small", b, NEW, NEW_SHA) for b in AI.BUILDS]
                                                   + [_entry("sf10", "large", b, OLD, OLD_SHA) for b in AI.BUILDS]}]}
    rows = both_builds("l2", "sf1", NEW, NEW_SHA) + both_builds("l2", "sf10", OLD, OLD_SHA)
    bad, text = _check_pair(payload, rows)
    assert bad == 0, text


def test_page_check_pair_gate_refuses_two_releases_inside_one_size_class():
    # The rows: the two builds name two releases at the same size (the entries too, so the row gate and the entry gate both speak).
    payload = {"tables": [{"id": "l2", "entries": [_entry("sf1", "small", "native", NEW, NEW_SHA), _entry("sf1", "small", "jvm", OLD, OLD_SHA)]}]}
    rows = [frow("l2", "sf1", "native", NEW, NEW_SHA), frow("l2", "sf1", "jvm", OLD, OLD_SHA)]
    bad, text = _check_pair(payload, rows)
    assert bad == 3, (bad, text)                                    # the entry gate (VERSION) and the two row sentences (COMMIT)
    assert "VERSION l2" in text and "(small)" in text and "COMMIT  in the small size (table l2)" in text, text
    assert NEW in text and OLD in text and NEW_SHA in text and OLD_SHA in text, text
    # Two tables, each internally consistent, on two releases inside the small size class: only the row gate sees it, and it refuses.
    payload = {"tables": [{"id": "l2", "entries": [_entry("sf1", "small", b, NEW, NEW_SHA) for b in AI.BUILDS]},
                          {"id": "l3d", "entries": [_entry("small", "small", b, OLD, OLD_SHA) for b in AI.BUILDS]}]}
    rows = both_builds("l2", "sf1", NEW, NEW_SHA) + both_builds("l3d", "small", OLD, OLD_SHA, workload="search")
    bad, text = _check_pair(payload, rows)
    assert bad == 2 and "table l2, l3d" in text, (bad, text)


# ------------------------------------------------------------------ gate 3: version_consistency_check
def _vc(entries, tid="l3d"):
    payload = {"tables": [{"id": tid, "entries": entries}]}
    with tempfile.TemporaryDirectory() as d:
        path = Path(d, "payload.json")
        path.write_text(json.dumps(payload))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            return VC.check(str(path))


def _ve(version, size_class, backend="ArcadeDB (embedded)", **more):
    return {"backend": backend, "version_name": version, "size_class": size_class, **more}


def test_version_consistency_accepts_one_arcadedb_release_per_size_class_of_a_table():
    failures = _vc([_ve(f"arcadedb {NEW} · {NEW_SHA}", "small"), _ve(f"arcadedb {OLD} · {OLD_SHA}", "large")])
    assert failures == [], failures


def test_version_consistency_refuses_two_arcadedb_releases_inside_one_size_class():
    failures = _vc([_ve(f"arcadedb {NEW} · {NEW_SHA}", "small"), _ve(f"arcadedb {OLD} · {OLD_SHA}", "small"),
                    _ve(f"arcadedb {OLD} · {OLD_SHA}", "large")])
    family = [f for f in failures if f.startswith("arcadedb wears 2 versions")]
    assert len(family) == 1 and "in the small size" in family[0] and "table l3d" in family[0], failures
    assert NEW in family[0] and OLD in family[0], family[0]
    label = [f for f in failures if "publishes 2 different version strings" in f]
    assert len(label) == 1 and "in the small size (table l3d)" in label[0] and NEW_SHA in label[0] and OLD_SHA in label[0], failures
    assert not [f for f in failures if "large size" in f], failures      # the large size has one release and is not blamed
    # Across two tables, inside one size class, as before.
    payload = {"tables": [{"id": "l2", "entries": [_ve(f"arcadedb {NEW}", "small")]}, {"id": "l3d", "entries": [_ve(f"arcadedb {OLD}", "small")]}]}
    with tempfile.TemporaryDirectory() as d:
        path = Path(d, "payload.json")
        path.write_text(json.dumps(payload))
        with contextlib.redirect_stdout(io.StringIO()):
            across = VC.check(str(path))
    assert any("in the small size" in f and "table l2" in f and "table l3d" in f for f in across), across


def test_version_consistency_accepts_one_comparator_version_per_size_class():
    """humemai/mmdbbench#192: the small rows of a moved comparator carry the new version, its large rows the one that measured them."""
    failures = _vc([_ve("neo4j 2026.10.0", "small", backend="Neo4j"), _ve("neo4j 2026.08.1", "large", backend="Neo4j"),
                    _ve("duckdb 2.0.1", "small", backend="DuckDB"), _ve("duckdb 1.5.6", "large", backend="DuckDB"),
                    _ve("duckdb vss 2.0.1", "small", backend="DuckDB VSS (fp32)"), _ve("duckdb vss 1.5.6", "large", backend="DuckDB VSS (fp32)")])
    assert failures == [], failures


def test_version_consistency_refuses_two_comparator_versions_inside_one_size_class():
    for cls, other in (("small", "large"), ("large", "small")):
        # One label on two tables of one size: both the label rule and the family rule name the size.
        failures = _vc([_ve("neo4j 2026.10.0", cls, backend="Neo4j"), _ve("neo4j 2026.08.1", cls, backend="Neo4j"),
                        _ve("neo4j 2026.08.1", other, backend="Neo4j")])
        family = [f for f in failures if f.startswith("neo4j wears 2 versions")]
        assert len(family) == 1 and f"in the {cls} size" in family[0], failures
        label = [f for f in failures if "publishes 2 different version strings" in f]
        assert len(label) == 1 and f"Neo4j in the {cls} size (table l3d)" in label[0], failures
        assert not [f for f in failures if f"{other} size" in f], failures
    # Two labels of one family inside one size: the family rule alone catches it.
    failures = _vc([_ve("duckdb 2.0.1", "small", backend="DuckDB"), _ve("duckdb vss 1.5.6", "small", backend="DuckDB VSS (fp32)")])
    assert len(failures) == 1 and failures[0].startswith("duckdb wears 2 versions in the small size"), failures


def test_version_consistency_keeps_what_it_enforced_before():
    # No class on the rows (an older payload, a table with no corpus size): one group, so two versions still fail, ours and theirs.
    assert _vc([_ve(f"arcadedb {NEW}", None), _ve(f"arcadedb {OLD}", None)])
    assert _vc([_ve("neo4j 2026.08.1", None, backend="Neo4j"), _ve("neo4j 2026.10.0", None, backend="Neo4j")])
    # A comparator wearing an ArcadeDB release number still fails.
    assert [f for f in _vc([_ve(f"arcadedb {OLD}", "small"), _ve(f"neo4j {NEW}", "large", backend="Neo4j")]) if "is an ArcadeDB release number" in f]


# ------------------------------------------------------------------ gate 4: export_web._one_version (an entry is one size; it already was per size)
def test_an_entry_pools_one_release_and_two_sizes_are_two_entries():
    pool = lambda release, sha, scale: [dict(frow("l2", scale, "jvm", release, sha), rep=rep) for rep in (1, 2)]   # noqa: E731
    assert EW._one_version(pool(NEW, NEW_SHA, "sf1"), "l2/sf1")["engine_version"] == NEW
    assert EW._one_version(pool(OLD, OLD_SHA, "sf10"), "l2/sf10")["engine_version"] == OLD
    try:
        EW._one_version(pool(NEW, NEW_SHA, "sf1") + pool(OLD, OLD_SHA, "sf1"), "l2/sf1")
    except SystemExit as exc:
        assert "different engine versions" in str(exc) and NEW in str(exc) and OLD in str(exc), exc
    else:
        raise AssertionError("an entry pooled two releases")


# ------------------------------------------------------------------ gate 5: the exporter wires the row classifier into its refusal
def test_the_exporter_calls_the_pair_gate_per_size_class():
    import inspect
    call = "_AI.pair_problems(rows, group=_SC.row_size_class, table_of=lambda r: _SC.row_table(r, "
    assert call in inspect.getsource(EW.main) and call in inspect.getsource(PC._check_build_pair)


def test_the_page_check_pair_gate_does_not_load_the_exporter():
    """The classifier is a light module: the page check asks it for a row's class without importing export_web (which refuses to load without its overlays)."""
    import subprocess
    code = ("import sys, page_check, size_classes\n"
            "rows = [{'lane': 'l2', 'scale': 'sf1', 'workload': 'oltp', 'backend': 'arcadedb_graph_embedded', 'engine_backend': b,"
            " 'engine_version': '26.12.1', 'engine_commit': 'abc123def'} for b in ('native', 'jvm')]\n"
            "assert page_check._AI.pair_problems(rows, group=size_classes.row_size_class, table_of=lambda r: size_classes.row_table(r, page_check._table_lanes())) == []\n"
            "assert page_check._check_build_pair({'tables': []}, rows) == 0\n"
            "assert 'export_web' not in sys.modules\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("BENCH_")}
    done = subprocess.run([sys.executable, "-c", code], cwd=HERE, env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-800:]


# ------------------------------------------------------------------ the sentences the page prints about the engine version
def _table(tid, lane, small_id, large_id):
    def rows(sid, release, sha):
        return [{"backend": AI.build_label("ArcadeDB (embedded)", b), "is_arcadedb": True, "scale": sid,
                 "scale_label": EW.scale_label(lane, sid), "version_name": f"arcadedb {release} · {sha}", "metrics": {}} for b in AI.BUILDS]
    comparator = {"backend": "Neo4j", "is_arcadedb": False, "scale": small_id, "scale_label": EW.scale_label(lane, small_id),
                  "version_name": "neo4j 2026.08.1", "metrics": {}}
    return {"id": tid, "conditions": [], "entries": rows(small_id, NEW, NEW_SHA) + rows(large_id, OLD, OLD_SHA) + [comparator],
            "withheld_scales": []}


def test_the_page_names_the_release_of_each_size_when_small_is_on_the_new_release_and_large_on_the_old_one():
    payload = {"conditions": ["A condition that was there before."], "tables": [_table("l2", "l2", "sf1", "sf10"), _table("l3d", "l3d", "small", "deep10m")]}
    EW._classify_sizes(payload)
    want = f"Engine version of the ArcadeDB rows: small size, {NEW}; large size, {OLD}."
    for table in payload["tables"]:
        assert want in table["conditions"], table["conditions"]
    first = payload["conditions"][0]
    assert f"The small sizes are measured on ArcadeDB {NEW}." in first and f"The large rows are from the ArcadeDB {OLD} campaign" in first, first
    assert "will be the small size of every table" not in first and first.endswith("planned for 2027."), first
    payload["conditions"] = payload["conditions"][:1]               # the paragraph alone: the sentence typed for this test has no registry entry
    payload["condition_provenance"] = {"generated": list(EW._GENERATED)}
    assert PC._check_conditions(payload, []) == 0                  # generated, and no number without a source


def test_each_table_names_the_other_engines_versions_by_size():
    def row(backend, version, sid, lane="l2"):
        return {"backend": backend, "is_arcadedb": False, "scale": sid, "scale_label": EW.scale_label(lane, sid), "version_name": version,
                "metrics": {}}
    table = _table("l2", "l2", "sf1", "sf10")
    table["entries"] = [e for e in table["entries"] if e["is_arcadedb"]] + [
        row("Neo4j", "neo4j 2026.10.0", "sf1"), row("Neo4j", "neo4j 2026.08.1", "sf10"),
        row("DuckDB", "duckdb 2.0.1 + duckpgq 61f5d082", "sf1"), row("ArangoDB", None, "sf10")]
    payload = {"conditions": [], "tables": [table]}
    EW._classify_sizes(payload)
    want = (f"{EW.VERSIONS_NOTE} small size, DuckDB 2.0.1 + DuckPGQ 61f5d082, Neo4j 2026.10.0; large size, Neo4j 2026.08.1.")
    assert want in table["conditions"], table["conditions"]
    first = payload["conditions"][0]
    assert "each table names the engine versions of its rows by size" in first, first
    payload["conditions"] = []                                      # the table's sentences are the ones under test
    payload["condition_provenance"] = {"generated": list(EW._GENERATED)}
    assert PC._check_conditions(payload, []) == 0                  # generated, and no number without a source
    assert PC._check_raw_backend_keys(payload) == 0                # products are spelled as products


def test_every_engine_family_of_the_version_gate_has_a_product_name_for_the_sentence():
    missing = [f for f in VC.FAMILIES if f not in EW._PRODUCT_NAMES]
    assert not missing, missing


def test_the_coverage_table_names_the_versions_of_its_engines_by_size():
    def row(backend, version, cls, ours=False):
        return {"backend": backend, "is_arcadedb": ours, "size_class": cls, "version_name": version, "metrics": {}}
    sources = [{"id": "l2", "title": "Graph", "entries": [
        row("ArcadeDB (embedded)", f"arcadedb {NEW} · {NEW_SHA}", "small", True), row("ArcadeDB (embedded)", f"arcadedb {OLD} · {OLD_SHA}", "large", True),
        row("ArangoDB", "arangodb 3.12.14", "small"), row("ArangoDB", "arangodb 3.12.12", "large"), row("Neo4j", "neo4j 2026.10.0", "small")]}]
    assert EW.multimodel_sources(sources) == sources
    note = EW._coverage_versions_note(sources + [{"id": "multimodel", "entries": []}])
    assert note == (f"{EW.COVERAGE_VERSIONS_NOTE} small size, ArcadeDB {NEW}, ArangoDB 3.12.14; large size, ArcadeDB {OLD}, ArangoDB 3.12.12.")


def test_the_payload_flags_a_comparator_split_only_inside_one_size_class():
    def r(version, scale):
        return {"lane": "l2", "scale": scale, "backend": "neo4j_graph", "engine_version": version}
    assert EW._comparator_version_split([r("2026.10.0", "sf1"), r("2026.08.1", "sf10")]) == []
    assert EW._comparator_version_split([r("2026.10.0", "sf1"), r("2026.08.1", "sf1")]) == ["neo4j_graph"]


def test_the_pin_report_keeps_an_older_large_row_only_when_the_large_rows_are_on_an_earlier_release(tmp_path, monkeypatch, capsys):
    import comparator_pins_check as CP
    pin = CP.read_pins()["duckdb"]

    def run(rows, large_pin):
        path = tmp_path / "frozen.csv"
        path.write_text("lane,scale,backend,engine_version\n" + "".join(f"l1tpc,{scale},duckdb,{v}\n" for scale, v in rows))
        monkeypatch.setattr(sys, "argv", ["comparator_pins_check.py", "--frozen", str(path)])
        if large_pin:
            monkeypatch.setenv("BENCH_LARGE_ENGINE_COMMIT", large_pin)
        else:
            monkeypatch.delenv("BENCH_LARGE_ENGINE_COMMIT", raising=False)
        code = CP.main()
        return code, capsys.readouterr().out

    code, out = run([("tpch1", pin), ("tpch10", "0.0.1")], OLD_SHA)
    assert code == 0 and "KEPT-LARGE" in out, out
    assert run([("tpch1", pin), ("tpch10", "0.0.1")], None)[0] == 1                       # one release on the page: every row at the pin
    assert run([("tpch1", "0.0.1"), ("tpch10", "0.0.1")], OLD_SHA)[0] == 1                # a small row is held to the pin
    assert run([("tpch1", pin), ("tpch10", "0.0.1"), ("tpch10", "0.0.2")], OLD_SHA)[0] == 1   # two versions inside the large size


def test_the_native_server_sentence_says_every_other_build_of_its_release_not_every_other_build_on_the_page():
    reg = engine_pin._equiv_registry()[OLD]
    tables = [{"id": "l1", "entries": [{"backend_key": "arcadedb_server", "backend": "ArcadeDB (served)"}]}]
    out = EW._native_server_equiv_note(tables, [{"lane": "l1", "backend": "arcadedb_server", "engine_commit": reg["pin"],
                                                 "server_engine_commit_equiv": reg["equivalent"][0]}])
    assert len(out) == 1 and f"every other ArcadeDB {OLD} build on the page" in out[0], out


if __name__ == "__main__":
    test_a_frozen_row_is_classified_by_the_one_size_class_table()
    test_pair_gate_accepts_small_on_one_release_and_large_on_another()
    test_pair_gate_refuses_two_releases_inside_one_size_class_and_names_the_table_the_class_and_both_values()
    test_pair_gate_keeps_what_it_enforced_before()
    test_page_check_pair_gate_accepts_two_releases_in_two_size_classes_of_one_table()
    test_page_check_pair_gate_refuses_two_releases_inside_one_size_class()
    test_version_consistency_accepts_one_arcadedb_release_per_size_class_of_a_table()
    test_version_consistency_refuses_two_arcadedb_releases_inside_one_size_class()
    test_version_consistency_keeps_what_it_enforced_before()
    test_an_entry_pools_one_release_and_two_sizes_are_two_entries()
    test_the_exporter_calls_the_pair_gate_per_size_class()
    test_the_page_check_pair_gate_does_not_load_the_exporter()
    test_the_page_names_the_release_of_each_size_when_small_is_on_the_new_release_and_large_on_the_old_one()
    test_the_native_server_sentence_says_every_other_build_of_its_release_not_every_other_build_on_the_page()
    print("ok")
