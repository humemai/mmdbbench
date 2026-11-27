"""Four gaps a rehearsal of the 26.12.1 landing found on real comparator rerun rows (2026-11-27, refs humemai/mmdbbench#114).

Light: temporary directories only, no store, no overlay of the repository. Run with pytest from this directory.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("BENCH_RESULTS_DIR", tempfile.mkdtemp(prefix="landing-gaps-"))
os.environ.setdefault("BENCH_ONLY_LANES", "l1tpc")
import export_web as EW  # noqa: E402
import land_stage as LS  # noqa: E402
import restate_web_page as RS  # noqa: E402
import size_classes as SC  # noqa: E402

NEW, OLD, COMPARATORS = "c0ffee261", "a3a5d1245", "e85469273"


# ---------------------------------------------------------------- the publish libraries are a dependency group, and the landing asks for them first
def test_the_publish_group_installs_what_the_landing_asks_for():
    text = (HERE.parent / "pyproject.toml").read_text(encoding="utf-8")
    group = text.split("publish = [", 1)[1].split("]", 1)[0]
    for name in LS.PUBLISH_PACKAGES:
        assert f'"{name}>=' in group, name


def test_missing_publish_packages_names_only_what_cannot_be_imported():
    assert LS.missing_publish_packages(find=lambda name: object()) == []
    assert LS.missing_publish_packages(find=lambda name: None if name == "matplotlib" else object()) == ["matplotlib"]


# ---------------------------------------------------------------- an overlay size that no source holds keeps its manifest
def _overlay(directory, name, body):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps([{"engine_version": body}]), encoding="utf-8")


def test_a_size_no_source_holds_is_left_as_it_is(tmp_path, capsys):
    results = tmp_path / "results"
    large = results / f"dense_mp5_{OLD}"
    _overlay(large, "mp_arango_b1.json", "3.12.12")
    record = "# file\tsource@pin\tclient\tsha256[:12]\nmp_arango_b1.json\tcomparators@e85469273\t-\t0123456789ab\n"
    (large / "MANIFEST.txt").write_text(record, encoding="utf-8")
    source = tmp_path / "rerun"
    _overlay(source / f"dense_mp5_small_{OLD}_2611", "mp_arango_b1.json", "3.12.14")
    LS.apply_overlay_merge([f"cmp:{OLD}:{source}"], [], NEW, results=results, large_pin=OLD)
    assert (large / "MANIFEST.txt").read_text(encoding="utf-8") == record
    assert f"cmp@{OLD}" in (results / f"dense_mp5_small_{NEW}" / "MANIFEST.txt").read_text(encoding="utf-8")
    assert "left as they are" in capsys.readouterr().out


# ---------------------------------------------------------------- the comparators' pins are for the comparators
def test_a_comparator_pin_never_admits_an_arcadedb_row(monkeypatch):
    monkeypatch.delenv(SC.LARGE_PIN_VAR, raising=False)
    pins = [COMPARATORS, OLD]
    cell = {"lane": "l2", "scale": "sf1", "engine_commit": OLD}
    assert SC.row_at_pin(dict(cell, backend="neo4j_graph"), landing=NEW, comparator_pins=pins)
    assert not SC.row_at_pin(dict(cell, backend="arcadedb_graph_embedded"), landing=NEW, comparator_pins=pins)
    assert SC.row_at_pin(dict(cell, backend="arcadedb_graph_embedded", engine_commit=NEW), landing=NEW, comparator_pins=pins)


def test_a_large_arcadedb_row_is_still_read_at_the_large_pin(monkeypatch):
    monkeypatch.setenv(SC.LARGE_PIN_VAR, OLD)
    row = {"lane": "l3d", "scale": "deep10m", "backend": "arcadedb_dense_server", "engine_commit": OLD}
    assert SC.row_at_pin(row, landing=NEW, comparator_pins=[COMPARATORS])


# ---------------------------------------------------------------- a restated coverage table says what its source tables declare
def test_restate_derives_the_coverage_cells_and_legend_again():
    source = {"id": "l3d", "title": "Dense vector search", "entries": [],
              "declared_absences": [{"backend": "SurrealDB (embedded, fp32)", "kind": "censored", "why": "x"},
                                    {"backend": "SurrealDB (server, fp32)", "kind": "not measured", "why": "y"}]}
    stale = {"id": "multimodel", "title": "Coverage", "columns": ["Dense vector search"],
             "conditions": [RS.LEGEND_OPENING + "one table above (censored, an older legend).", "Another sentence."],
             "entries": [{"backend": engine, "metrics": {"Dense vector search": {"text": "declared, censored"}}} for engine in EW.MULTIMODEL_ENGINES]}
    payload, changes = {"tables": [source, stale]}, []
    RS._coverage_cells(payload, changes)
    surreal = next(e for e in stale["entries"] if e["backend"] == "SurrealDB")
    assert surreal["metrics"]["Dense vector search"]["text"] == "declared, censored; not measured"
    assert "not measured, the engine was not run on that table" in stale["conditions"][0]
    assert stale["conditions"][1] == "Another sentence."
    assert any("SurrealDB x Dense vector search" in c for c in changes)
