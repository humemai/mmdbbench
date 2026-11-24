"""The page states which ArcadeDB release its rows are, and what the 26.12.1 rerun does to them (mmdbbench#173).

- page_status.json is the one place: its fields, the shapes of its releases and dates, and a state that agrees with the releases are checked on load;
- the status block reads as the owner worded it, and changing one line of the file (the state, then the small release) changes the page's words;
- what the file says about the rows is held to the rows: a status that claims a release the rows of that size class are not is refused;
- the restate step applies the exporter's statements to a payload without touching a number, writes them again identically on a second run, and
  refreshes only the status block on a payload the exporter wrote;
- the payload the page publishes carries a status block that is the one the file gives.
Light: dictionaries and the committed payload only; no rows are read. Run with pytest, or as plain functions from this directory.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("BENCH_RESULTS_DIR", tempfile.mkdtemp(prefix="page-status-"))
os.environ.setdefault("BENCH_ONLY_LANES", "l2,l3d")   # the exporter refuses to load without the E4 overlay unless the lanes are scoped
import export_web as EW  # noqa: E402
import page_status as PS  # noqa: E402
import restate_web_page as RW  # noqa: E402

DAY = "2026-11-25"
OLD, NEW = "arcadedb 26.11.1 · a3a5d1245", "arcadedb 26.12.1 · 0123abcde"
OLD_LEGEND = "In the cells: `>30m` means the cell ran past its tier's cap and was not retried. A dash is an operation the engine cannot express, never a slow one."
OLD_SIZE = "SF1FULL (10k people, 181k friendships)"
NATIVE_SERVER = "ArcadeDB (server, fp32, native build)"


def _status(**more):
    return {**json.loads(PS.STATUS_FILE.read_text(encoding="utf-8")), **more}


def _entry(backend, key, scale, label, version=OLD, **more):
    return {"backend": backend, "backend_key": key, "is_arcadedb": backend.startswith("ArcadeDB"), "scale": scale, "scale_label": label,
            "workload": "search", "precision": "fp32", "deployment": "server", "version_name": version if backend.startswith("ArcadeDB") else None,
            "metrics": {"warm p50 ms": {"median": 1.5, "min": 1.4, "max": 1.6, "n": 3}}, **more}


def _stale():
    """A payload as the last landing wrote it: no size classes, no status, the labels and sentences the exporter has since corrected."""
    gone = _entry("CrateDB (fp32)", "cratedb_dense", "small", "1M vectors", precision=None, deployment="embedded", outcome="censored",
                  metrics={"warm p50 ms": {"text": ">30m"}})
    failed = _entry(NATIVE_SERVER, "arcadedb_dense_server", "deep10m", "9.99M vectors", precision=None, outcome="failed", metrics={"warm p50 ms": {"text": "lost"}})
    nm = f"{NATIVE_SERVER} was not measured at 9.99M vectors."
    fail = f"{NATIVE_SERVER} at 9.99M vectors: the search cell failed inside its budget and was not retried, so there is no row."
    note = f"The native build was not measured for {NATIVE_SERVER} at 9.99M vectors, so those rows are absent."
    dense = {"id": "l3d", "title": "Dense", "dataset": "DEEP-10M", "withheld_scales": [], "conditions": [OLD_LEGEND, note, fail],
             "entries": [_entry("ArcadeDB (embedded, fp32, JVM build)", "arcadedb_dense_embedded", "small", "1M vectors"),
                         _entry(NATIVE_SERVER, "arcadedb_dense_server", "small", "1M vectors"), gone,
                         _entry("ArcadeDB (embedded, fp32, JVM build)", "arcadedb_dense_embedded", "deep10m", "9.99M vectors"), failed],
             "declared_absences": [{"backend": NATIVE_SERVER, "column": None, "kind": "not measured", "why": nm},
                                   {"backend": NATIVE_SERVER, "column": None, "kind": "failed", "why": fail}]}
    graph = {"id": "l2olap", "title": "Graph OLAP", "dataset": "LDBC-SNB, SF10", "withheld_scales": [],
             "conditions": [f"Neo4j at {OLD_SIZE}: LSQB Q1 (0 of 100 iterations)."],
             "entries": [_entry("ArcadeDB (embedded)", "arcadedb_graph_embedded", "sf1full", OLD_SIZE, precision=None, deployment="embedded")],
             "declared_absences": [{"backend": "Neo4j", "column": None, "kind": "censored", "why": f"Neo4j at {OLD_SIZE}: over budget."}]}
    return {"conditions": ["A condition that was there before."], "tables": [dense, graph],
            "condition_provenance": {"generated": [{"text": OLD_LEGEND, "values": [">30m"]}, {"text": note, "values": [NATIVE_SERVER, "9.99M vectors"]}]}}


def _numbers(payload):
    return [(t["id"], e["backend"], e["scale"], e["metrics"]) for t in payload["tables"] for e in t["entries"]]


def test_the_file_is_checked_on_load():
    assert PS.load()["final_release"] == EW.FINAL_SMALL_RELEASE and PS.load()["large_run_year"] == EW.LARGE_RUN_YEAR
    tmp = Path(tempfile.mkdtemp(prefix="page-status-file-"))
    for name, more, why in (("state", {"rerun_state": "done"}, "rerun_state"), ("release", {"large_release": "v26.11"}, "large_release"),
                            ("date", {"rerun_start": "3 December"}, "rerun_start"), ("agree", {"rerun_state": "landed"}, "disagree"),
                            ("field", {"surprise": "x"}, "unknown field")):
        (tmp / f"{name}.json").write_text(json.dumps(_status(**more)))
        try:
            PS.load(tmp / f"{name}.json")
        except SystemExit as e:
            assert why in str(e), (name, str(e))
        else:
            raise AssertionError(f"{name}: a status that disagrees with itself was accepted")


def test_the_status_reads_as_worded_and_changes_with_one_line():
    scheduled = PS.block(_status(), DAY)
    assert scheduled["lines"][0] == (
        "These rows are ArcadeDB 26.11.1 (the November 2026 instrument). The final numbers are the 26.12.1 rerun at the small size of every lane: "
        "it starts on 2026-12-03, after the release on 2026-12-02, and the rows of the ArcadeDB arms update then. "
        "The large sizes keep their 26.11.1 rows until 2027."), scheduled["lines"][0]
    assert scheduled["stamp"] == "Instrument 2026-11 · ArcadeDB 26.11.1 · generated 2026-11-25", scheduled["stamp"]
    running = PS.block(_status(rerun_state="running"), DAY)["lines"][0]
    assert "it started on 2026-12-03" in running and "update as each lane lands" in running and "starts on" not in running, running
    landed = PS.block(_status(rerun_state="landed", small_release="26.12.1"), DAY)
    assert landed["lines"][0].startswith("The small rows are ArcadeDB 26.12.1 and the large rows are ArcadeDB 26.11.1"), landed["lines"][0]
    assert landed["stamp"] == "Instrument 2026-11 · ArcadeDB 26.12.1 (small) and 26.11.1 (large) · generated 2026-11-25", landed["stamp"]
    for text in scheduled["lines"] + running.split(". ") + landed["lines"]:
        assert "—" not in text and "dev" not in text.lower().split(), text    # no em dash; the sizes are small and large


def test_the_status_is_held_to_the_rows():
    payload = {"tables": [{"entries": [{"is_arcadedb": True, "size_class": "small", "version_name": OLD},
                                       {"is_arcadedb": True, "size_class": "large", "version_name": OLD}]}]}
    assert PS.releases_by_class(payload) == {"small": {"26.11.1"}, "large": {"26.11.1"}}
    payload["status"] = PS.block(_status(), DAY)
    assert PS.problems(payload, _status()) == []
    claimed = _status(rerun_state="landed", small_release="26.12.1")           # the file runs ahead of the landing
    assert any("small rows are ArcadeDB 26.12.1" in p for p in PS.problems(payload, claimed)), PS.problems(payload, claimed)
    payload["tables"][0]["entries"][0]["version_name"] = NEW                    # the rows ran ahead of the file
    assert any("small rows are ArcadeDB 26.12.1" in p for p in PS.problems(payload, _status())), PS.problems(payload, _status())
    payload["tables"][0]["entries"][0]["version_name"] = OLD
    payload["status"]["lines"][0] += " Edited by hand."
    assert any("not the one" in p for p in PS.problems(payload, _status())), PS.problems(payload, _status())
    assert PS.problems({"tables": []}, _status()) == ["the payload has no status block"]


def test_restate_applies_the_exporters_statements_and_touches_no_number():
    before = _stale()
    after, changes = RW.restate(before, DAY)
    assert _numbers(after) == _numbers(before)                                    # no cell moved
    dense, graph = after["tables"]
    cells = {(e["backend"], e["scale"]): e for e in dense["entries"] if e.get("outcome")}
    assert cells[("CrateDB (fp32)", "small")]["precision"] == "fp32" and cells[("CrateDB (fp32)", "small")]["deployment"] == "server"
    assert cells[(NATIVE_SERVER, "deep10m")]["precision"] == "fp32"
    legend = [c for c in dense["conditions"] if c.startswith("In the cells")]
    assert len(legend) == 1 and "A dash means the column does not apply" in legend[0] and "cannot express the operation" in legend[0], legend
    assert not [c for c in dense["conditions"] if "was not measured for" in c], dense["conditions"]     # attempted, so not also "not measured"
    assert [a["kind"] for a in dense["declared_absences"]] == ["failed"], dense["declared_absences"]
    assert graph["dataset"] == "LDBC-SNB, SF1 full network", graph["dataset"]
    assert graph["entries"][0]["scale_label"] == "Small: SF1, full network (3.2M vertices, 13.8M edges)", graph["entries"][0]["scale_label"]
    assert OLD_SIZE not in json.dumps(after) and "SF1, full network (3.2M vertices, 13.8M edges)" in graph["conditions"][0]
    assert "Large size (the full SF10 network): no rows yet, planned for 2027 on the new host." in graph["conditions"], graph["conditions"]
    assert [s["class"] for s in dense["sizes"]] == ["small", "large"] and all(e["size_class"] for t in after["tables"] for e in t["entries"])
    assert PS.problems(after) == [] and after["status"]["stamp"].endswith("generated 2026-11-25")
    assert after["restated"]["changes"] == len(changes) > 0
    texts = {c for c in after["conditions"] + dense["conditions"] + graph["conditions"]}
    assert all(r["text"] in texts for r in after["condition_provenance"]["generated"])       # the registry holds what the page carries
    again, more = RW.restate(after, DAY)
    assert again == after and not more                                            # a second run writes the same payload


def test_a_payload_the_exporter_wrote_gets_only_its_status_refreshed():
    exported, _ = RW.restate(_stale(), DAY)
    exported.pop("restated")                                                      # as if the exporter had written the classes itself
    exported["tables"][0]["conditions"].append("A sentence the exporter wrote.")
    refreshed, changes = RW.restate(exported, "2026-12-03")
    assert not changes and "restated" not in refreshed, changes
    assert refreshed["status"]["stamp"].endswith("generated 2026-12-03")
    assert {**refreshed, "status": exported["status"]} == exported


def test_the_published_payload_carries_the_status_the_file_gives():
    payload = json.loads((HERE / "results" / "web_benchmarks.json").read_text(encoding="utf-8"))
    assert PS.problems(payload) == [], PS.problems(payload)
    # every row of every table with a corpus size says small, large or extra, and Graph OLAP says what its large size is
    graph = next(t for t in payload["tables"] if t["id"] == "l2olap")
    assert [s["class"] for s in graph["sizes"]] == ["small", "large"] and graph["sizes"][1]["rows"] == 0, graph["sizes"]
    assert all(e["scale_label"].startswith("Small: ") for e in graph["entries"]), {e["scale_label"] for e in graph["entries"]}
    assert "SF10" not in graph["dataset"], graph["dataset"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("ok")
