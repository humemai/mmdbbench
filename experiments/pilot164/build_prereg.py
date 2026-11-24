#!/usr/bin/env python3
"""build_prereg.py: writes PREREG.md and QUALIFICATION-PLAN.md from their .in templates, splicing in the output of the scripts, so that no number of the pre-registration is
typed. Refuses an em dash or an en dash in the result (the text may be posted later), a marker left in the text, a design constant of the text that differs from the one in
the code, and a cited figure that is not in the file it is cited from.

Run order (each step reads the files of the steps before it):
  select_cells.py (picks.json, select_cells.out.txt)  ->  build_orders.py  ->  cost_legs.py  ->  smoke.py > smoke.out.txt  ->  smoke_runner.py > smoke_runner.out.txt
  ->  build_recipe.py  ->  build_prereg.py
Run:  uv run --no-project python -I build_prereg.py
Reads the files named above, humem-ops docs and the commit of humem-ops. Writes PREREG.md and QUALIFICATION-PLAN.md (through .new files and a rename).
"""
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOPS = os.path.expanduser("~/repos/tae898/humem-ops")
BUILD = os.path.expanduser("~/build-scratch/pilot-permutation-20261124")


def rd(name):
    return open(os.path.join(HERE, name), encoding="utf-8").read()


def sha(name, base=HERE):
    return hashlib.sha256(open(os.path.join(base, name), "rb").read()).hexdigest()


def fence(text):
    return "```\n" + text.rstrip("\n") + "\n```"


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


