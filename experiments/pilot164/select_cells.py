#!/usr/bin/env python3
"""select_cells.py: candidate cells and the pick for the pilot of mmdbbench#164 (permuted neighbours on compare lanes). READ-ONLY.

Run:  uv run --no-project python -I select_cells.py [--json-out picks.json]
Inputs (every number below comes from these files, none is typed):
  --rows          the frozen landing rows of the 26.11.1 pass (experiments/results/runs_paper.csv of the mmdbbench clone)
  --status        a copy of the mini's ~/STATUS.txt (cell wall times: `[i/n] <cell id> <secs>s (<cpuset>) -> ok`)
  --size-classes  a copy of experiments/size_classes.py of origin/main (the table that says which size is small)
  --lanes-doc     humem-ops docs/lanes.md (the mini's example profile: the memory cap of a compare lane)

RULE, WRITTEN BEFORE THE PICK WAS PRINTED (2026-11-24; the thresholds were fixed after I had seen the row totals of CPU, I/O and peak
memory per cell, but before any wall time, class or pick was computed. A change after the first pilot run is a new pre-registration):

Universe. A candidate is one ArcadeDB arm of one cell of the 26.11.1 landing at the SMALL size class (size_classes.SIZE_CLASS), headline arms
only (no `clientlean`, `clientpgwire` or `imgdefaults` variant). A cell is (lane, backend, workload, scale, durability class); an arm is
the build (jvm or native) of it. Rows count only when engine_version names 26.11.1.

Measured per candidate (median over its repetitions):
  wall    seconds of the cell as the stage logged it, stages qV* (jvm) and qN* (native) of STATUS.txt, rows with outcome ok;
  cores   mean cores used = cpu_usec_sum / 1e6 / wall (cpu time of all containers of the cell over its wall time; the load phase is inside);
  io      (io_read_mib_sum + io_write_mib_sum) / wall in MiB/s;
  cap     mem_cap of the row, in GiB.

Class (calibration classes of humem-ops: compute, bw_heavy, io_heavy; the fourth, cache and latency, has NO calibration probe and is new):
  disk I/O              durability class strict (every commit waits for the disk);
  cache and latency     relaxed, and (lane, workload) is (l2, oltp) or (l3d, search): point reads, traversals and index walks on a working set in RAM;
  memory bandwidth      relaxed, and (lane, workload) is (l1tpc, olap) or (l2, olap): whole-table or whole-graph scans;
  compute               every other relaxed cell (l1tpc oltp, e2 hybrid and atomicity).
Screens, in this order (a candidate that fails one is listed with the first one it failed):
  S1 wall      the median wall is at least 60 s;
  S2 threads   cores is at most 1.5 (a compare lane has 2 cpus; a cell that uses more depends on thread count and stays solo);
  S3 memory    cap is at most the memory_gb of a compare lane of the mini's profile (12 GiB; a larger cap is another measurement, not a smaller lane).
Pick, per class, among the candidates that passed S1 to S3:
  P1  jvm arms before native arms (one engine arm per class where possible: the arm that most candidates of the class share, jvm on a tie);
  P2  embedded before server (no client process);
  P3  shortest median wall first, at most one cell per (lane, workload, scale), up to 3 cells per class; a class with fewer than 2 such groups
      is filled to 2 cells by the next candidates of the pool in the same order (P2, then wall).
A class with no candidate after S1 to S3 has no pick and the script says so; nothing is relaxed here.
"""
import argparse
import csv
import importlib.util
import json
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRATCH = os.path.expanduser("~/build-scratch/pilot-permutation-20261124")
ap = argparse.ArgumentParser()
ap.add_argument("--rows", default=os.path.expanduser("~/repos/humemai/mmdbbench/experiments/results/runs_paper.csv"))
ap.add_argument("--status", default=SCRATCH + "/STATUS-mini-20261123.txt")
ap.add_argument("--size-classes", default=SCRATCH + "/size_classes.py")
ap.add_argument("--lanes-doc", default=os.path.expanduser("~/repos/tae898/humem-ops/docs/lanes.md"))
ap.add_argument("--json-out")
a = ap.parse_args()

