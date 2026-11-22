"""Which size class a frozen row belongs to, and which table it feeds (humemai/mmdbbench#131, #134).

`SIZE_CLASS` (lane, size id -> small, large or extra) and `TABLE_LANE` (table id -> lane, workload) were in export_web.py. The gates that hold
ArcadeDB to one engine commit per size class read FROZEN ROWS (arm_identity.pair_problems, called by the exporter and by page_check), and
importing the exporter to ask a lane and a size for their class loads the exporter's whole machinery and refuses without its overlays. So the
tables are here, imports only the standard library, and export_web binds them under their old names (`export_web.SIZE_CLASS`,
`export_web._TABLE_LANE`): one table, one classifier, two readers. The words and what they mean are explained at SIZE_CLASS in export_web.py.
"""
from __future__ import annotations

SIZE_CLASSES = ("small", "large", "extra")
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


TABLE_LANE = {
    "docs_oltp": ("l1tpc", "oltp"), "docs_olap": ("l1tpc", "olap"),
    "l2": ("l2", "oltp"), "l2olap": ("l2", "olap"),
    "l3d": ("l3d", None), "l3s": ("l3s", None), "l4": ("l4", None),
    "e2": ("e2", "hybrid"), "e2atom": ("e2", "atomicity"),
    # The lifecycle table was not here, so a lifecycle cell that exceeded its
    # budget would have left an engine off the table with no note, and the
    # coverage gate had no lane to read its fields from.
    "lifecycle": ("lifecycle", None),
    "restart": ("restart", "restart"),
}


def row_size_class(row) -> str | None:
    """The size class (small, large or extra) of a FROZEN row, from its lane and size id, or None when the pair is not in SIZE_CLASS.

    The row form of `export_web.size_class`, over the same SIZE_CLASS (no second classifier). A row it cannot place (the durability rows, the
    client/server decomposition) is None, and the gates hold all of those rows together as one unit, as they always did."""
    return SIZE_CLASS.get((row.get("lane"), str(row.get("scale"))))


def row_table(row) -> str:
    """The id of the table a frozen row feeds (TABLE_LANE: lane and workload), else its lane. For the sentences of the gates, nothing else."""
    lane, workload = row.get("lane"), row.get("workload")
    for tid, (table_lane, table_workload) in TABLE_LANE.items():
        if table_lane == lane and (table_workload is None or table_workload == workload):
            return tid
    return str(lane)