plan, an = load("plan"), load("analyze")
sel, cost_txt = rd("select_cells.out.txt"), rd("cost_legs.out.txt")
costj = json.load(open(os.path.join(HERE, "cost_legs.json")))
picks = json.load(open(os.path.join(HERE, "picks.json")))
smoke, smoke_runner = rd("smoke.out.txt"), rd("smoke_runner.out.txt")
assert "SMOKE OK" in smoke and "RUNNER SMOKE OK" in smoke_runner, "a smoke output does not end in OK"
hops_sha = subprocess.run(["git", "-C", HOPS, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
assert sha("study/probes.py") == sha("src/controlplane/worker/lanes/probes.py", HOPS), "study/probes.py is not the probes.py of the humem-ops checkout"
assert "10 calls per hour per area" in open(os.path.join(HOPS, "docs/start-queue.md")).read() and "at most 10 write calls per area per hour" in open(os.path.join(HOPS, "docs/write-tools.md")).read(), "the queue_add rate limit is not 10 calls per hour per area in the humem-ops docs"
qdoc = open(os.path.join(HOPS, "docs/qualification.md"), encoding="utf-8").read()
ldoc = open(os.path.join(HOPS, "docs/lanes.md"), encoding="utf-8").read()
assert "memory_gb = 12" in ldoc

# ---- pieces ------------------------------------------------------------------------------------------------------------------------------------------------
i_table, i_funnel, i_near, i_pick = sel.index("cell id"), sel.index("Funnel per class"), sel.index("Near misses"), sel.index("PICK (rule")
funnel = sel[i_funnel:i_near].rstrip("\n")
pick = sel[i_pick:].rstrip("\n")
candidates = sel[:i_funnel].rstrip("\n") + "\n\n" + sel[i_near:i_pick].rstrip("\n")

legs_rows = ["| Leg | What | Targets and levels | Units | Claims | Hours low / central / high | Claimable |", "|---|---|---|---|---|---|---|"]
n_claimable_claims = 0
for leg in ("L0", "L1", "L2", "L3", "L4", "H", "L5", "L6"):
    o = json.load(open(os.path.join(HERE, "orders", f"order-{leg}.json")))
    c = costj[leg]
    kinds = {}
    for u in o["units"]:
        kinds[u["kind"]] = kinds.get(u["kind"], 0) + 1
    tl = "compare1 membw, compare2 and compare3 cpu, 1800 s" if leg == "H" else "; ".join(f"{t['id'].replace('.', ' ')}: {', '.join(o['levels'])}" for t in o["targets"])
    units = f"{len(o['units'])} ({', '.join(f'{v} {k}' for k, v in sorted(kinds.items()))})"
    legs_rows.append(f"| {leg} | {o['title']} | {tl} | {units} | {len(o['claims'])} | {c['hours']['low']} / {c['hours']['central']} / {c['hours']['high']} | {'yes' if o['claimable'] else 'no: ' + str(o['needs'])} |")
    if o["claimable"]:
        n_claimable_claims += len(o["claims"])

files = ["PREREG.md.in", "QUALIFICATION-PLAN.md.in", "plan.py", "analyze.py", "study/pilot_run.py", "study/probes.py", "study/run_ab.sh", "picks.json", "select_cells.py", "select_cells.out.txt", "build_orders.py", "cost_legs.py",
         "cost_legs.out.txt", "smoke.py", "smoke.out.txt", "smoke_runner.py", "smoke_runner.out.txt", "build_recipe.py", "RUN-RECIPE.md", "qual_throttle_check.py", "build_prereg.py",
         "qualify-plan-io.txt", "qualify-plan-membw.txt", "mini-profile-from-lanes-md.toml"]
lock = ["| Item | Value |", "|---|---|", f"| Prepared (UTC) | {time.strftime('%Y-%m-%d %H:%M', time.gmtime())} |", "| Locked | when I post this file on #164 (the date of the post is the date of the lock) |",
        f"| Seed of the orders | {json.load(open(os.path.join(HERE, 'orders', 'order-L1.json')))['seed']} (the salt of each leg is in its order file and in the table above) |",
        "| Admission assumed by the orders | `lanes_proven` " + ", ".join(f"{k} {v}" for k, v in plan.DEFAULT_PROVEN.items()) + " (the record `mini-2026-11-19-1b62305a8e21`) |", f"| humem-ops commit of the probes and the docs | `{hops_sha}` |"]
for leg in ("L0", "L1", "L2", "L3", "L4", "H", "L5", "L6"):
    lock.append(f"| sha256 of `orders/order-{leg}.json` | `{sha(f'orders/order-{leg}.json')}` |")
lock.append("| Admission path | claims through the Tower's start queue, one per lane and stage; no launcher outside the Worker (section 8) |")
lock.append("| Reading of n | B: 5 runs per target and neighbour level (section 3) |")
hashes = "\n".join(f"{sha(f)}  {f}" for f in files)
qp_sha = None


def qp_text(name, label):
    t = rd(name)
    m = re.search(r"Hours \(ASSUMED\): 3 rounds ([\d.]+) h, 5 rounds ([\d.]+) h, 10 rounds ([\d.]+) h", t)
    runs = re.search(r"Runs per round: (\d+)", t).group(1)
    return f"the offline plan prints, as an assumption, {m.group(1)} hours at 3 rounds, {m.group(2)} at 5 and {m.group(3)} at 10 ({runs} runs per round)."


# ---- QUALIFICATION-PLAN.md ---------------------------------------------------------------------------------------------------------------------------------
qp = rd("QUALIFICATION-PLAN.md.in")
qp = qp.replace("@@QP_IO@@", qp_text("qualify-plan-io.txt", "io")).replace("@@QP_MEMBW@@", qp_text("qualify-plan-membw.txt", "membw")).replace("@@QTC_SHA@@", f"`{sha('qual_throttle_check.py')}`").replace("@@HUMEMOPS_SHA@@", f"`{hops_sha}`")
for tok in set(re.findall(r"\b\d\.\d{3}\b", qp)):
    assert tok in qdoc, f"QUALIFICATION-PLAN cites {tok}, which is not in docs/qualification.md"
for needle in ("8feabb577dd3", "002ff543713b", "1b62305a8e21"):
    assert needle in qdoc and needle in qp
assert "Runs per round: 15" in rd("qualify-plan-io.txt") and "15 runs per round" in qp
assert "1b62305a8e21" in qdoc
# ---- PREREG.md ---------------------------------------------------------------------------------------------------------------------------------------------
open(os.path.join(HERE, "QUALIFICATION-PLAN.md.new"), "w", encoding="utf-8").write(qp)
os.replace(os.path.join(HERE, "QUALIFICATION-PLAN.md.new"), os.path.join(HERE, "QUALIFICATION-PLAN.md"))
lock.append(f"| sha256 of `QUALIFICATION-PLAN.md` | `{sha('QUALIFICATION-PLAN.md')}` |")
text = rd("PREREG.md.in")
repl = {"@@FUNNEL@@": fence(funnel), "@@PICK@@": fence(pick), "@@LEGS@@": "\n".join(legs_rows), "@@SMOKE@@": fence(smoke) + "\n\n" + fence(smoke_runner),
        "@@LOCK@@": "\n".join(lock) + "\n\nSha256 of the files that this registration is built from (written by `build_prereg.py`; the inputs `runs_paper.csv`, the copy of the mini's `STATUS.txt` and `size_classes.py` are named and hashed at the top of `select_cells.out.txt`):\n\n" + fence(hashes),
        "@@COST@@": fence(cost_txt), "@@CANDIDATES@@": fence(candidates)}
for k, v in repl.items():
    assert k in text, "marker missing in the template: " + k
    text = text.replace(k, v)
assert "@@" not in text, "unfilled marker left in the text"
text = text.replace("43 claims for the claimable legs", f"{n_claimable_claims} claims for the claimable legs")
assert f"{n_claimable_claims} claims for the claimable legs" in text
text = text.replace("(5.4 hours assumed at 10 rounds)", "(" + re.search(r"the offline plan prints, as an assumption, [\d.]+ hours at 3 rounds, [\d.]+ at 5 and ([\d.]+) at 10", qp).group(1) + " hours assumed at 10 rounds)")
# design constants of the text against the code
L1 = plan.LEGS["L1"]
needles = [f"at most {plan.CORR_MAX:.2f}", f"correlation above {an.REALISED_CORR_MAX:.2f}", f"the package at most {an.HEAT_MAX_C:g} C", f"covered less than {an.COVER_MIN * 100:g} percent",
           f"above {an.THROTTLE_SHARE * 100:g} percent of its wall time", f"{L1['reps']} runs per target and neighbour level", f"{L1['ref_n']} runs each", f"{an.EARLY_FAIL * 100:g} percent",
           f"{plan.HEAT_SECONDS} s", f"{picks['lane_memory_gb']} GiB", f"at most {picks['max_cores']} cores", f"at least {picks['min_wall_s']:g} s", "within 3 percent"]
gate = re.search(r'PILOT_GATE_C", "(\d+)"', open(os.path.join(HERE, "study", "pilot_run.py")).read()).group(1)
ready = re.search(r'"PILOT_READY_S", "(\d+)"', open(os.path.join(HERE, "study", "pilot_run.py")).read()).group(1)
rdv = re.search(r'"PILOT_RENDEZVOUS_S", "(\d+)"', open(os.path.join(HERE, "study", "pilot_run.py")).read()).group(1)
needles += [f"at most {gate} C", f"within {int(ready) // 60} minutes", f"after {int(rdv) // 60} minutes", f"{int(rdv) // 60} minutes"]
for n in needles:
    assert n in text, "a design constant of the text differs from the code: " + n
assert an.BAND == 0.03 and an.MAX_INVALID_SHARE == 0.10 and plan.SPLIT_SHARE == 0.6
bad = [c for c in ("—", "–") if c in text or c in qp]
if bad:
    sys.exit("REFUSED: em or en dash in the text: " + repr(bad))
open(os.path.join(HERE, "PREREG.md.new"), "w", encoding="utf-8").write(text)
os.replace(os.path.join(HERE, "PREREG.md.new"), os.path.join(HERE, "PREREG.md"))
print("PREREG.md written,", len(text.splitlines()), "lines; QUALIFICATION-PLAN.md written,", len(qp.splitlines()), "lines;", n_claimable_claims, "claimable claims")
