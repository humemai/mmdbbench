#!/usr/bin/env python3
"""smoke_runner.py: smallest-scale smoke of study/pilot_run.py on THIS machine (the laptop), before it goes to the mini. Never run on the mini.

Run:  uv run --no-project python -I smoke_runner.py
It builds the smoke leg L0 with 2-second boxes, copies the study template, fakes the two sysfs readings (package temperature, throttle counters) with the
test hooks of the runner, and starts the three compare claims of stage s2 at once (cores 12, 13, 14 of the laptop, nice 19, a few minutes of 1 percent to
100 percent of three LP-E cores), then the solo claim of stage s1 (cores 12 to 15). It checks: the barrier (the three lanes of a unit start within 0.5 s), the
roles (one target with a figure, a busy stream or a light neighbour on the others), the row fields the analysis needs, the resume (a second start of a claim
writes nothing new), the refusal of a wrong lane, class or OUT, the rendezvous failure (exit 4) when a lane never starts, and that analyze.py reads the rows.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("plan", os.path.join(HERE, "plan.py"))
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)
N = 0


def check(cond, text):
    global N
    print(("ok    " if cond else "FAIL  ") + text)
    if not cond:
        sys.exit(1)
    N += 1


plan.LEGS["L0"].update({"seconds": 2, "mid_n": 1, "end_n": 1})  # the smoke here uses the stages s3 to s5 too; the registered L0 has only s1 and s2
picks = json.load(open(os.path.join(HERE, "picks.json")))
order = plan.build("L0", 20261124, dict(plan.DEFAULT_PROVEN), picks, plan.sha256_file(os.path.join(HERE, "picks.json")))
study = tempfile.mkdtemp(prefix="pilot-study-", dir=os.path.expanduser("~/build-scratch")) if os.path.isdir(os.path.expanduser("~/build-scratch")) else tempfile.mkdtemp(prefix="pilot-study-")
for f in ("pilot_run.py", "probes.py", "run_ab.sh"):
    shutil.copy(os.path.join(HERE, "study", f), study)
plan.dump(order, os.path.join(study, "order.json"))
fake = tempfile.mkdtemp(prefix="pilot-fake-sys-")
for c in range(12, 16):
    d = os.path.join(fake, f"cpu{c}", "thermal_throttle")
    os.makedirs(d)
    for n in ("core_throttle_total_time_ms", "package_throttle_total_time_ms"):
        open(os.path.join(d, n), "w").write("0\n")
open(os.path.join(fake, "temp"), "w").write("52000\n")
CPUS = {"compare1": "12", "compare2": "13", "compare3": "14", "solo": "12-15"}


def start(out, lane, cls="compute", extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PILOT_")}
    env.update({"OUT": out, "HUMEM_HOST_LANE": lane, "HUMEM_HOST_CPUS": CPUS[lane], "PILOT_TEMP_FILE": os.path.join(fake, "temp"), "PILOT_THROTTLE_ROOT": fake, "PILOT_GATE_C": "500"})
    if cls:
        env["HUMEM_HOST_CELL_CLASS"] = cls
    env.update(extra or {})
    return subprocess.Popen([sys.executable, "-I", os.path.join(study, "pilot_run.py")], cwd=study, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, preexec_fn=lambda: os.nice(19))


def rows_of(out):
    p = os.path.join(study, out, "rows.jsonl")
    return [json.loads(x) for x in open(p)] if os.path.exists(p) else []


# stage s2: three lanes at once
procs = {lane: start(f"s2-c{lane[-1]}", lane) for lane in ("compare1", "compare2", "compare3")}
res = {lane: p.communicate(timeout=300) for lane, p in procs.items()}
check(all(p.returncode == 0 for p in procs.values()), "three compare claims of stage s2 ran to the end, exit 0 (" + ", ".join(f"{k} {v.returncode}" for k, v in procs.items()) + ")")
for lane in procs:
    if procs[lane].returncode:
        print(res[lane][1][-800:], res[lane][0][-800:])
s2 = [u for u in order["units"] if u["stage"] == "s2"]
allrows = {lane: rows_of(f"s2-c{lane[-1]}") for lane in procs}
for lane, rr in allrows.items():
    check(len(rr) == sum(1 for u in s2 if plan.lane_roles(u)[lane] != "none"), f"{lane}: {len(rr)} rows, one per unit where the lane has a role")
for u in s2:
    t = [r for r in allrows[u["position"]] if r["unit"] == u["id"]][0]
    check(t["role"] == "target" and t["status"] == "ok" and t["figure"] and t["figure"] > 0 and t["gate_ok"] is True and t["throttle_ms"] == 0 and t["cpus_allowed"] == t["cpus_expected"], f"{u['id']}: target row has a figure ({t['figure']:.4g} {t['unit_label']}), the gate, throttle 0 and the pinned cores")
    starts = [r["t_start"] for lane in procs for r in allrows[lane] if r["unit"] == u["id"]]
    ends = [r["t_end"] for lane in procs for r in allrows[lane] if r["unit"] == u["id"]]
    check(max(starts) - min(starts) < 0.6 and min(ends) >= t["t_end"] - 0.5, f"{u['id']}: the lanes started within {max(starts) - min(starts):.2f} s of each other and the neighbours ran until the target ended")
    if u["kind"] == "perm":
        roles = {lane: [r for r in allrows[lane] if r["unit"] == u["id"]][0]["role"] for lane in procs}
        check(sorted(roles.values()) == sorted(r.split(":")[0] for r in plan.lane_roles(u).values()), f"{u['id']}: roles {roles}")
# resume
p = start("s2-c2", "compare2")
p.communicate(timeout=60)
check(p.returncode == 0 and len(rows_of("s2-c2")) == len(allrows["compare2"]), "a second start of the claim writes no new row (resume)")
# refusals
p = start("s2-c2", "compare3")
_, err = p.communicate(timeout=60)
check(p.returncode == 2 and "REFUSED" in err, "a claim started on another lane than its order says is refused (exit 2)")
p = start("s2-c2", "compare2", cls="io_heavy")
_, err = p.communicate(timeout=60)
check(p.returncode == 2 and "REFUSED" in err, "a claim started with another cell class than its order says is refused (exit 2)")
p = start("nope", "compare2")
_, err = p.communicate(timeout=60)
check(p.returncode == 2 and "REFUSED" in err, "an OUT that is not in the order is refused (exit 2)")
# rendezvous failure: only compare1 and compare2 start for stage s4
a = start("s4-c1", "compare1", extra={"PILOT_RENDEZVOUS_S": "4"})
b = start("s4-c2", "compare2", extra={"PILOT_RENDEZVOUS_S": "4"})
a.communicate(timeout=60)
b.communicate(timeout=60)
check(a.returncode == 4 and b.returncode == 4, f"stage s4 with compare3 missing: the rendezvous fails and both claims exit 4 ({a.returncode}, {b.returncode})")
# the same stage queued again with -r2 on every OUT runs, with its own sync folder
rr = {lane: start(f"s4-c{lane[-1]}-r2", lane) for lane in ("compare1", "compare2", "compare3")}
rr_out = {lane: p.communicate(timeout=120) for lane, p in rr.items()}
for lane, o in rr_out.items():
    if rr[lane].returncode:
        print(lane, rr[lane].returncode, o[1][-600:], o[0][-600:])
check(all(p.returncode == 0 for p in rr.values()) and sum(len(rows_of(f"s4-c{i}-r2")) for i in (1, 2, 3)) >= 1, "stage s4 queued again with -r2 on every OUT runs to the end (exit 0, rows written)")
# solo stage
s = start("s1-solo", "solo", cls=None)
out, err = s.communicate(timeout=120)
sr = rows_of("s1-solo")
check(s.returncode == 0 and len(sr) == 1 and sr[0]["figure"] > 0 and sr[0]["role"] == "target", f"solo claim: exit {s.returncode}, one row, figure {sr[0]['figure'] if sr else None:.4g}")
# analyze reads the rows
d = tempfile.mkdtemp(prefix="pilot-smoke-an-")
q = subprocess.run([sys.executable, "-I", os.path.join(HERE, "analyze.py"), "--order", os.path.join(study, "order.json"), "--rows", study, "--out-dir", d, "--boot", "200"], capture_output=True, text=True)
check(q.returncode == 0, f"analyze.py reads the runner's rows (smoke leg, no verdict): exit {q.returncode} {q.stderr.strip()[:100]}")
shutil.rmtree(study)
shutil.rmtree(fake)
print(f"\nRUNNER SMOKE OK: {N} checks")
