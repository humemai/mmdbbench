"""Labels and captions the page scan of 2026-11-21 found contradicting each other (mmdbbench#124).

- the full-network graph tier has its own size label: people and friendships alone hid the message half;
- the Graph OLAP caption named SF10 for a table whose only size is SF1 (full network);
- a row that stands for a cell with no result takes its precision from the arm and its deployment from the topology, never from the backend name
  (MongoDB printed as embedded, and "fp32" stayed inside the engine name);
- the cell legend names every meaning of a dash.
Light: a temporary run log. Run with pytest, or as plain functions from this directory.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("BENCH_RESULTS_DIR", tempfile.mkdtemp(prefix="page-gap-labels-"))
os.environ.setdefault("BENCH_ONLY_LANES", "l2,l3d")   # the exporter refuses to load without the E4 overlay unless the lanes are scoped
import export_web as EW  # noqa: E402


def test_the_full_network_size_label_names_the_message_half():
    # With the loaded counts present (they are, on the real rows) the l2 branch of scale_label used to answer first and print the people and friendships alone.
    real = EW._l2_size
    EW._l2_size = lambda scale: "10k people, 181k friendships"
    try:
        label = EW.scale_label("l2", "sf1full")
        assert "full network" in label and "vertices" in label and "edges" in label, label
        assert "people" not in label and "SF1FULL" not in label, label
        assert EW.scale_label("l2", "sf1") == "SF1 (10k people, 181k friendships)"   # the projection tiers keep the counts
    finally:
        EW._l2_size = real


def test_the_graph_olap_caption_does_not_say_sf10():
    spec = next(v["l2olap"] for v in vars(EW).values()
                if isinstance(v, dict) and isinstance(v.get("l2olap"), dict) and "dataset" in v["l2olap"])
    assert "SF10" not in spec["dataset"] and "SF1" in spec["dataset"] and "full network" in spec["dataset"], spec["dataset"]


def test_the_legend_names_every_meaning_of_a_dash():
    text = EW._mark_legend({">30m"})[0]
    for part in ("does not apply to that row", "not run at that size", "cannot express the operation"):
        assert part in text, (part, text)
    assert "never stands for a slow one" in text, text


def test_a_cell_with_no_result_takes_precision_and_deployment_from_the_arm():
    tmp = Path(tempfile.mkdtemp(prefix="page-gap-censored-"))
    row = {"lane": "l3d", "scale": "deep10m", "workload": "search", "backend": "mongodb_dense", "rep": 1, "engine_commit": "abc123def",
           "instrument": "2026-11", "rc": -1, "error": "timeout_after_3600s"}
    (tmp / "runs.jsonl").write_text(json.dumps(row) + "\n")
    old = {k: os.environ.get(k) for k in ("BENCH_ENGINE_COMMIT", "BENCH_COMPARATOR_PIN")}
    os.environ["BENCH_ENGINE_COMMIT"] = "abc123def"
    os.environ.pop("BENCH_COMPARATOR_PIN", None)
    real = EW.RESULTS
    EW.RESULTS, EW._CENSORED_CACHE = tmp, None
    try:
        table = {"id": "l3d", "columns": ["cold p50 ms"],
                 "entries": [{"backend": "pgvector (fp32)", "backend_key": "pgvector_dense", "scale": "deep10m",
                              "metrics": {"cold p50 ms": {"median": 1.0, "n": 3}}}]}
        rows, _marks = EW._censored_entries(table)
        mine = [e for e in rows if e.get("backend_key") == "mongodb_dense"]
        assert mine, rows
        assert mine[0]["deployment"] == "server", mine[0]["deployment"]          # the name rule said embedded
        assert mine[0]["precision"] == "fp32", mine[0]["precision"]              # None left "fp32" inside the engine name
    finally:
        EW.RESULTS, EW._CENSORED_CACHE = real, None
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


if __name__ == "__main__":
    test_the_full_network_size_label_names_the_message_half()
    test_the_graph_olap_caption_does_not_say_sf10()
    test_the_legend_names_every_meaning_of_a_dash()
    test_a_cell_with_no_result_takes_precision_and_deployment_from_the_arm()
    print("ok")
