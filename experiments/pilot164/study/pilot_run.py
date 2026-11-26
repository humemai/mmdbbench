#!/usr/bin/env python3
"""pilot_run.py: the claim of one lane in one stage of the pilot of mmdbbench#164. Stdlib only. Started by run_ab.sh, which the Humem Worker starts on the lane.

Environment (set by the Worker): OUT (the claim's label), HUMEM_HOST_LANE (compare1..3 or solo), HUMEM_HOST_CPUS (the lane's cores, such as 0,2), HUMEM_HOST_CELL_CLASS.
Reads order.json and order-*-t1.json in this folder, finds the claim whose `out` is OUT, checks lane and class against it, and runs the units of the claim's stage in order.

Compare stages run the three lanes in lock step. For every unit each lane prepares its work (the probe's setup), writes a `ready` marker, and the leader (compare1)
waits for all three, holds the thermal gate (package at most PILOT_GATE_C, default 70 C, poll 10 s, cap 900 s) and writes `go` with a start time 3 s ahead. Then each
lane plays its role: `target` (the measured run), `busy:<probe>` (a probe that loops until the target is done), `light` (busy about 1 percent of the time until the
target is done) or `none` (waits). The target writes `done`. Every lane that ran writes one row: figure, times, package temperature, throttle time of its cores
(thermal_throttle counters, as the Worker's sampler reads them), the cores read back from /proc, gate result. A unit that a lane could not join within 600 s is aborted
by the leader for everybody (`abort`); two aborted units in a row end the stage. The first rendezvous of a stage waits up to 30 minutes (the claims start one
Worker tick apart); if it fails the claim exits 4 and is queued again with a new OUT.
A unit that already has a row of this lane is skipped, so a claim that the Worker restarts after a halt resumes; a unit that was started but has no row is written
as `failed: interrupted`. Nothing is timed outside the units. Heat leg: every lane runs its probe for the whole box and writes one row.
A target whose workload is `cell:<name>` is one benchmark cell run by cell_run.py (legs L5 and L6, smoke leg C0): the pins are checked before the first
rendezvous (a refusal is exit 4), the figure is the cell's wall time in seconds, and every role of such a unit waits for the target as long as the cell may run.
"""
import glob
import hashlib
import json
import os
import re
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LANES = ("compare1", "compare2", "compare3")
RENDEZVOUS_S = float(os.environ.get("PILOT_RENDEZVOUS_S", "1800"))  # PILOT_RENDEZVOUS_S and PILOT_READY_S are test hooks of the smoke
READY_S = float(os.environ.get("PILOT_READY_S", "600"))
GATE_C = float(os.environ.get("PILOT_GATE_C", "70"))
GATE_POLL_S = 10
GATE_CAP_S = 900
GO_AHEAD_S = 3.0
LIGHT_BUSY_S, LIGHT_PERIOD_S = 0.0004, 0.04


