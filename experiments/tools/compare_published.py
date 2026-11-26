#!/usr/bin/env python3
"""Put the row of a cell you ran next to the published rows of the same cell (docs/reproduce.md, humemai/mmdbbench#102).

A cell writes one JSON row (`--out`). The published rows are `experiments/results/runs_paper.csv`, three repetitions per
cell, from the benchmark host. This prints, for every timing, throughput and recall field that both have, your value, the
median of the published repetitions, and the ratio. Absolute times differ with the hardware; compare the ratios between
fields, and between engines run on your machine, not the absolute values (see "Compare with the published rows" in the guide).

  cd experiments
  uv run --no-project --with pandas python tools/compare_published.py e2_arcadedb.json --lane e2 --backend arcadedb_e2 --scale e2 --workload hybrid

The published rows of an ArcadeDB arm exist for two builds of one release, `jvm` and `native`; the build is read from your row
(`engine_backend`), or given with `--engine-backend`. Only rows of your durability class (`durability_class`) and with `rc == 0` are used.
"""
import argparse
import json
import os
import re
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "..", "results", "runs_paper.csv")
FIELD = re.compile(r"(_ms|_s|_per_s|_ops_per_s|^recall.*|_recall.*)$")


def load_row(path):
    with open(path, encoding="utf-8") as f:
        text = f.read().strip()
    if text.startswith("RESULT "):
        text = text[len("RESULT "):]
    return json.loads(text)


def published(csv, lane, backend, scale, workload=None, engine_backend=None, durability_class=None, gav=None):
    d = pd.read_csv(csv, low_memory=False)
    d = d[(d["rc"] == 0) & (d["lane"] == lane) & (d["backend"] == backend) & (d["scale"] == scale)]
    if workload:
        d = d[d["workload"] == workload]
    if engine_backend and "engine_backend" in d.columns:
        d = d[d["engine_backend"].fillna("jvm") == engine_backend]
    if durability_class and "durability_class" in d.columns:
        d = d[d["durability_class"] == durability_class]
    # Graph analytics publishes ArcadeDB twice, with and without its analytical view (`gav`). A median over both arms is neither.
    if gav is not None and "gav" in d.columns:
        d = d[d["gav"].astype(str) == str(gav)]
    return d


def compare(row, pub):
    out = []
    for key, mine in row.items():
        if not FIELD.search(key) or isinstance(mine, bool) or not isinstance(mine, (int, float)):
            continue
        if key not in pub.columns:
            continue
        col = pd.to_numeric(pub[key], errors="coerce").dropna()
        if col.empty:
            continue
        med = float(col.median())
        out.append((key, float(mine), med, len(col), (float(mine) / med) if med else float("nan")))
    return out


def digests(row, pub):
    """The answer digests (`res_<query>_digest`) of your row against the published ones: the check that two engines, or two
    runs, returned the same answer. Returns [(field, yours, published set, same)]."""
    out = []
    for key, mine in row.items():
        if key.startswith("res_") and key.endswith("_digest") and key in pub.columns:
            seen = sorted(set(pub[key].dropna().astype(str)))
            out.append((key, str(mine), seen, str(mine) in seen))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("row", help="the JSON file a cell wrote with --out")
    ap.add_argument("--lane", required=True, help="e2, l1tpc, l2, l3d, ...")
    ap.add_argument("--backend", required=True, help="the --backend you ran")
    ap.add_argument("--scale", required=True)
    ap.add_argument("--workload", default=None)
    ap.add_argument("--engine-backend", default=None, help="jvm or native; default: the row's engine_backend")
    ap.add_argument("--csv", default=CSV)
    args = ap.parse_args(argv)
    row = load_row(args.row)
    eb = args.engine_backend or row.get("engine_backend")
    pub = published(args.csv, args.lane, args.backend, args.scale, args.workload, eb, row.get("durability_class"), row.get("gav"))
    if pub.empty:
        print(f"no published rows for lane={args.lane} backend={args.backend} scale={args.scale} workload={args.workload} "
              f"engine_backend={eb}", file=sys.stderr)
        return 1
    print(f"published: {len(pub)} rows, durability_class {row.get('durability_class')}, engine_version {sorted(set(pub['engine_version'].dropna().astype(str)))}, "
          f"host {sorted(set(pub['bench_host'].dropna().astype(str)))}; yours: engine_version {row.get('engine_version')}")
    print(f"{'field':36} {'yours':>12} {'published':>12} {'n':>3} {'ratio':>7}")
    for key, mine, med, n, ratio in compare(row, pub):
        print(f"{key:36} {mine:12.3f} {med:12.3f} {n:3d} {ratio:7.2f}")
    dg = digests(row, pub)
    if dg:
        print("answer digests (same = the published rows hold your digest):")
        for key, mine, seen, same in dg:
            print(f"  {key:44} {'same' if same else 'DIFFERENT'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
