#!/usr/bin/env python3
"""plan.py: the seeded, balanced order of the pilot of mmdbbench#164 (permuted neighbours on the mini's compare lanes), and the claims that carry it.

Run (stdlib only, deterministic: the same arguments give the same bytes):
  uv run --no-project python -I plan.py build --leg L1 --seed 20261124 --out-dir DIR
  uv run --no-project python -I plan.py check --order DIR/order-L1.json
  uv run --no-project python -I plan.py topup --order DIR/order-L1.json --invalid invalid.json --out DIR/order-L1-t1.json
  uv run --no-project python -I plan.py claims --order DIR/order-L1.json

THE DESIGN (PREREG.md sections 3 and 4; every constant below is registered, a change after the first run is a new pilot)

* A leg has targets (a probe or a real cell), neighbour levels, and 5 runs per target and level (reps). The levels are `idle` and the busy
  streams `compute` (probe cpu), `membw` (probe membw) and `io` (probe io).
* A permuted block is the target on one compare lane, ONE busy neighbour stream (or none) on a second lane, and a LIGHT neighbour (a process
  that is busy about 1 percent of the time) on the third lane. At most two lanes are busy at once: the mini throttled with three busy lanes
  (humem-ops#480), so three busy lanes wait for a measured long run (leg H). In the `idle` level both neighbours are light.
* Admission is part of the design: the order only places a class on a lane that the mini's record admits. `--lanes-proven` is the record's
  `lanes_proven` per class (default: compute 3, bw_heavy 1, io_heavy 1, none 1, the record `mini-2026-11-19-1b62305a8e21`). A class with N proven
  lanes may use the first N of compare1, compare2, compare3. So a memory-bandwidth or disk stream, and a target of such a class, sit on
  compare1 only until a qualification plan proves more.
* Balance: each (target, level) has n runs (n = 5 here), the positions of the target are equal within one among the admitted positions of that level
  (the extra run goes to the position with the smallest total, ties by the seed), the neighbour lane alternates, the level order of a round is a
  cyclic Latin-square row of a seeded permutation (reversed in later cycles), and the targets are interleaved so that every target spreads over the
  whole pilot. A seeded search over a salt takes the first order whose correlation between run order (drift) and every level and position dummy is at
  most 0.30 (`check_design`); the salt is written into the order file.
* Solo references: the solo lane at full width (cores 0-11), and the same target alone on two cpus (a compare lane, nothing beside it, every admitted
  position once per set). `ref_n` runs at the start and at the end, `mid_n` runs in the middle, after round ceil(0.6 n).
* Stages (each is one claim per lane, see claims): s1 solo start, s2 compare (alone start set, rounds before the middle, alone middle),
  s3 solo middle, s4 compare (rounds after the middle, alone end set), s5 solo end. A top-up stage replaces invalid runs, once (`topup`).
"""
import argparse
import hashlib
import json
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LANES = ("compare1", "compare2", "compare3")
SHORT = {"compare1": "c1", "compare2": "c2", "compare3": "c3", "solo": "solo"}
DEFAULT_PROVEN = {"compute": 3, "bw_heavy": 1, "io_heavy": 1, "none": 1}
CORR_MAX = 0.30
SALT_MAX = 5000
SPLIT_SHARE = 0.6
ISSUE = "humemai/mmdbbench#164"
LEVELS = {
    "idle": {"stream": None, "cls": None},
    "compute": {"stream": "probe:cpu", "cls": "compute"},
    "membw": {"stream": "probe:membw", "cls": "bw_heavy"},
    "io": {"stream": "probe:io", "cls": "io_heavy"},
}
PROBE_BOX_S = {"cpu": 60, "membw": 60, "io": 90}  # probes.DEFAULT_SECONDS of humem-ops (a test in cost_legs.py keeps them equal)
PROBE_TARGETS = {
    "cpu": {"id": "cpu", "workload": "probe:cpu", "cls": "compute", "unit": "ops/s", "probe": True, "box_s": PROBE_BOX_S["cpu"]},
    "membw": {"id": "membw", "workload": "probe:membw", "cls": "bw_heavy", "unit": "MB/s", "probe": True, "box_s": PROBE_BOX_S["membw"]},
}
HEAT_SECONDS = 1800
LEGS = {
    "L0": {"title": "smoke of the chain on the mini (shortened, never data)", "targets": ["cpu"], "levels": ["idle", "compute"], "reps": 2, "ref_n": 1, "mid_n": 0, "end_n": 0,
           "seconds": 5, "data": False, "claimable": True},
    "L1": {"title": "compute: probe cpu beside idle and compute neighbours", "targets": ["cpu"], "levels": ["idle", "compute"], "reps": 5, "ref_n": 3, "mid_n": 1,
           "data": True, "claimable": True},
    "L2": {"title": "bandwidth stand-in: probe membw (compare1 only) beside idle and compute neighbours", "targets": ["membw"], "levels": ["idle", "compute"],
           "reps": 5, "ref_n": 3, "mid_n": 1, "data": True, "claimable": True},
    "L3": {"title": "probe cpu beside idle, compute and one membw stream (on compare1)", "targets": ["cpu"], "levels": ["idle", "compute", "membw"], "reps": 5,
           "ref_n": 3, "mid_n": 1, "data": True, "claimable": True},
    "L4": {"title": "probe cpu beside idle, compute and one io stream (on compare1)", "targets": ["cpu"], "levels": ["idle", "compute", "io"], "reps": 5,
           "ref_n": 3, "mid_n": 1, "data": True, "claimable": True},
    "H": {"title": "heat run: compare1 membw, compare2 cpu, compare3 cpu at once for 30 minutes (decides whether three busy lanes may be used)", "heat": True,
          "data": True, "claimable": True},
    "C0": {"title": "smoke of the cell command (two cells once each: solo, two cpus alone, beside one compute neighbour; never data)", "targets": ["picks:cache and latency"],
           "levels": ["compute"], "reps": 1, "ref_n": 1, "mid_n": 0, "end_n": 0, "data": False, "claimable": True},
    "L5": {"title": "disk I/O: the two strict cells of picks.json (compare1 only) beside idle and compute neighbours", "targets": ["picks:disk I/O"],
           "levels": ["idle", "compute"], "reps": 5, "ref_n": 3, "mid_n": 1, "data": True, "claimable": True},
    "L6": {"title": "cache and latency: the two relaxed cells of picks.json (compare1 only) beside idle and compute neighbours", "targets": ["picks:cache and latency"],
           "levels": ["idle", "compute"], "reps": 5, "ref_n": 3, "mid_n": 1, "data": True, "claimable": True},
}