MIN_WALL_S, MAX_CORES = 60.0, 1.5
VARIANTS = ("clientlean", "clientpgwire", "imgdefaults")
CLASS_ORDER = ("compute", "memory bandwidth", "disk I/O", "cache and latency")
CELL = re.compile(r"^\s+\[\d+/\d+\] (\S+) ([\d.]+)s \(([^)]*)\) -> (.*)$")
START = re.compile(r"^\[(\S+)\] (q\w+) START")
MAIN_STAGE = re.compile(r"^q([VN])\d")


def load_size_class(path):
    spec = importlib.util.spec_from_file_location("size_classes", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.SIZE_CLASS


def compare_lane_memory_gb(path):
    txt = open(path, encoding="utf-8").read()
    m = re.search(r"\[lanes\.compare1\](.*?)(?=\n\[lanes\.compare2\])", txt, re.S)
    g = re.search(r"^memory_gb\s*=\s*(\d+)", m.group(1), re.M) if m else None
    if not g:
        sys.exit("REFUSED: no memory_gb under [lanes.compare1] in " + path)
    return int(g.group(1))


def read_status(path):
    """{(key, strict, arm): [secs]} for cells of the 2026-11 era with outcome ok in stages qV* (jvm) and qN* (native)."""
    era, stage, out = "old", None, {}
    for ln in open(path, errors="replace"):
        ln = ln.rstrip("\n")
        m = START.match(ln)
        if m:
            stage = m.group(2)
            if stage == "qC01":
                era = "2611"
        m = CELL.match(ln)
        if not m or era != "2611" or stage is None:
            continue
        cid, secs, _, outcome = m.groups()
        ms = MAIN_STAGE.match(stage)
        if not ms or not outcome.strip().startswith("ok"):
            continue
        strict = cid.endswith("_dstrict")
        mr = re.match(r"(.*)_r(\d+)$", cid[:-8] if strict else cid)
        if mr:
            out.setdefault((mr.group(1), strict, "jvm" if ms.group(1) == "V" else "native"), []).append(float(secs))
    return out


def med(v):
    return st.median(v) if v else None


size_class = load_size_class(a.size_classes)
lane_gb = compare_lane_memory_gb(a.lanes_doc)
status = read_status(a.status)

rows = {}
with open(a.rows, newline="") as fh:
    for r in csv.DictReader(fh):
        if not r["backend"].startswith("arcadedb") or "26.11.1" not in r["engine_version"]:
            continue
        if size_class.get((r["lane"], r["scale"])) != "small" or r["rc"] != "0":
            continue
        key = f"{r['lane']}_{r['backend']}_{r['workload']}_{r['scale']}"
        if any(v in key for v in VARIANTS):
            continue
        rows.setdefault((key, r["durability_class"] == "strict", r["engine_backend"]), []).append(r)


def num(r, f):
    try:
        return float(r[f])
    except (KeyError, ValueError):
        return None


def klass(lane, workload, strict):
    if strict:
        return "disk I/O"
    if (lane, workload) in (("l2", "oltp"), ("l3d", "search")):
        return "cache and latency"
    if (lane, workload) in (("l1tpc", "olap"), ("l2", "olap")):
        return "memory bandwidth"
    return "compute"


cands = []
for (key, strict, arm), rr in sorted(rows.items()):
    lane, backend, workload, scale = rr[0]["lane"], rr[0]["backend"], rr[0]["workload"], rr[0]["scale"]
    walls = status.get((key, strict, arm), [])
    cpu = [num(r, "cpu_usec_sum") for r in rr if num(r, "cpu_usec_sum") is not None]
    ior = [(num(r, "io_read_mib_sum") or 0) + (num(r, "io_write_mib_sum") or 0) for r in rr]
    gate = [num(r, "precell_gate_wait_s") for r in rr if num(r, "precell_gate_wait_s") is not None]
    w = med(walls)
    cores = (med(cpu) / 1e6 / w) if (w and cpu) else None
    io = (med(ior) / w) if w else None
    cap = int(re.match(r"(\d+)g", rr[0]["mem_cap"]).group(1))
    topo = "embedded" if "embedded" in backend or backend == "arcadedb_e2" else "server"
    c = dict(cell=f"{key}{'_dstrict' if strict else ''}", arm=f"{arm}-{topo}", build=arm, topo=topo, lane=lane, workload=workload, scale=scale,
             cls=klass(lane, workload, strict), wall_s=w, wall_min_s=min(walls) if walls else None, wall_max_s=max(walls) if walls else None,
             n_wall=len(walls), n_rows=len(rr), cores=cores, io_mibs=io, cap_gib=cap, gate_s=med(gate), why_out=None,
             peak_mib=med([num(r, "peak_mib_sum") for r in rr if num(r, "peak_mib_sum") is not None]))
    if w is None:
        c["why_out"] = "S0 no wall time in STATUS"
    elif w < MIN_WALL_S:
        c["why_out"] = f"S1 wall under {MIN_WALL_S:.0f} s"
    elif cores is None or cores > MAX_CORES:
        c["why_out"] = f"S2 threads (cores over {MAX_CORES})"
    elif cap > lane_gb:
        c["why_out"] = f"S3 memory (cap over {lane_gb} GiB)"
    cands.append(c)

print(f"rows: {a.rows}\nstatus: {a.status}\nsize classes: {a.size_classes}\ncompare-lane memory_gb (docs/lanes.md, mini example profile): {lane_gb}")
print(f"candidates: {len(cands)} arms of small-size cells (26.11.1, headline arms)\n")
hdr = f"{'cell id':<58} {'arm':<16} {'class':<18} {'wall s':>7} {'cores':>6} {'io MiB/s':>8} {'cap':>4}  verdict"
print(hdr)
print("-" * len(hdr))
for c in sorted(cands, key=lambda c: (CLASS_ORDER.index(c["cls"]), c["why_out"] is not None, c["wall_s"] or 0)):
    f = lambda v, p: "-" if v is None else f"{v:.{p}f}"
    print(f"{c['cell']:<58} {c['arm']:<16} {c['cls']:<18} {f(c['wall_s'], 0):>7} {f(c['cores'], 2):>6} {f(c['io_mibs'], 2):>8} {c['cap_gib']:>3}g  {c['why_out'] or 'ok'}")

print("\nFunnel per class (candidates, then left after S1, S2, S3):")
picks = {}
for k in CLASS_ORDER:
    cs = [c for c in cands if c["cls"] == k]
    s1 = [c for c in cs if c["wall_s"] is not None and c["wall_s"] >= MIN_WALL_S]
    s2 = [c for c in s1 if c["cores"] is not None and c["cores"] <= MAX_CORES]
    s3 = [c for c in s2 if c["cap_gib"] <= lane_gb]
    print(f"  {k:<18} {len(cs):>3} {len(s1):>3} {len(s2):>3} {len(s3):>3}")
    if not s3:
        picks[k] = []
        continue
    builds = [c["build"] for c in s3]
    build = "jvm" if builds.count("jvm") >= builds.count("native") else "native"
    pool = sorted((c for c in s3 if c["build"] == build), key=lambda c: (c["topo"] != "embedded", c["wall_s"]))
    chosen, groups = [], set()
    for c in pool:  # pool is already in P2, P3 order
        g = (c["lane"], c["workload"], c["scale"])
        if g not in groups and len(chosen) < 3:
            chosen.append(c)
            groups.add(g)
    for c in pool:  # a class with fewer than 2 groups is filled to 2 cells by the next candidates of the pool
        if len(chosen) < 2 and c not in chosen:
            chosen.append(c)
    picks[k] = chosen[:3]

print("\nNear misses (failed S3 only; informational, the rule is not relaxed): peak memory of the cell against the compare lane")
for c in cands:
    if c["why_out"] and c["why_out"].startswith("S3"):
        print(f"  {c['cell']:<58} {c['arm']:<16} {c['cls']:<18} cap {c['cap_gib']}g, peak {c['peak_mib']:.0f} MiB of {lane_gb * 1024} MiB")

print("\nPICK (rule P1 to P3 of the docstring):")
for k in CLASS_ORDER:
    if not picks[k]:
        print(f"  {k}: NO ELIGIBLE CELL after S1 to S3")
    for c in picks[k]:
        print(f"  {k}: {c['cell']}  arm {c['arm']}  median wall {c['wall_s']:.0f} s [{c['wall_min_s']:.0f}, {c['wall_max_s']:.0f}] over {c['n_wall']} runs  cores {c['cores']:.2f}  cap {c['cap_gib']}g")
if a.json_out:
    json.dump({"lane_memory_gb": lane_gb, "min_wall_s": MIN_WALL_S, "max_cores": MAX_CORES, "picks": picks,
               "candidates": cands, "classes": list(CLASS_ORDER)}, open(a.json_out + ".new", "w"), indent=1)
    os.replace(a.json_out + ".new", a.json_out)
