#!/usr/bin/env python3
"""cost_legs.py: hours of every leg of the pilot of mmdbbench#164, from the order files, the probe time boxes and the stored 26.11.1 rows. READ-ONLY.

Run:  uv run --no-project python -I cost_legs.py [--json-out cost_legs.json]
Inputs: orders/order-<leg>.json (plan.py), picks.json (select_cells.py: median, minimum and maximum wall time of each picked cell in the 26.11.1 landing rows and the
mini's STATUS.txt), humem-ops probes.py (DEFAULT_SECONDS), and the offline qualification plan texts qualify-plan-*.txt (their `Hours (ASSUMED)` line).
Nothing is typed except the ASSUMED constants below.

A unit takes its box (a probe's time box, or a cell's wall time) plus an overhead for the barrier, the thermal gate and the setup. Units of a stage run one after the
other, so a stage takes the sum. Real cells run on two cpus (compare lanes) in `perm` and `alone2` units and at full width in `solo` units: the wall time of a cell on
two cpus is the full-width wall time times f (ASSUMED 1.0, 1.25, 1.5 for low, central, high; a probe is time boxed, so f is 1). Between stages the claims need a
Worker tick each and a rendezvous: STAGE_GAP_S (ASSUMED) per stage.
Low: every wall at its minimum, f 1.0. Central: medians, f 1.25. High: every wall at its maximum, f 1.5, and a thermal wait of GATE_WAIT_S before every compare unit.
"""
import argparse
import importlib.util
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
OVERHEAD_COMPARE_S, OVERHEAD_SOLO_S, STAGE_GAP_S, GATE_WAIT_S = 30.0, 15.0, 300.0, 60.0  # ASSUMED
F = {"low": 1.0, "central": 1.25, "high": 1.5}
LEGS = ("L0", "L1", "L2", "L3", "L4", "H", "L5", "L6")

ap = argparse.ArgumentParser()
ap.add_argument("--probes-py", default=os.path.expanduser("~/repos/tae898/humem-ops/src/controlplane/worker/lanes/probes.py"))
ap.add_argument("--json-out")
a = ap.parse_args()
spec = importlib.util.spec_from_file_location("plan", os.path.join(HERE, "plan.py"))
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)
picks = json.load(open(os.path.join(HERE, "picks.json")))
cell = {f"{c['cell']}.{c['arm']}": c for k in picks["picks"] for c in picks["picks"][k]}
src = open(a.probes_py).read()
box = {k: int(v) for k, v in re.findall(r'"(\w+)":\s*(\d+)', re.search(r"DEFAULT_SECONDS\s*=\s*(\{[^}]*\})", src).group(1))}
assert box["cpu"] == plan.PROBE_BOX_S["cpu"] and box["membw"] == plan.PROBE_BOX_S["membw"] and box["io"] == plan.PROBE_BOX_S["io"], "plan.PROBE_BOX_S differs from probes.py"
out = {}
print(f"{'leg':<4} {'units':>5} {'claims':>6} {'low h':>6} {'central h':>9} {'high h':>7}  title")
for leg in LEGS:
    o = json.load(open(os.path.join(HERE, "orders", f"order-{leg}.json")))
    hours = {}
    for scen, f in F.items():
        secs = 0.0
        stages = []
        for u in o["units"]:
            if u["stage"] not in stages:
                stages.append(u["stage"])
            if u["kind"] == "heat":
                w = float(u["box_s"])
            elif u["target"] in cell:
                c = cell[u["target"]]
                w = {"low": c["wall_min_s"], "central": c["wall_s"], "high": c["wall_max_s"]}[scen] * (1.0 if u["kind"] == "solo" else f)
            else:
                w = float(u["box_s"])
            compare = u["kind"] != "solo"
            secs += w + (OVERHEAD_COMPARE_S + (GATE_WAIT_S if scen == "high" else 0.0) if compare else OVERHEAD_SOLO_S)
        secs += STAGE_GAP_S * len(stages)
        hours[scen] = secs / 3600.0
    out[leg] = {"units": len(o["units"]), "claims": len(o["claims"]), "hours": {k: round(v, 1) for k, v in hours.items()}, "title": o["title"], "claimable": o["claimable"]}
    print(f"{leg:<4} {len(o['units']):>5} {len(o['claims']):>6} {hours['low']:>6.1f} {hours['central']:>9.1f} {hours['high']:>7.1f}  {o['title'][:92]}")
for name in sorted(f for f in os.listdir(HERE) if f.startswith("qualify-plan-") and f.endswith(".txt")):
    t = open(os.path.join(HERE, name)).read()
    m = re.search(r"Hours \(ASSUMED\): 3 rounds ([\d.]+) h, 5 rounds ([\d.]+) h, 10 rounds ([\d.]+) h", t)
    pr = re.search(r"Probes: ([\w,\s]+)\. Rounds", t)
    out[name] = {"probes": pr.group(1), "hours_rung_3_5_10": [float(x) for x in m.groups()], "plan_sha_offline": re.search(r"plan (\w+),", t).group(1)}
    print(f"{name}: probes {pr.group(1)}, assumed hours at rungs 3, 5 and 10: {', '.join(m.groups())} (the plan_sha of this offline copy is not the one of the mini: its layout hash differs)")
print(f"\nASSUMED: overhead {OVERHEAD_COMPARE_S:.0f} s per compare unit and {OVERHEAD_SOLO_S:.0f} s per solo unit, {STAGE_GAP_S:.0f} s per stage for the claims, f {F}, a thermal wait of {GATE_WAIT_S:.0f} s per compare unit in the high case")
tot = {s: sum(out[l]["hours"][s] for l in ("L0", "L1", "L2", "L3", "L4", "H")) for s in F}
print(f"claimable now (L0, L1, L2, L3, L4, H): {tot['low']:.1f} / {tot['central']:.1f} / {tot['high']:.1f} h (low / central / high)")
out["claimable_now_hours"] = {k: round(v, 1) for k, v in tot.items()}
if a.json_out:
    json.dump(out, open(a.json_out + ".new", "w"), indent=1, sort_keys=True)
    os.replace(a.json_out + ".new", a.json_out)
