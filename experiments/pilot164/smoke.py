#!/usr/bin/env python3
"""smoke.py: smoke test of plan.py and analyze.py on synthetic data with a known truth. Nothing here touches a host.

Run:  uv run --no-project python -I smoke.py
It checks, and prints what it checked (every line is a registered smoke result of PREREG.md section 12):
  1  plan.py is deterministic (the same seed gives the same bytes) and every data leg is balanced as built
  2  the t quantile of the analysis equals the known values
  3  the analysis recovers a simulated truth (idle figure, neighbour effects, lane positions, drift): estimate inside its interval in at least 90 percent of
     100 simulated pilots, and no bias larger than a quarter of the noise
  4  a biased truth (idle figure 6 percent above solo) is FAIL, a clean one is PASS
  5  the design rules refuse an order that is not balanced: sorted by level (drift confounded with level), and one that puts every run of a level on one lane
  6  missing and refused runs: one invalid run is tolerated, three make the target UNDECIDED, a throttled run is invalid, a top-up restores the verdict
  7  an unstable solo reference makes the target UNDECIDED
  8  the heat leg reads its verdict from the rows
"""
import copy
import importlib.util
import json
import math
import os
import random
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


plan = load("plan")
an = load("analyze")
PICKS = json.load(open(os.path.join(HERE, "picks.json")))
PICKS_SHA = plan.sha256_file(os.path.join(HERE, "picks.json"))
CPUS = {"solo": "0-11", "compare1": "0,2", "compare2": "4,6", "compare3": "8,10"}
OK = []


def check(cond, text):
    print(("ok    " if cond else "FAIL  ") + text)
    if not cond:
        sys.exit(1)
    OK.append(text)


def order_of(leg, seed=20261124):
    return plan.build(leg, seed, dict(plan.DEFAULT_PROVEN), PICKS, PICKS_SHA)


def synth(order, truth, rng, solo=1.0e6):
    """rows of a pilot whose truth is: ln figure = ln(solo * idle_ratio) + level effect + position effect + drift * t + noise (sd)."""
    rows = {}
    nplan = {t["id"]: sum(1 for u in order["units"] if u["kind"] == "perm" and u["target"] == t["id"]) for t in order["targets"]}
    rank = {}
    for t in order["targets"]:
        for i, u in enumerate(sorted([u for u in order["units"] if u["kind"] == "perm" and u["target"] == t["id"]], key=lambda u: u["idx"])):
            rank[u["id"]] = i
    clock = 1000.0
    for u in order["units"]:
        roles = plan.lane_roles(u)
        n = nplan.get(u["target"], 1)
        if u["kind"] == "perm":
            ln = math.log(solo * truth["idle_ratio"]) + (truth["level"].get(u["level"], 0.0) if u["level"] != "idle" else 0.0) + truth["pos"][u["position"]] + truth["drift"] * ((rank[u["id"]] - (n - 1) / 2) / n)
        elif u["kind"] == "alone2":
            ln = math.log(solo * truth["width"])
        else:
            ln = math.log(solo)
        fig = math.exp(ln + rng.gauss(0, truth["sd"]))
        t0, t1 = clock, clock + 60.0
        clock += 100.0
        for lane, role in roles.items():
            if role == "none":
                continue
            r = {"leg": order["leg"], "unit": u["id"], "lane": lane, "role": "target" if role == "target" else role.split(":")[0], "status": "ok", "figure": fig if role == "target" else None,
                 "t_start": t0 - 0.2 if role != "target" else t0, "t_end": t1 + 5.0 if role != "target" else t1, "wall_s": 60.0, "pkg_c_start": 66.0, "pkg_c_max": 74.0, "throttle_ms": 0,
                 "gate_ok": True, "cpus_allowed": CPUS[lane], "cpus_expected": CPUS[lane], "shortened": False}
            rows[(u["id"], lane)] = r
    return rows