def sha256_file(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def admitted(cls, proven):
    n = proven.get(cls or "none", 1)
    return list(LANES[:max(1, min(3, n))])


def resolve_targets(leg, picks):
    out = []
    for tid in leg.get("targets", []):
        if tid in PROBE_TARGETS:
            out.append(dict(PROBE_TARGETS[tid]))
        elif tid.startswith("picks:"):
            klass = tid.split(":", 1)[1]
            for c in picks["picks"][klass]:
                out.append({"id": f"{c['cell']}.{c['arm']}", "workload": "cell:" + c["cell"], "arm": c["arm"], "cls": "io_heavy" if klass == "disk I/O" else None,
                            "unit": "s", "probe": False, "box_s": round(c["wall_s"])})
        else:
            raise SystemExit("unknown target " + tid)
    return out


def tclass(t):
    return t["cls"]


def feasible(t, level, proven):
    """The positions (compare lanes) where target t may sit when the neighbour level is `level`, given what the record admits."""
    pos = admitted(tclass(t), proven)
    st = LEVELS[level]["stream"]
    if st is None:
        return pos
    nb = admitted(LEVELS[level]["cls"], proven)
    return [p for p in pos if any(q != p for q in nb)]


def corr(a, b):
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va == 0 or vb == 0:
        return 0.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def check_design(units, targets, levels, proven, expect_equal=True, corr_max=CORR_MAX):
    """The balance rules of PREREG.md section 3, for the permuted units of a plan (expect_equal) or of the runs that are left (expect_equal=False).
    Returns a list of problems; an empty list is a balanced design."""
    problems = []
    for t in targets:
        us = sorted((u for u in units if u["kind"] == "perm" and u["target"] == t["id"]), key=lambda u: u["idx"])
        if not us:
            problems.append(f"{t['id']}: no permuted run")
            continue
        counts = {l: sum(1 for u in us if u["level"] == l) for l in levels}
        if expect_equal and len(set(counts.values())) > 1:
            problems.append(f"{t['id']}: unequal runs per level {counts}")
        for l in levels:
            feas = feasible(t, l, proven)
            at = [u for u in us if u["level"] == l]
            if any(u["position"] not in feas for u in at):
                problems.append(f"{t['id']}/{l}: a run sits on a lane that the record does not admit for it")
            c = [sum(1 for u in at if u["position"] == p) for p in feas]
            if c and max(c) - min(c) > 1:
                problems.append(f"{t['id']}/{l}: lane positions not equal within one {dict(zip(feas, c))}")
        if corr_max is None or len(us) < 8:
            continue
        rank = list(range(len(us)))
        for l in levels:
            if l == "idle" or counts[l] == 0:
                continue
            r = corr(rank, [1.0 if u["level"] == l else 0.0 for u in us])
            if abs(r) > corr_max:
                problems.append(f"{t['id']}: run order is confounded with level {l} (correlation {r:+.2f})")
        for p in sorted({u["position"] for u in us}):
            if len({u["position"] for u in us}) < 2:
                break
            r = corr(rank, [1.0 if u["position"] == p else 0.0 for u in us])
            if abs(r) > corr_max:
                problems.append(f"{t['id']}: run order is confounded with position {p} (correlation {r:+.2f})")
    return problems


def attempt(leg_id, leg, targets, seed, salt, proven):
    rng = random.Random(f"{seed}:{leg_id}:{salt}")
    levels, n = leg["levels"], leg["reps"]
    pos_plan = {}
    for t in targets:
        total = {p: 0 for p in admitted(tclass(t), proven)}
        for l in rng.sample(levels, len(levels)):
            feas = feasible(t, l, proven)
            if not feas:
                raise SystemExit(f"{t['id']}/{l}: no lane is admitted for this pair (lanes_proven {proven})")
            base, extra = divmod(n, len(feas))
            cnt = {p: base for p in feas}
            for p in sorted(feas, key=lambda p: (total[p], rng.random()))[:extra]:
                cnt[p] += 1
            for p in feas:
                total[p] += cnt[p]
            seq = [p for p in feas for _ in range(cnt[p])]
            rng.shuffle(seq)
            pos_plan[(t["id"], l)] = seq
    nl = len(levels)
    rows = {}
    for t in targets:
        perm = rng.sample(levels, nl)
        rows[t["id"]] = []
        for r in range(n):
            row = perm[r % nl:] + perm[:r % nl]
            if (r // nl) % 2 == 1:
                row = row[::-1]
            rows[t["id"]].append(row)
    split = math.ceil(SPLIT_SHARE * n)
    ctr, idx, perm_units = {}, 0, []
    for r in range(n):
        for s in range(nl):
            k = (r + s) % len(targets)
            for t in targets[k:] + targets[:k]:
                l = rows[t["id"]][r][s]
                p = pos_plan[(t["id"], l)][r]
                q = None
                if LEVELS[l]["stream"]:
                    cands = [x for x in admitted(LEVELS[l]["cls"], proven) if x != p]
                    start = ctr.setdefault((t["id"], l, p), rng.randrange(len(cands)))
                    ctr[(t["id"], l, p)] = start + 1
                    q = cands[start % len(cands)]
                perm_units.append({"id": f"{leg_id}.p.{t['id']}.{l}.r{r}", "stage": "s2" if r < split else "s4", "kind": "perm", "target": t["id"], "level": l,
                                   "position": p, "busy_lane": q, "busy_stream": LEVELS[l]["stream"], "light_lanes": [x for x in LANES if x not in (p, q)],
                                   "set": None, "rep": r, "round": r, "idx": idx, "box_s": leg.get("seconds") or t["box_s"]})
                idx += 1
    units = {s: [] for s in ("s1", "s2", "s3", "s4", "s5")}

    def solo_units(kind_set, k, stage):
        for i in range(k):
            for t in targets:
                units[stage].append({"id": f"{leg_id}.s.{t['id']}.{kind_set}{i}", "stage": stage, "kind": "solo", "target": t["id"], "level": None, "position": "solo",
                                     "busy_lane": None, "busy_stream": None, "light_lanes": [], "set": kind_set, "rep": i, "round": None, "idx": None,
                                     "box_s": leg.get("seconds") or t["box_s"]})

    def alone_units(kind_set, k, stage):
        cyc = {t["id"]: (lambda b: [b[i % len(b)] for i in range(k)])(rng.sample(admitted(tclass(t), proven), len(admitted(tclass(t), proven)))) for t in targets}
        for i in range(k):
            for t in targets:
                units[stage].append({"id": f"{leg_id}.a.{t['id']}.{kind_set}{i}", "stage": stage, "kind": "alone2", "target": t["id"], "level": None,
                                     "position": cyc[t["id"]][i], "busy_lane": None, "busy_stream": None, "light_lanes": [], "set": kind_set, "rep": i, "round": None,
                                     "idx": None, "box_s": leg.get("seconds") or t["box_s"]})

    solo_units("start", leg["ref_n"], "s1")
    alone_units("start", leg["ref_n"], "s2")
    units["s2"] += [u for u in perm_units if u["stage"] == "s2"]
    alone_units("mid", leg["mid_n"], "s2")
    solo_units("mid", leg["mid_n"], "s3")
    units["s4"] += [u for u in perm_units if u["stage"] == "s4"]
    alone_units("end", leg.get("end_n", leg["ref_n"]), "s4")
    solo_units("end", leg.get("end_n", leg["ref_n"]), "s5")
    return [u for s in ("s1", "s2", "s3", "s4", "s5") for u in units[s]]


def heat_leg(leg_id, leg):
    streams = {"compare1": "probe:membw", "compare2": "probe:cpu", "compare3": "probe:cpu"}
    unit = {"id": f"{leg_id}.h.all3", "stage": "h", "kind": "heat", "target": None, "level": None, "position": None, "busy_lane": None, "busy_stream": None,
            "light_lanes": [], "set": None, "rep": 0, "round": None, "idx": None, "box_s": HEAT_SECONDS, "streams": streams}
    return [unit]


def lane_roles(u):
    """{lane: role} of a unit; role is `target`, `busy:<stream>`, `light` or `none`."""
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


def make_claims(leg_id, units, targets, proven, claimable, stage_prefix=""):
    study = f"pilot164-{leg_id.lower()}"
    tmap = {t["id"]: t for t in targets}
    cls_of = {}
    for lane in LANES:
        s = set()
        for u in units:
            if u["kind"] == "solo":
                continue
            role = lane_roles(u).get(lane)
            if role == "target":
                s.add(tclass(tmap[u["target"]]) or "none")
            elif role and role.startswith("busy:"):
                s.add({"probe:cpu": "compute", "probe:membw": "bw_heavy", "probe:io": "io_heavy"}[role[5:]])
            elif role == "light":
                s.add("compute")
        heavy = s - {"compute"}
        if len(heavy) > 1:
            raise SystemExit(f"{leg_id}: lane {lane} would carry the classes {sorted(heavy)} in one claim: split the leg")
        cls_of[lane] = (heavy.pop() if heavy else "compute")
        if cls_of[lane] == "none":
            cls_of[lane] = None
    claims = []
    for st in dict.fromkeys(u["stage"] for u in units):
        if any(u["kind"] == "solo" for u in units if u["stage"] == st):
            claims.append({"study": study, "out": f"{stage_prefix}{st}-solo", "stage": st, "lane": "solo", "cell_class": None})
        else:
            for lane in LANES:
                claims.append({"study": study, "out": f"{stage_prefix}{st}-{SHORT[lane]}", "stage": st, "lane": lane, "cell_class": cls_of[lane]})
    for c in claims:
        c["issue"] = ISSUE
        c["note"] = f"pilot of #164, leg {leg_id}, stage {c['stage']}, lane {c['lane']}; order.json in the study folder"[:200]
        c["claimable"] = bool(claimable)
        c["job"] = f"{c['study']}@{c['out']}"
    return claims


def build(leg_id, seed, proven, picks, picks_sha):
    leg = LEGS[leg_id]
    targets = resolve_targets(leg, picks)
    if leg.get("heat"):
        units, salt = heat_leg(leg_id, leg), 0
    else:
        units, salt = None, None
        for s in range(SALT_MAX):
            cand = attempt(leg_id, leg, targets, seed, s, proven)
            if not check_design(cand, targets, leg["levels"], proven, corr_max=CORR_MAX if leg["data"] else None):
                units, salt = cand, s
                break
        if units is None:
            raise SystemExit("REFUSED: no balanced order found in %d salts" % SALT_MAX)
    claims = make_claims(leg_id, units, targets, proven, leg["claimable"])
    return {"format": 1, "leg": leg_id, "title": leg["title"], "seed": seed, "salt": salt, "lanes_proven": proven, "levels": leg.get("levels", []), "reps": leg.get("reps"),
            "ref_n": leg.get("ref_n"), "mid_n": leg.get("mid_n"), "data": leg["data"], "claimable": leg["claimable"], "needs": leg.get("needs"),
            "plan_py_sha256": sha256_file(__file__), "picks_json_sha256": picks_sha, "corr_max": CORR_MAX, "targets": targets, "units": units, "claims": claims,
            "topup_of": None}


def topup(order, invalid_ids, tag="t1"):
    """Replacement units for the invalid or missing ones, appended as one more stage (compare and solo claims), once."""
    if order.get("topup_of"):
        raise SystemExit("REFUSED: a top-up of a top-up (one top-up stage per leg)")
    byid = {u["id"]: u for u in order["units"]}
    bad = [byid[i] for i in invalid_ids if i in byid]
    if len(bad) != len(set(invalid_ids)):
        raise SystemExit("REFUSED: an invalid id is not a unit of the order")
    nxt = max([u["idx"] for u in order["units"] if u["idx"] is not None] + [-1]) + 1
    new = []
    for u in sorted(bad, key=lambda u: (u["stage"], u["idx"] if u["idx"] is not None else -1, u["id"])):
        v = dict(u)
        v["id"] = u["id"] + "." + tag
        v["replaces"] = u["id"]
        v["stage"] = (tag + "s") if u["kind"] == "solo" else (tag + "c")
        if u["kind"] == "perm":
            v["idx"] = nxt
            nxt += 1
        new.append(v)
    targets = order["targets"]
    claims = make_claims(order["leg"], new, targets, order["lanes_proven"], order["claimable"])
    return {"format": 1, "leg": order["leg"], "title": order["title"] + " (top-up " + tag + ")", "seed": order["seed"], "salt": order["salt"], "lanes_proven": order["lanes_proven"],
            "levels": order["levels"], "reps": order["reps"], "ref_n": order["ref_n"], "mid_n": order["mid_n"], "data": order["data"], "claimable": order["claimable"],
            "needs": order["needs"], "plan_py_sha256": sha256_file(__file__), "picks_json_sha256": order["picks_json_sha256"], "corr_max": order["corr_max"], "targets": targets,
            "units": new, "claims": claims, "topup_of": order["leg"]}


def dump(obj, path):
    data = json.dumps(obj, indent=1, sort_keys=True) + "\n"
    open(path + ".new", "w", encoding="utf-8").write(data)
    os.replace(path + ".new", path)
    return hashlib.sha256(data.encode()).hexdigest()


def parse_proven(text):
    proven = dict(DEFAULT_PROVEN)
    if text:
        for kv in text.split(","):
            k, v = kv.split("=")
            if k not in proven or not v.isdigit():
                raise SystemExit("bad --lanes-proven " + kv)
            proven[k] = int(v)
    return proven


def report(order):
    units = order["units"]
    kinds = {}
    for u in units:
        kinds[u["kind"]] = kinds.get(u["kind"], 0) + 1
    lines = [f"leg {order['leg']}: {order['title']}", f"seed {order['seed']} salt {order['salt']} units {len(units)} {kinds}"]
    for t in order["targets"]:
        us = [u for u in units if u["kind"] == "perm" and u["target"] == t["id"]]
        for l in order["levels"]:
            c = {}
            for u in us:
                if u["level"] == l:
                    c[u["position"]] = c.get(u["position"], 0) + 1
            lines.append(f"  {t['id']:<44} {l:<8} runs {sum(c.values())}  by position {c}")
    for c in order["claims"]:
        lines.append(f"  claim {c['job']:<28} lane {c['lane']:<9} cell_class {c['cell_class']}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--leg", required=True, choices=sorted(LEGS))
    b.add_argument("--seed", type=int, required=True)
    b.add_argument("--lanes-proven", default="")
    b.add_argument("--picks", default=os.path.join(HERE, "picks.json"))
    b.add_argument("--out-dir", required=True)
    c = sub.add_parser("check")
    c.add_argument("--order", required=True)
    t = sub.add_parser("topup")
    t.add_argument("--order", required=True)
    t.add_argument("--invalid", required=True, help="JSON list of unit ids (analyze.py writes it)")
    t.add_argument("--out", required=True)
    cl = sub.add_parser("claims")
    cl.add_argument("--order", required=True)
    a = ap.parse_args()
    if a.cmd == "build":
        proven = parse_proven(a.lanes_proven)
        picks = json.load(open(a.picks))
        order = build(a.leg, a.seed, proven, picks, sha256_file(a.picks))
        os.makedirs(a.out_dir, exist_ok=True)
        path = os.path.join(a.out_dir, f"order-{a.leg}.json")
        print(report(order))
        print(f"sha256 {dump(order, path)}  {path}")
    elif a.cmd == "check":
        order = json.load(open(a.order))
        probs = check_design(order["units"], order["targets"], order["levels"], order["lanes_proven"], corr_max=order["corr_max"] if order["data"] else None) if not order["claims"][0]["stage"] == "h" else []
        print(report(order))
        print("BALANCED" if not probs else "NOT BALANCED:\n  " + "\n  ".join(probs))
        sys.exit(1 if probs else 0)
    elif a.cmd == "topup":
        order = json.load(open(a.order))
        new = topup(order, json.load(open(a.invalid)))
        print(report(new))
        print(f"sha256 {dump(new, a.out)}  {a.out}")
    else:
        for c in json.load(open(a.order))["claims"]:
            print(json.dumps(c, sort_keys=True))


if __name__ == "__main__":
    main()