def load_probes():
    import importlib.util
    spec = importlib.util.spec_from_file_location("pilot_probes", os.path.join(HERE, "probes.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_cells():
    import importlib.util
    spec = importlib.util.spec_from_file_location("pilot_cells", os.path.join(HERE, "cell_run.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def log(msg):
    print(time.strftime("%H:%M:%SZ", time.gmtime()) + " " + msg, flush=True)


def parse_cpus(text):
    out = set()
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.update(range(int(a), int(b) + 1))
        elif part.strip():
            out.add(int(part))
    return sorted(out)


def lane_roles(u):
    """The same function as plan.lane_roles (the study folder has no plan.py)."""
    if u["kind"] == "solo":
        return {"solo": "target"}
    if u["kind"] == "heat":
        return {lane: "busy:" + s for lane, s in u["streams"].items()}
    r = {lane: "none" for lane in LANES}
    r[u["position"]] = "target"
    if u["kind"] == "perm":
        if u["busy_lane"]:
            r[u["busy_lane"]] = "busy:" + u["busy_stream"]
        for x in u["light_lanes"]:
            r[x] = "light"
    return r


# ---- the host's readings ---------------------------------------------------------------------------------------------------------------------------------


def temp_path():
    for d in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        try:
            if open(os.path.join(d, "name")).read().strip() == "coretemp":
                return os.path.join(d, "temp1_input")
        except OSError:
            continue
    return None


TEMP = os.environ.get("PILOT_TEMP_FILE") or temp_path()  # PILOT_TEMP_FILE and PILOT_THROTTLE_ROOT are test hooks of the smoke on the laptop; rows made with them say so
THROTTLE_ROOT = os.environ.get("PILOT_THROTTLE_ROOT") or "/sys/devices/system/cpu"
TEST_HOOKS = any(os.environ.get(k) for k in ("PILOT_TEMP_FILE", "PILOT_THROTTLE_ROOT", "PILOT_RENDEZVOUS_S", "PILOT_READY_S"))


def pkg_c():
    try:
        return int(open(TEMP).read()) / 1000.0
    except (OSError, TypeError, ValueError):
        return None


def throttle_counters(cpus):
    out = {}
    for c in cpus:
        for name in ("core_throttle_total_time_ms", "package_throttle_total_time_ms"):
            try:
                out[(c, name)] = int(open(f"{THROTTLE_ROOT}/cpu{c}/thermal_throttle/{name}").read())
            except (OSError, ValueError):
                pass
    return out


def throttle_delta(before, after):
    d = [after[k] - before[k] for k in before if k in after and after[k] >= before[k]]
    return max(d) if d else None


class Watch:
    """Package temperature every 2 s while a unit runs."""

    def __init__(self):
        self.vals, self.stop = [], threading.Event()
        self.th = threading.Thread(target=self.loop, daemon=True)

    def loop(self):
        while not self.stop.is_set():
            v = pkg_c()
            if v is not None:
                self.vals.append(v)
            self.stop.wait(2.0)

    def __enter__(self):
        v = pkg_c()
        if v is not None:
            self.vals.append(v)
        self.th.start()
        return self

    def __exit__(self, *a):
        self.stop.set()
        self.th.join(3)
        v = pkg_c()
        if v is not None:
            self.vals.append(v)


def thermal_gate():
    """Wait until the package is at most GATE_C (poll 10 s, cap 900 s). Returns (gate_ok, waited_s, temperature)."""
    t0 = time.time()
    while True:
        v = pkg_c()
        if v is None:
            return False, time.time() - t0, None
        if v <= GATE_C:
            return True, time.time() - t0, v
        if time.time() - t0 >= GATE_CAP_S:
            return False, time.time() - t0, v
        time.sleep(GATE_POLL_S)


# ---- markers ---------------------------------------------------------------------------------------------------------------------------------------------


def touch(path, text=""):
    with open(path + ".tmp", "w") as fh:
        fh.write(text)
    os.replace(path + ".tmp", path)


def wait_for(paths, timeout, stop_on=None):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if stop_on and os.path.exists(stop_on):
            return "abort"
        if all(os.path.exists(p) for p in paths):
            return "ok"
        time.sleep(0.5)
    return "timeout"


# ---- the roles -------------------------------------------------------------------------------------------------------------------------------------------


def prepare(probes, workload, cpus_text, iodir):
    if workload.startswith("cell:"):
        probes.pin(cpus_text)
        return {"cell": workload.split(":", 1)[1], "allowed": probes.allowed_cpus()}
    if not workload.startswith("probe:"):
        raise SystemExit("REFUSED: workload " + workload + " has no runner")
    name = workload.split(":", 1)[1]
    allowed = probes.pin(cpus_text)
    os.makedirs(iodir, exist_ok=True)
    state = probes.SETUP[name](cpus=probes.parse_cpus(cpus_text), buffer_mib=None, directory=iodir, size_mib=None)
    return {"name": name, "allowed": allowed, "state": state}


def run_workload(probes, prep, seconds):
    t0 = time.time()
    res = probes.RUN[prep["name"]](seconds, state=prep["state"])
    return res, t0, time.time(), bool(probes.STOP)


def light_loop(stop_path, cap_s):
    t0 = time.time()
    while time.time() - t0 < cap_s and not os.path.exists(stop_path):
        end = time.perf_counter() + LIGHT_BUSY_S
        while time.perf_counter() < end:
            pass
        time.sleep(LIGHT_PERIOD_S - LIGHT_BUSY_S)
    return time.time() - t0


def stopper(probes, stop_path, cap_s):
    def run():
        t0 = time.time()
        while time.time() - t0 < cap_s + 5:
            if os.path.exists(stop_path):
                probes.STOP = True
                return
            time.sleep(0.25)
    th = threading.Thread(target=run, daemon=True)
    th.start()
    return th


# ---- main ------------------------------------------------------------------------------------------------------------------------------------------------


def main():
    out = os.environ.get("OUT")
    lane = os.environ.get("HUMEM_HOST_LANE")
    cpus_text = os.environ.get("HUMEM_HOST_CPUS")
    cell_class = os.environ.get("HUMEM_HOST_CELL_CLASS") or None
    if not (out and lane and cpus_text):
        print("REFUSED: OUT, HUMEM_HOST_LANE and HUMEM_HOST_CPUS must be set (the Worker sets them)", file=sys.stderr)
        return 2
    orders = [json.load(open(f)) for f in sorted(glob.glob(os.path.join(HERE, "order*.json")))]
    claim, order = None, None
    base_out = re.sub(r"-r\d+$", "", out)  # a stage whose rendezvous failed is queued again with -r2 appended to every OUT: same claim, its own sync folder
    suffix = out[len(base_out):]
    for o in orders:
        for c in o["claims"]:
            if c["out"] == base_out:
                claim, order = c, o
    if claim is None:
        print(f"REFUSED: no claim with OUT {out} in the orders of this folder", file=sys.stderr)
        return 2
    if claim["lane"] != lane or (claim["cell_class"] or None) != cell_class:
        print(f"REFUSED: the claim says lane {claim['lane']} class {claim['cell_class']}, the Worker gave lane {lane} class {cell_class}", file=sys.stderr)
        return 2
    if not order.get("claimable"):
        print("REFUSED: this leg is not claimable yet: " + str(order.get("needs")), file=sys.stderr)
        return 2
    probes = load_probes()
    cells, facts = None, None
    mine = parse_cpus(cpus_text)
    probes.pin(cpus_text)
    if len(probes.parse_cpus(probes.allowed_cpus())) != len(mine):
        print("REFUSED: the process may run on other cores than the lane's", file=sys.stderr)
        return 5
    stage = claim["stage"]
    units = [u for u in order["units"] if u["stage"] == stage]
    odir = os.path.join(HERE, out)
    os.makedirs(odir, exist_ok=True)
    rows_path = os.path.join(odir, "rows.jsonl")
    done_units = set()
    if os.path.exists(rows_path):
        for ln in open(rows_path):
            if ln.strip():
                done_units.add(json.loads(ln)["unit"])
    sync = os.path.join(HERE, "sync", order["leg"], stage + suffix)
    os.makedirs(sync, exist_ok=True)
    compare = lane != "solo"
    shortened = not order["data"]
    provenance = {"runner_sha256": sha(__file__), "probes_sha256": sha(os.path.join(HERE, "probes.py")), "order_leg": order["leg"], "seed": order["seed"], "salt": order["salt"]}

    # a lane that is the target of a cell checks the pins before anything else: a missing wheel or image ends the claim with no row
    if any((lane_roles(u).get(lane) == "target") and order_workload(order, u).startswith("cell:") for u in units):
        cells = load_cells()
        try:
            facts = cells.preflight(order["data"])
        except cells.CellError as exc:
            print("REFUSED: the cell pins: " + str(exc), file=sys.stderr)
            return 4
        provenance.update({"cell_run_sha256": sha(os.path.join(HERE, "cell_run.py")), "cell_json_sha256": sha(os.path.join(HERE, "cell.json"))})

    def write_row(row):
        row.update({"leg": order["leg"], "stage": stage, "out": out, "lane": lane, "cpus_expected": cpus_text, "shortened": shortened, "host_lane": lane, "cell_class": cell_class})
        row.update(provenance)
        row["test_hooks"] = TEST_HOOKS or bool(row.get("test_hooks_cell"))
        with open(rows_path, "a") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    log(f"claim {claim['job']} lane {lane} cpus {cpus_text} class {cell_class} stage {stage}: {len(units)} units, {len(done_units)} already have rows")
    if compare:
        touch(os.path.join(sync, f"rendezvous.{lane}.ready"))
        if lane == "compare1":
            r = wait_for([os.path.join(sync, f"rendezvous.{x}.ready") for x in LANES], RENDEZVOUS_S)
            touch(os.path.join(sync, "rendezvous.go" if r == "ok" else "stage-abort"))
        r = wait_for([os.path.join(sync, "rendezvous.go")], RENDEZVOUS_S + 60, os.path.join(sync, "stage-abort"))
        if r != "ok":
            log("rendezvous failed: the other lanes did not start; exit 4")
            return 4
    aborted_in_a_row = 0
    n_rows = 0
    for u in units:
        roles = lane_roles(u)
        role = roles.get(lane)
        if role is None:
            continue
        uid = u["id"]
        if uid in done_units:
            log(f"{uid}: has a row, skipped")
            continue
        base = os.path.join(sync, uid)
        if os.path.exists(base + ".abort"):
            if role != "none":
                write_row({"unit": uid, "role": role.split(":")[0], "status": "failed", "reason": "barrier-abort", "figure": None})
                n_rows += 1
            continue
        started_before = os.path.exists(base + ".go")
        if started_before:
            if role != "none":
                write_row({"unit": uid, "role": role.split(":")[0], "status": "failed", "reason": "interrupted: this lane's claim was restarted inside the unit", "figure": None})
                n_rows += 1
            continue
        box = float(u["box_s"])
        cap = box * 1.5 + 60
        if u["kind"] != "heat" and order_workload(order, u).startswith("cell:"):
            cap = load_cells().load_config()["timeout_s"] + 900  # neighbours cover the target for as long as the cell may run
        iodir = os.path.join(odir, "io")
        prep = None
        try:
            if role == "target" or role.startswith("busy:"):
                workload = ("probe:" + role.split(":probe:")[1]) if role.startswith("busy:") else order_workload(order, u)
                prep = prepare(probes, workload, cpus_text, iodir)
        except SystemExit as exc:
            print(str(exc), file=sys.stderr)
            return 2
        gate = {"ok": True, "waited": 0.0, "temp": pkg_c()}
        if compare:
            touch(base + f".{lane}.ready")
            if lane == "compare1":
                r = wait_for([base + f".{x}.ready" for x in LANES], READY_S)
                if r != "ok":
                    touch(base + ".abort")
                else:
                    ok, waited, temp = thermal_gate()
                    touch(base + ".go", json.dumps({"t_go": time.time() + GO_AHEAD_S, "gate_ok": ok, "gate_wait_s": waited, "pkg_c": temp}))
            r = wait_for([base + ".go"], READY_S + GATE_CAP_S + 120, base + ".abort")
            if r != "ok":
                log(f"{uid}: aborted (a lane did not join)")
                aborted_in_a_row += 1
                if role != "none":
                    write_row({"unit": uid, "role": role.split(":")[0], "status": "failed", "reason": "barrier-abort", "figure": None})
                    n_rows += 1
                if aborted_in_a_row >= 2:
                    log("two aborted units in a row: the stage ends")
                    if lane == "compare1":
                        touch(os.path.join(sync, "stage-abort"))
                    return 4
                continue
            aborted_in_a_row = 0
            g = json.load(open(base + ".go"))
            gate = {"ok": bool(g["gate_ok"]), "waited": g["gate_wait_s"], "temp": g["pkg_c"]}
            while time.time() < g["t_go"]:
                time.sleep(0.01)
        else:
            ok, waited, temp = thermal_gate()
            gate = {"ok": ok, "waited": waited, "temp": temp}
            touch(base + ".go", json.dumps({"t_go": time.time(), "gate_ok": ok, "gate_wait_s": waited, "pkg_c": temp}))
        stop_path = base + ".done"
        probes.STOP = False
        before = throttle_counters(mine)
        row = {"unit": uid, "role": role.split(":")[0], "status": "ok", "reason": None, "figure": None, "gate_ok": gate["ok"], "gate_wait_s": round(gate["waited"], 1)}
        with Watch() as w:
            t_start = time.time()
            try:
                if role == "target" or role.startswith("busy:"):
                    is_target = role == "target"
                    if not is_target:
                        stopper(probes, stop_path, cap)
                    if "cell" in prep:
                        t_start = time.time()
                        res = cells.run(facts, prep["cell"], cpus_text, odir, f"{out}_{uid}", {"ok": gate["ok"], "waited": gate["waited"], "temp": gate["temp"], "max_c": GATE_C})
                        t_end, partial = time.time(), False
                        row.update(res["extra"])
                        row["unit_label"] = "s"
                        row["test_hooks_cell"] = cells.test_hooks()
                    else:
                        res, t_start, t_end, partial = run_workload(probes, prep, box if (is_target or u["kind"] == "heat") else cap)
                        row["unit_label"] = probes.UNITS[prep["name"]]
                    row["figure"] = res["value"] if is_target or u["kind"] == "heat" else None
                    row["cpus_allowed"] = prep["allowed"]
                    row["status"] = "partial" if partial and not is_target else "ok"
                    if is_target and u["kind"] != "heat":
                        touch(stop_path)
                elif role == "light":
                    light_loop(stop_path, cap)
                    t_end = time.time()
                    row["cpus_allowed"] = probes.allowed_cpus()
                else:
                    wait_for([stop_path], cap)
                    t_end = time.time()
            except Exception as exc:  # a probe that fails writes a failed row; the stage goes on
                t_end = time.time()
                row.update({"status": "failed", "reason": f"{type(exc).__name__}: {exc}"})
                if role == "target":
                    touch(stop_path)
        if role != "none":
            row.update({"t_start": round(t_start, 3), "t_end": round(t_end, 3), "wall_s": round(t_end - t_start, 3), "pkg_c_start": w.vals[0] if w.vals else None,
                        "pkg_c_max": max(w.vals) if w.vals else None, "throttle_ms": throttle_delta(before, throttle_counters(mine))})
            write_row(row)
            n_rows += 1
            log(f"{uid}: {role} {row['status']} figure {row['figure']} wall {row['wall_s']} s, package {row['pkg_c_start']} to {row['pkg_c_max']} C, throttle {row['throttle_ms']} ms, gate {gate['ok']}")
        elif compare:
            log(f"{uid}: waited as {role}")
    with open(os.path.join(odir, "analysis.txt"), "w") as fh:
        fh.write(f"claim {claim['job']} lane {lane} stage {stage}: {n_rows} rows written, {len(units)} units in the stage; the analysis is analyze.py's, run on the laptop from the rows.jsonl files\n")
    log("claim done")
    return 0


def order_workload(order, u):
    for t in order["targets"]:
        if t["id"] == u["target"]:
            return t["workload"]
    raise SystemExit("REFUSED: no target " + str(u["target"]))


if __name__ == "__main__":
    sys.exit(main())