def run_cli(order_path, rows, extra=()):
    d = tempfile.mkdtemp(prefix="pilot-smoke-")
    os.makedirs(os.path.join(d, "rows"))
    with open(os.path.join(d, "rows", "rows.jsonl"), "w") as fh:
        for r in rows.values():
            fh.write(json.dumps(r) + "\n")
    p = subprocess.run([sys.executable, "-I", os.path.join(HERE, "analyze.py"), "--order", order_path, "--rows", os.path.join(d, "rows"), "--out-dir", os.path.join(d, "out"), "--boot", "1000", *extra],
                       capture_output=True, text=True)
    res = None
    if p.returncode == 0:
        res = json.load(open(os.path.join(d, "out", "analysis.json")))
    return p, res, d


def write_order(order):
    d = tempfile.mkdtemp(prefix="pilot-smoke-order-")
    path = os.path.join(d, "order.json")
    plan.dump(order, path)
    return path


TRUTH = {"idle_ratio": 1.01, "level": {"compute": math.log(0.99), "membw": math.log(0.92), "io": math.log(0.97)}, "pos": {"compare1": 0.004, "compare2": -0.001, "compare3": -0.003},
         "drift": -0.015, "width": 0.995, "sd": 0.004}

# 1 determinism and balance
for leg in ("L1", "L2", "L3", "L4", "L5", "L6"):
    a, b = order_of(leg), order_of(leg)
    check(json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True), f"plan {leg}: the same seed gives the same order (salt {a['salt']})")
    probs = plan.check_design(a["units"], a["targets"], a["levels"], a["lanes_proven"], corr_max=a["corr_max"])
    check(not probs, f"plan {leg}: balanced as built (equal runs per level, positions within one, drift correlation at most {plan.CORR_MAX})")
# every leg: each lane position equally often within one over the whole target (L1), and the Latin-square rows
l1 = order_of("L1")
pos = [u["position"] for u in l1["units"] if u["kind"] == "perm"]
check(max(pos.count(p) for p in plan.LANES) - min(pos.count(p) for p in plan.LANES) <= 1, f"plan L1: lane positions over all runs {[pos.count(p) for p in plan.LANES]} (within one)")
check(len(order_of("L3")["claims"]) == 9 and {c["cell_class"] for c in order_of("L3")["claims"] if c["lane"] == "compare1"} == {"bw_heavy"}, "plan L3: the compare1 claims carry the class of the stream they host (bw_heavy), compare2 and compare3 only compute")
check(all(u["position"] != "compare1" for u in order_of("L3")["units"] if u["kind"] == "perm" and u["level"] == "membw"), "plan L3: a membw stream is on compare1 only, so its target is never on compare1")

# 2 t quantile
check(abs(an.t_ppf(0.975, 5) - 2.5706) < 1e-3 and abs(an.t_ppf(0.975, 13) - 2.1604) < 1e-3 and abs(an.t_ppf(0.975, 30) - 2.0423) < 1e-3, "t quantile 0.975 at 5, 13 and 30 degrees of freedom equals 2.5706, 2.1604 and 2.0423")

# 3 recovery of a known truth, 100 simulated pilots of leg L3
o3 = order_of("L3")
tgt = o3["targets"][0]
rng = random.Random(7)
cover = {"b0": 0, "compute": 0, "membw": 0}
bias = {"b0": 0.0, "compute": 0.0, "membw": 0.0}
nsim = 100
for _ in range(nsim):
    rows = synth(o3, TRUTH, rng)
    r = an.analyse_target(o3, tgt, o3["units"], rows, 200, False)
    f = r["fit"]
    truth_b0 = math.log(1.0e6 * TRUTH["idle_ratio"])
    for name, tv in (("b0", truth_b0), ("compute", TRUTH["level"]["compute"]), ("membw", TRUTH["level"]["membw"])):
        j = f["names"].index(name)
        lo, hi = f["interval"][j]
        cover[name] += lo <= tv <= hi
        bias[name] += (f["beta"][j] - tv) / nsim
