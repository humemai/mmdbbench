#!/usr/bin/env python3
"""Time and memory of the small cells, from the landed rows, for docs/reproduce.md (humemai/mmdbbench#121, #102).

Reads `experiments/results/runs_paper.csv` (three repetitions per cell, the relaxed durability class, `rc == 0`) and prints one markdown table per run: for each
(lane, scale, backend) the median cell time and the peak memory over the repetitions.

  cell time   build_s + oltp_total_s (the definition of #121) plus the `<query>_elapsed_s` of the five l1tpc analytics queries; still a
              lower bound, because the timed reads of the other lanes are not in it
  peak GiB    the runner's `peak_mib_sum`: the peak of the server and of the client container added up, or of the one process when the engine runs
              inside the client

Nothing here is typed by hand: the guide pastes this output, and `--check` exits 1 when a row of the guide's table differs
from what the CSV gives. Run it with `uv run --no-project --with pandas python tools/small_cell_cost.py` from `experiments/`.
"""
import argparse
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "..", "results", "runs_paper.csv")

# The cells the guide documents: (lane, scale, backend, workload or None, engine build or None, what the cell is).
# The ArcadeDB arms have rows for two builds of one release; the guide's commands install the JVM wheel, so those rows are the JVM ones.
CELLS = (
    ("e2", "e2", "arcadedb_e2", "hybrid", "jvm", "ArcadeDB embedded"),
    ("e2", "e2", "duckdb_e2", "hybrid", None, "DuckDB"),
    ("l1tpc", "tpch1", "arcadedb_embedded", "olap", "jvm", "ArcadeDB embedded"),
    ("l1tpc", "tpch1", "sqlite", "oltp", None, "SQLite"),
    ("l3d", "small", "arcadedb_dense_embedded", None, "jvm", "ArcadeDB embedded"),
    ("l3d", "small", "sqlite_vec_dense", None, None, "SQLite with sqlite-vec"),
    ("l2", "sf1", "arcadedb_graph_embedded", "oltp", "jvm", "ArcadeDB embedded"),
    ("l2", "sf1full", "arcadedb_graph_embedded", "olap", "jvm", "ArcadeDB embedded"),
)


def peak_gib(row):
    """The cell's peak as the runner sums it (`peak_mib_sum`): server plus client for a served cell. An engine inside the client's process is one
    process and counts once; adding the client peak to the phase peaks counted it twice (humemai/mmdbbench#198)."""
    total = row.get("peak_mib_sum")
    return float(total) / 1024.0 if pd.notna(total) else float("nan")


def load(path=CSV):
    d = pd.read_csv(path, low_memory=False)
    d = d[(d["rc"] == 0) & (d["durability_class"] == "relaxed")].copy()   # the guide runs the default class
    elapsed = [c for c in ("q1_elapsed_s", "q6_elapsed_s", "top_parts_elapsed_s", "ship_mode_elapsed_s", "by_month_elapsed_s") if c in d.columns]
    d["cell_s"] = d["build_s"].fillna(0) + d["oltp_total_s"].fillna(0) + d[elapsed].fillna(0).sum(axis=1)
    d["peak_gib"] = d.apply(peak_gib, axis=1)
    return d


def table(d=None):
    d = load() if d is None else d
    rows = []
    for lane, scale, backend, workload, build, what in CELLS:
        s = d[(d["lane"] == lane) & (d["scale"] == scale) & (d["backend"] == backend)]
        if workload:
            s = s[s["workload"] == workload]
        if build:
            s = s[s["engine_backend"].fillna("jvm") == build]
        if "gav" in s.columns:                       # graph analytics has an arm without the analytical view; the guide runs the default
            s = s[s["gav"].astype(str) != "False"]
        if s.empty:
            rows.append((lane, scale, backend, workload or "", what, 0, float("nan"), float("nan"), float("nan"), ""))
            continue
        cap = ",".join(sorted(set(str(x) for x in s["mem_cap"].dropna())))
        rows.append((lane, scale, backend, workload or "", what, len(s), s["cell_s"].median(), s["peak_gib"].median(),
                     s["peak_gib"].max(), cap))
    return rows


def render(rows):
    out = ["| lane | scale | backend id | workload | rows | cell time, median (s) | peak memory, median / max (GiB) | cap in the rows |",
           "|---|---|---|---|---|---|---|---|"]
    for lane, scale, backend, workload, what, n, cell_s, med, mx, cap in rows:
        out.append(f"| `{lane}` | `{scale}` | `{backend}` | {workload or 'all'} | {n} | {cell_s:.0f} | {med:.1f} / {mx:.1f} | {cap or 'none'} |")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--csv", default=CSV)
    ap.add_argument("--check", metavar="MARKDOWN", help="exit 1 unless this file contains the table this script prints")
    args = ap.parse_args(argv)
    text = render(table(load(args.csv)))
    if args.check:
        with open(args.check, encoding="utf-8") as f:
            body = f.read()
        if text not in body:
            print("the table in", args.check, "differs from the rows; paste this one:\n" + text)
            return 1
        print("ok:", args.check, "holds the table of", args.csv)
        return 0
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
