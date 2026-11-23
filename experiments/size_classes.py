"""Which size class a frozen row belongs to, and which table it feeds (humemai/mmdbbench#131, #134).

`SIZE_CLASS` (lane, size id -> small, large or extra) was in export_web.py. The gates that hold
ArcadeDB to one engine commit per size class read FROZEN ROWS (arm_identity.pair_problems, called by the exporter and by page_check), and
importing the exporter to ask a lane and a size for their class loads the exporter's whole machinery and refuses without its overlays. So the
table is here, imports only the standard library, and export_web binds it under its old name (`export_web.SIZE_CLASS`): one table, one
classifier, two readers. The words and what they mean are explained at SIZE_CLASS in export_web.py. The table of page tables (`_TABLE_LANE`) stays in
export_web.py, where make_2611_stages, page_check and gen_engines_doc read it by ast; `row_table` takes it as an argument.

`pin_of_size_class` is the one rule for which engine commit a size class reads its pin-keyed overlay directories at (humemai/mmdbbench#146).
"""
from __future__ import annotations

import os

SIZE_CLASSES = ("small", "large", "extra")
# The variable a landing sets when its large rows stay on an earlier release than the run being landed (see pin_of_size_class).
LARGE_PIN_VAR = "BENCH_LARGE_ENGINE_COMMIT"
SIZE_CLASS = {
    ("l3s", "tiny"): "extra",
    ("l3s", "small"): "small",
    ("l3s", "medium"): "large",
    ("l3d", "small"): "small",
    ("l3d", "deep10m"): "large",
    ("e4", "e2"): "small",
    ("l2", "sf1"): "small",
    ("l2", "sf10"): "large",
    ("l2", "sf1full"): "small",
    ("l1tpc", "tpch1"): "small",
    ("l1tpc", "tpch10"): "large",
    ("e2", "e2"): "small",
    ("e2", "e2_500k"): "large",
    ("l4", "ts100"): "small",
    ("l4", "ts1000"): "large",
    ("lifecycle", "lc10k"): "extra",
    ("lifecycle", "lc100k"): "extra",
    ("lifecycle", "lc1m"): "small",
    ("lifecycle", "lc10m"): "large",
    ("restart", "tpch1"): "small",
    ("restart", "tpch10"): "large",
    ("restart", "sf1"): "small",
    ("restart", "sf10"): "large",
    ("restart", "small"): "small",
    ("restart", "deep10m"): "large",
    ("restart", "ts100"): "small",
    ("restart", "ts1000"): "large",
}


def row_size_class(row) -> str | None:
    """The size class (small, large or extra) of a FROZEN row, from its lane and size id, or None when the pair is not in SIZE_CLASS.

    The row form of `export_web.size_class`, over the same SIZE_CLASS (no second classifier). A row it cannot place (the durability rows, the
    client/server decomposition) is None, and the gates hold all of those rows together as one unit, as they always did."""
    return SIZE_CLASS.get((row.get("lane"), str(row.get("scale"))))


def pin_of_size_class(size_class: str) -> str:
    """The engine commit whose overlay directories (`dense_mp5_<pin>`, `dense_mp5_small_<pin>`) a size class reads. One rule (humemai/mmdbbench#146).

    - `BENCH_ENGINE_COMMIT` is the pin of the run being landed, and it is the pin of the small and the extra classes: their rows are the landing's.
    - The large class reads `BENCH_LARGE_ENGINE_COMMIT`, the commit of the release the large rows are on, when the landing names it. Until the full
      benchmark of the large sizes the large rows keep the numbers of the release that measured them (26.11.1) while the small rows move to a new
      release, so the overlay of the large rows sits in a directory named by the OLD pin and is not found by the landing's pin.
    - Unset or blank, the large class reads the landing's pin: a landing whose two classes are on one release needs no variable and nothing moves.

    Returns "" for an unset pin; the resolvers refuse that, as they always did. A class that is not in SIZE_CLASSES raises ValueError."""
    if size_class not in SIZE_CLASSES:
        raise ValueError(f"size class {size_class!r}: one of {', '.join(SIZE_CLASSES)}")
    landing = os.environ.get("BENCH_ENGINE_COMMIT", "").strip()
    if size_class == "large":
        return os.environ.get(LARGE_PIN_VAR, "").strip() or landing
    return landing


def row_table(row, table_lane) -> str:
    """The id of the table a frozen row feeds (`table_lane` is export_web._TABLE_LANE: table id -> lane, workload), else its lane. For the
    sentences of the gates, nothing else."""
    lane, workload = row.get("lane"), row.get("workload")
    for tid, (table_lane_id, table_workload) in table_lane.items():
        if table_lane_id == lane and (table_workload is None or table_workload == workload):
            return tid
    return str(lane)