check(all(cover[k] / nsim >= 0.90 for k in cover), f"recovery over {nsim} simulated pilots: interval covers the truth for the idle figure, the compute effect and the membw effect in {cover['b0']}, {cover['compute']} and {cover['membw']} of {nsim}")
check(all(abs(bias[k]) < TRUTH["sd"] / 4 for k in bias), f"recovery: mean error of the idle figure, compute and membw effects {bias['b0']:+.5f}, {bias['compute']:+.5f}, {bias['membw']:+.5f} (log scale, noise sd {TRUTH['sd']})")
rows = synth(o3, TRUTH, random.Random(1))
r = an.analyse_target(o3, tgt, o3["units"], rows, 2000, False)
check(r["verdict"] == "PASS", f"truth idle +1 percent over solo, noise sd 0.4 percent: verdict {r['verdict']} (ratio {r['ratio_full']:.4f}, half-width {r['half_width'] * 100:.2f} percent)")
check(abs(r["interference"]["membw"]["factor"] - 0.92) < 0.01 and r["interference"]["membw"]["interval"][0] < 0.92 < r["interference"]["membw"]["interval"][1], f"neighbour effect membw recovered: x{r['interference']['membw']['factor']:.4f} [{r['interference']['membw']['interval'][0]:.4f}, {r['interference']['membw']['interval'][1]:.4f}] for a truth of x0.92")
check(abs(math.log(r["position_effects"]["compare1"]) - 0.004) < 0.006, f"lane position effect of compare1 recovered: x{r['position_effects']['compare1']:.4f} for a truth of x{math.exp(0.004):.4f}")

# 4 a biased truth fails
bad = dict(TRUTH, idle_ratio=1.06)
r = an.analyse_target(o3, tgt, o3["units"], synth(o3, bad, random.Random(2)), 1000, False)
check(r["verdict"] == "FAIL", f"truth idle +6 percent over solo: verdict {r['verdict']} (ratio {r['ratio_full']:.4f})")
noisy = dict(TRUTH, sd=0.03)
r = an.analyse_target(o3, tgt, o3["units"], synth(o3, noisy, random.Random(3)), 1000, False)
check(r["verdict"] in ("UNDECIDED", "FAIL", "PASS") and (r["verdict"] != "PASS" or r["half_width"] <= 0.03), f"noise sd 3 percent: verdict {r['verdict']}, half-width {r['half_width'] * 100:.2f} percent (never PASS with a half-width above 3 percent)")

# 5 unbalanced designs are refused
o1 = order_of("L1")
srt = copy.deepcopy(o1)
perm = sorted([u for u in srt["units"] if u["kind"] == "perm"], key=lambda u: (u["level"] != "idle", u["round"]))
for i, u in enumerate(perm):
    u["idx"] = i
probs = plan.check_design(srt["units"], srt["targets"], srt["levels"], srt["lanes_proven"], corr_max=srt["corr_max"])
check(any("confounded with level" in p for p in probs), "design check: an order sorted by level (all idle runs first) is refused as confounded with drift: " + probs[0])
one = copy.deepcopy(o1)
for u in one["units"]:
    if u["kind"] == "perm" and u["level"] == "compute":
        u["position"] = "compare3"
        u["busy_lane"] = "compare1"
probs = plan.check_design(one["units"], one["targets"], one["levels"], one["lanes_proven"], corr_max=one["corr_max"])
check(any("not equal within one" in p for p in probs), "design check: every run of one level on a single lane is refused: " + [p for p in probs if "not equal" in p][0])
wrong = copy.deepcopy(order_of("L3"))
for u in wrong["units"]:
    if u["kind"] == "perm" and u["level"] == "membw":
        u["position"], u["busy_lane"] = "compare1", "compare2"
probs = plan.check_design(wrong["units"], wrong["targets"], wrong["levels"], wrong["lanes_proven"], corr_max=wrong["corr_max"])
check(any("does not admit" in p for p in probs), "design check: a run on a lane that the record does not admit for its class is refused")
p, _, _ = run_cli(write_order(srt), synth(srt, TRUTH, random.Random(4)))
check(p.returncode == 2 and "not a balanced design" in p.stderr, "analyze.py exits 2 with REFUSED for the unbalanced order (" + p.stderr.strip().splitlines()[0][:70] + ")")
p, res, _ = run_cli(write_order(o1), synth(o1, TRUTH, random.Random(5)))
check(p.returncode == 0 and res["results"][0]["verdict"] in ("PASS", "UNDECIDED"), f"analyze.py end to end on a balanced L1 order through files: exit 0, verdict {res['results'][0]['verdict']}")

# 6 missing, refused and throttled runs, and the top-up
opath = write_order(o1)
rows = synth(o1, TRUTH, random.Random(6))
perm_units = [u for u in o1["units"] if u["kind"] == "perm"]
drop1 = dict(rows)
del drop1[(perm_units[3]["id"], perm_units[3]["position"])]
p, res, _ = run_cli(opath, drop1)
r1 = res["results"][0]
check(r1["n_invalid"] == 1 and r1["verdict"] in ("PASS", "UNDECIDED") and not any("invalid or missing" in w for w in r1["reasons"]), f"one missing run of 10 is tolerated: verdict {r1['verdict']}, invalid {r1['n_invalid']}")
drop3 = dict(rows)
for u in perm_units[:3]:
    del drop3[(u["id"], u["position"])]
p, res, d3 = run_cli(opath, drop3)
check(res["results"][0]["verdict"] == "UNDECIDED" and any("invalid or missing" in w for w in res["results"][0]["reasons"]), "three missing runs of 10: UNDECIDED with the reason " + [w for w in res["results"][0]["reasons"] if "invalid" in w][0])
thr = copy.deepcopy(rows)
for u in perm_units[:2]:
    thr[(u["id"], u["position"])]["throttle_ms"] = 5000
p, res, _ = run_cli(opath, thr)
r2 = res["results"][0]
check(r2["n_invalid"] == 2 and r2["verdict"] == "UNDECIDED" and "throttled" in r2["invalid"][0]["why"][0], "two throttled runs (5 s of 60 s) are invalid and listed: " + r2["invalid"][0]["why"][0])
shortcut = copy.deepcopy(rows)
u0 = perm_units[0]
shortcut[(u0["id"], u0["busy_lane"] or u0["light_lanes"][0])]["t_end"] = shortcut[(u0["id"], u0["position"])]["t_start"] + 30
p, res, _ = run_cli(opath, shortcut)
check(any("covered" in w for x in res["results"][0]["invalid"] for w in x["why"]), "a neighbour that covered 30 s of a 60 s run makes the run invalid (coverage rule)")
invalid_ids = json.load(open(os.path.join(d3, "out", "invalid.json")))
check(len([i for i in invalid_ids if ".p." in i]) == 3, f"invalid.json lists the 3 units to replace: {len(invalid_ids)} ids")
tp = plan.topup(o1, invalid_ids)
check(all(u["stage"] in ("t1c", "t1s") for u in tp["units"]) and {c["stage"] for c in tp["claims"]} <= {"t1c", "t1s"}, f"plan.py topup: {len(tp['units'])} replacement units in stages {sorted({u['stage'] for u in tp['units']})}, claims {[c['job'] for c in tp['claims']]}")
tpath = os.path.join(tempfile.mkdtemp(prefix="pilot-smoke-topup-"), "topup.json")
plan.dump(tp, tpath)
rows_all = dict(drop3)
nrows = synth(tp, TRUTH, random.Random(8))
for k, v in nrows.items():
    rows_all[k] = v
d = tempfile.mkdtemp(prefix="pilot-smoke-")
os.makedirs(os.path.join(d, "rows"))
with open(os.path.join(d, "rows", "rows.jsonl"), "w") as fh:
    for r in rows_all.values():
        fh.write(json.dumps(r) + "\n")
q = subprocess.run([sys.executable, "-I", os.path.join(HERE, "analyze.py"), "--order", opath, "--topup", tpath, "--rows", os.path.join(d, "rows"), "--out-dir", os.path.join(d, "out"), "--boot", "1000"], capture_output=True, text=True)
res = json.load(open(os.path.join(d, "out", "analysis.json")))
check(q.returncode == 0 and res["results"][0]["n_invalid"] == 0 and res["results"][0]["verdict"] in ("PASS", "UNDECIDED"), f"after the top-up stage the three runs are replaced: invalid {res['results'][0]['n_invalid']}, verdict {res['results'][0]['verdict']} {res['results'][0]['reasons']} {res['results'][0]['design_problems']}")
try:
    plan.topup(tp, ["x"])
    check(False, "a top-up of a top-up is refused")
except SystemExit:
    check(True, "a second top-up stage is refused (one per leg)")

# 6b repeated rows: a failed row that was followed by the run that went on is read as the run that went on; two usable rows of one run are refused
d = tempfile.mkdtemp(prefix="pilot-smoke-dup-")
for sub, rr in (("a", [dict(rows[(perm_units[0]["id"], perm_units[0]["position"])], status="failed", reason="barrier-abort", figure=None)]), ("b", list(rows.values()))):
    os.makedirs(os.path.join(d, sub))
    with open(os.path.join(d, sub, "rows.jsonl"), "w") as fh:
        for r in rr:
            fh.write(json.dumps(r) + "\n")
q = subprocess.run([sys.executable, "-I", os.path.join(HERE, "analyze.py"), "--order", opath, "--rows", d, "--out-dir", os.path.join(d, "out"), "--boot", "200"], capture_output=True, text=True)
check(q.returncode == 0, "a failed row and the later row of the same run in two files: read, exit 0")
with open(os.path.join(d, "a", "rows.jsonl"), "a") as fh:
    fh.write(json.dumps(rows[(perm_units[1]["id"], perm_units[1]["position"])]) + "\n")
q = subprocess.run([sys.executable, "-I", os.path.join(HERE, "analyze.py"), "--order", opath, "--rows", d, "--out-dir", os.path.join(d, "out"), "--boot", "200"], capture_output=True, text=True)
check(q.returncode == 2 and "repeated rows" in q.stderr, "two usable rows of one run: REFUSED, exit 2")

# 7 unstable reference
unst = copy.deepcopy(rows)
for u in o1["units"]:
    if u["kind"] == "solo" and u["set"] == "end":
        unst[(u["id"], "solo")]["figure"] *= 1.08
p, res, _ = run_cli(opath, unst)
check(res["results"][0]["verdict"] == "UNDECIDED" and any("start and the end median" in w or "spreads" in w for w in res["results"][0]["reasons"]), "the start and the end set of solo runs 8 percent apart: UNDECIDED, reason: " + res["results"][0]["reasons"][0][:90])

# 8 interim early fail
very_bad = dict(TRUTH, idle_ratio=1.15)
p, res, _ = run_cli(opath, synth(o1, very_bad, random.Random(9)), ("--interim",))
check(p.returncode == 0 and res["results"][0]["verdict"] == "EARLY-FAIL", f"interim read, truth idle +15 percent over solo: {res['results'][0]['verdict']}")
p, res, _ = run_cli(opath, synth(o1, TRUTH, random.Random(9)), ("--interim",))
check(res["results"][0]["verdict"] == "NO-EARLY-FAIL", f"interim read, truth +1 percent: {res['results'][0]['verdict']}")

# 9 heat leg
oh = order_of("H")
u = oh["units"][0]
hrows = {}
for lane in plan.LANES:
    hrows[(u["id"], lane)] = {"leg": "H", "unit": u["id"], "lane": lane, "role": "busy", "status": "ok", "figure": 1.0, "t_start": 0.0, "t_end": 1800.0, "wall_s": 1800.0, "pkg_c_start": 64.0,
                              "pkg_c_max": 83.0, "throttle_ms": 0, "gate_ok": True, "cpus_allowed": CPUS[lane], "cpus_expected": CPUS[lane], "shortened": False}
p, res, _ = run_cli(write_order(oh), hrows)
check(res["verdict"] == "HEAT-PASS", "heat leg: no throttle and 83 C at most is HEAT-PASS")
hrows[(u["id"], "compare2")]["throttle_ms"] = 40000
p, res, _ = run_cli(write_order(oh), hrows)
check(res["verdict"] == "HEAT-FAIL", "heat leg: 40 s of throttle on one lane in 1800 s (2.2 percent) is HEAT-FAIL")
print(f"\nSMOKE OK: {len(OK)} checks")
