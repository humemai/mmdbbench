#!/usr/bin/env python3
"""analyze.py: the registered analysis of the pilot of mmdbbench#164. Every number of the report is computed here from the order file and the rows files.

Run (stdlib only):
  uv run --no-project python -I analyze.py --order order-L1.json [--topup order-L1-t1.json] --rows DIR [DIR ...] --out-dir OUT [--interim] [--boot 10000]
  uv run --no-project python -I analyze.py --order order-H.json --rows DIR [DIR ...] --out-dir OUT          (the heat leg: no model, a heat verdict)
Exit codes: 0 a report was written, 2 the input is refused (not balanced as planned, a repeated row, a malformed line, another leg, no rows).

THE MODEL (PREREG.md section 4), per target: y = ln(figure) of the permuted runs that are valid,
  y = b0 + sum over non-idle levels b_l [level = l] + sum over positions c_p (effect coded, sum to zero) + d * t
where t is the run's place in the planned order of that target, centred and divided by the number of its planned runs (so d is the drift over the whole
pilot). exp(b0) is the figure with an idle neighbour, averaged over the lane positions, at the middle of the pilot. exp(b_l) is the factor that a busy
neighbour of level l puts on it (the interference matrix). A term whose column the design cannot identify (a level or a position with no valid run) makes the
target UNDECIDED. Intervals: 95 percent. HC3 robust standard error with a t quantile on n - p degrees of freedom, and a residual bootstrap
(leverage-corrected residuals, 10000 resamples, seed 1); the WIDER of the two is used, coefficient by coefficient.

THE PASS RULE (registered; r = exp(b0) over the solo figure, the median of the valid full-width solo runs of the start and the end sets):
  PASS       |r - 1| <= 0.03 and the half-width of the interval of exp(b0) is at most 3 percent of exp(b0);
  FAIL       the whole interval of r lies outside 0.97 to 1.03;
  UNDECIDED  otherwise, and always when: the reference is unstable (a set of solo runs spreads by more than 3 percent from smallest to largest, or the
             start and the end median differ by more than 3 percent), a set has fewer than 2 valid runs, more than 10 percent of the planned permuted
             runs are invalid or missing, the realised design has a level or a position confounded with the run order (correlation above 0.60; the planned order is held to 0.30), or the
             model cannot be identified.
  Class      PASS needs at least 2 real cells, all PASS; a stand-in probe gives PROBE-PASS or PROBE-FAIL and never PASS; any FAIL is FAIL.
A run is valid when its row exists, status ok, not shortened (a data leg), pinned as asked, throttle_ms read and at most 1 percent of its wall time, the
start gate held (gate_ok), and every neighbour stream covered at least 95 percent of the target's run. Anything else is invalid and listed; invalid
runs are replaced by one top-up stage (plan.py topup) and never dropped. The interim reading (--interim) uses the first half only and can only say
EARLY-FAIL (the idle median of at least 3 runs per level differs from the solo figure by more than 10 percent); it stops nothing by itself.
"""
import argparse
import glob
import hashlib
import functools
import importlib.util
import json
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BAND = 0.03
THROTTLE_SHARE = 0.01
COVER_MIN = 0.95
MAX_INVALID_SHARE = 0.10
EARLY_FAIL = 0.10
REALISED_CORR_MAX = 0.60  # the planned order must stay at 0.30 (plan.CORR_MAX); runs that are missing or replaced at the end may raise it, a correlation above 0.60 (variance factor 1.6) makes the target UNDECIDED
HEAT_MAX_C = 88.0  # the highest package temperature of a run without throttle in humem-ops#480 (ab396-r2, 2026-11-22)


def load_plan():
    spec = importlib.util.spec_from_file_location("pilot_plan", os.path.join(HERE, "plan.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


plan = load_plan()


def refuse(msg):
    """Exit code 2 with the reason on standard error (the input is refused; an empty or unbalanced input is never read as a pass)."""
    print(msg, file=sys.stderr)
    sys.exit(2)


# ---- small linear algebra and statistics (stdlib only) ---------------------------------------------------------------------------------------------------


def mat_inv(a):
    n = len(a)
    m = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(a)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[piv][c]) < 1e-9:
            return None
        m[c], m[piv] = m[piv], m[c]
        d = m[c][c]
        m[c] = [v / d for v in m[c]]
        for r in range(n):
            if r != c and m[r][c] != 0.0:
                f = m[r][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c])]
    return [row[n:] for row in m]


def t_pdf(x, df):
    return math.exp(math.lgamma((df + 1) / 2) - math.lgamma(df / 2)) / math.sqrt(df * math.pi) * (1 + x * x / df) ** (-(df + 1) / 2)


def t_cdf(x, df, steps=2000):
    h = x / steps
    s = t_pdf(0, df) + t_pdf(x, df)
    for i in range(1, steps):
        s += (4 if i % 2 else 2) * t_pdf(i * h, df)
    return 0.5 + s * h / 3


@functools.lru_cache(maxsize=None)
def t_ppf(q, df):
    lo, hi = 0.0, 400.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if t_cdf(mid, df) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def percentile(sorted_vals, q):
    k = (len(sorted_vals) - 1) * q
    f = math.floor(k)
    c = min(f + 1, len(sorted_vals) - 1)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def median(v):
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def ols(x, y, boot, seed):
    """Fit y = X b. Returns None when X is not of full column rank or has no residual degrees of freedom."""
    n, p = len(x), len(x[0])
    if n - p < 1:
        return None
    xtx = [[sum(x[i][a] * x[i][b] for i in range(n)) for b in range(p)] for a in range(p)]
    a_inv = mat_inv(xtx)
    if a_inv is None:
        return None
    xty = [sum(x[i][a] * y[i] for i in range(n)) for a in range(p)]
    beta = [sum(a_inv[a][b] * xty[b] for b in range(p)) for a in range(p)]
    e = [y[i] - sum(x[i][a] * beta[a] for a in range(p)) for i in range(n)]
    h = [sum(x[i][a] * a_inv[a][b] * x[i][b] for a in range(p) for b in range(p)) for i in range(n)]
    df = n - p
    tq = t_ppf(0.975, df)
    meat = [[0.0] * p for _ in range(p)]
    hc3 = all(1 - hh > 1e-6 for hh in h)
    for i in range(n):
        w = (e[i] / (1 - h[i])) ** 2 if hc3 else sum(v * v for v in e) / df
        for a in range(p):
            for b in range(p):
                meat[a][b] += w * x[i][a] * x[i][b]
    v = [[sum(a_inv[a][c] * meat[c][d] * a_inv[d][b] for c in range(p) for d in range(p)) for b in range(p)] for a in range(p)]
    se = [math.sqrt(max(v[j][j], 0.0)) for j in range(p)]
    t_int = [(beta[j] - tq * se[j], beta[j] + tq * se[j]) for j in range(p)]
    rc = [e[i] / math.sqrt(1 - h[i]) for i in range(n)] if all(1 - hh > 1e-6 for hh in h) else e[:]
    mrc = sum(rc) / n
    rc = [r - mrc for r in rc]
    proj = [[sum(a_inv[a][b] * x[i][b] for b in range(p)) for i in range(n)] for a in range(p)]
    rng = random.Random(seed)
    draws = [[] for _ in range(p)]
    for _ in range(boot):
        es = rng.choices(rc, k=n)
        for a in range(p):
            draws[a].append(beta[a] + sum(proj[a][i] * es[i] for i in range(n)))
    b_int = []
    for a in range(p):
        d = sorted(draws[a])
        b_int.append((percentile(d, 0.025), percentile(d, 0.975)))
    wide = [(min(t_int[j][0], b_int[j][0]), max(t_int[j][1], b_int[j][1])) for j in range(p)]
    return {"beta": beta, "se_hc3": se, "t_interval": t_int, "boot_interval": b_int, "interval": wide, "df": df, "n": n, "p": p, "sigma": math.sqrt(sum(r * r for r in e) / df), "hc3": hc3}


# ---- rows and validity -----------------------------------------------------------------------------------------------------------------------------------


def load_rows(dirs):
    rows, bad, dup = {}, 0, []
    files = []
    for d in dirs:
        files += sorted(glob.glob(os.path.join(d, "**", "rows.jsonl"), recursive=True))
    for f in files:
        for line in open(f, encoding="utf-8"):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                key = (r["unit"], r["lane"])
            except (ValueError, KeyError):
                bad += 1
                continue
            if key in rows:
                old = rows[key]
                if old.get("status") == "failed" and r.get("status") != "failed":
                    pass  # an earlier failed row (barrier-abort, interrupted) is permanent and kept in the files; the row of the run that went on is read
                elif r.get("status") == "failed" and old.get("status") != "failed":
                    continue
                else:
                    dup.append(key)
            rows[key] = r
    return rows, bad, dup, files


def unit_validity(u, rows, data):
    """(valid, reasons) of a unit's target run."""
    lane = u["position"]
    r = rows.get((u["id"], lane))
    if r is None:
        return False, ["missing"]
    why = []
    if r.get("status") != "ok":
        why.append(f"status {r.get('status')}: {r.get('reason')}")
    if r.get("figure") is None or not (r.get("figure") or 0) > 0:
        why.append("no figure")
    if data and r.get("shortened"):
        why.append("shortened")
    if data and r.get("test_hooks"):
        why.append("made with the test hooks of the smoke")
    if r.get("cpus_allowed") != r.get("cpus_expected") or r.get("cpus_allowed") is None:
        why.append("not pinned as asked")
    tm, wall = r.get("throttle_ms"), r.get("wall_s")
    if tm is None:
        why.append("throttle not read")
    elif wall and tm > THROTTLE_SHARE * wall * 1000:
        why.append(f"throttled {tm} ms of {wall * 1000:.0f} ms")
    if r.get("gate_ok") is not True:
        why.append("start gate not held")
    if r.get("t_start") and r.get("t_end") and u["kind"] in ("perm",):
        dur = r["t_end"] - r["t_start"]
        for l2, role in plan.lane_roles(u).items():
            if role in ("target", "none"):
                continue
            n = rows.get((u["id"], l2))
            if n is None or n.get("t_start") is None or n.get("t_end") is None or n.get("status") not in ("ok", "partial"):
                why.append(f"neighbour on {l2} missing")
                continue
            cover = max(0.0, min(r["t_end"], n["t_end"]) - max(r["t_start"], n["t_start"])) / dur if dur > 0 else 0.0
            if cover < COVER_MIN:
                why.append(f"neighbour on {l2} covered {cover:.2f}")
    return (not why), why


def fmt(v, p=4):
    return "-" if v is None else f"{v:.{p}g}"


# ---- per target ------------------------------------------------------------------------------------------------------------------------------------------


def design_columns(order, tgt):
    levels = [l for l in order["levels"] if l != "idle"]
    planned = [u for u in order["units"] if u["kind"] == "perm" and u["target"] == tgt["id"]]
    positions = sorted({u["position"] for u in planned})
    return levels, positions, planned


def build_x(runs, levels, positions, n_planned_rank):
    x, y = [], []
    for r in runs:
        row = [1.0] + [1.0 if r["level"] == l else 0.0 for l in levels]
        if len(positions) > 1:
            last = positions[-1]
            row += [(-1.0 if r["position"] == last else (1.0 if r["position"] == p else 0.0)) for p in positions[:-1]]
        row += [(r["rank"] - (n_planned_rank - 1) / 2.0) / n_planned_rank]
        x.append(row)
        y.append(math.log(r["figure"]))
    return x, y


def analyse_target(order, tgt, units_all, rows, boot, interim):
    data = order["data"]
    res = {"target": tgt["id"], "workload": tgt["workload"], "class": tgt["cls"], "standin": bool(tgt.get("probe")), "reasons": [], "invalid": [], "notes": []}
    levels, positions, planned = design_columns(order, tgt)
    if interim:
        planned = [u for u in planned if u["stage"] == "s2"]
    replaced = {u["replaces"] for u in units_all if u.get("replaces")}
    rank_of = {u["id"]: i for i, u in enumerate(sorted([u for u in units_all if u["kind"] == "perm" and u["target"] == tgt["id"]], key=lambda u: u["idx"]))}
    n_all = sum(1 for u in order["units"] if u["kind"] == "perm" and u["target"] == tgt["id"])
    # permuted runs, replacements taking the place of the invalid run they replace
    perm_runs, n_invalid = [], 0
    for u in [u for u in units_all if u["kind"] == "perm" and u["target"] == tgt["id"]]:
        if interim and u["stage"] != "s2":
            continue
        ok, why = unit_validity(u, rows, data)
        if u["id"] in replaced:
            if not ok:
                res["invalid"].append({"unit": u["id"], "why": why, "replaced": True})
            continue
        if not ok:
            n_invalid += 1
            res["invalid"].append({"unit": u["id"], "why": why, "replaced": False})
            continue
        r = rows[(u["id"], u["position"])]
        perm_runs.append({"unit": u["id"], "level": u["level"], "position": u["position"], "figure": r["figure"], "rank": rank_of[u["id"]]})
    res["n_planned"], res["n_valid"], res["n_invalid"] = len(planned), len(perm_runs), n_invalid
    # references
    ref = {}
    for kind, name in (("solo", "full width"), ("alone2", "two cpus")):
        sets = {}
        for u in [u for u in units_all if u["kind"] == kind and u["target"] == tgt["id"]]:
            ok, why = unit_validity(u, rows, data)
            if u["id"] in replaced:
                if not ok:
                    res["invalid"].append({"unit": u["id"], "why": why, "replaced": True})
                continue
            if not ok:
                res["invalid"].append({"unit": u["id"], "why": why, "replaced": False})
                continue
            sets.setdefault(u["set"], []).append(rows[(u["id"], u["position"])]["figure"])
        ref[kind] = {"name": name, "sets": sets}
        s_st, s_en = sets.get("start", []), sets.get("end", [])
        both = s_st + s_en
        ref[kind]["median"] = median(both) if both else None
        ref[kind]["median_start"] = median(s_st) if s_st else None
        ref[kind]["median_end"] = median(s_en) if s_en else None
        ref[kind]["mid"] = median(sets["mid"]) if sets.get("mid") else None
        ref[kind]["spread"] = {k: (max(v) / min(v) - 1.0) for k, v in sets.items() if len(v) >= 2}
        ref[kind]["n_valid"] = len(both)
    res["reference"] = ref
    solo = ref["solo"]
    ref_why = []
    if data and not interim:
        if len(solo["sets"].get("start", [])) < 2 or len(solo["sets"].get("end", [])) < 2:
            ref_why.append("a solo set has fewer than 2 valid runs")
        if any(v > BAND for v in solo["spread"].values()):
            ref_why.append("a set of solo runs spreads by more than 3 percent: " + ", ".join(f"{k} {v:.3f}" for k, v in solo["spread"].items() if v > BAND))
        if solo["median_start"] and solo["median_end"] and abs(solo["median_end"] / solo["median_start"] - 1) > BAND:
            ref_why.append(f"the start and the end median of the solo runs differ by {abs(solo['median_end'] / solo['median_start'] - 1):.3f}")
    res["reference_problems"] = ref_why
    if solo["mid"] and solo["median"]:
        res["notes"].append(f"middle anchor at full width over the reference: {solo['mid'] / solo['median']:.4f}")
    if ref["alone2"]["mid"] and ref["alone2"]["median"]:
        res["notes"].append(f"middle anchor on two cpus over the reference: {ref['alone2']['mid'] / ref['alone2']['median']:.4f}")
    if ref["alone2"]["median"] and solo["median"]:
        res["width_ratio"] = ref["alone2"]["median"] / solo["median"]
    # design as realised
    probs = plan.check_design([{"kind": "perm", "target": tgt["id"], "level": r["level"], "position": r["position"], "idx": r["rank"]} for r in perm_runs], [tgt], order["levels"], order["lanes_proven"],
                              expect_equal=False, corr_max=REALISED_CORR_MAX if (data and len(perm_runs) >= 8) else None)
    res["design_problems"] = probs
    fatal = [p for p in probs if "confounded" in p]
    # interim: early fail
    if interim:
        idle = [r["figure"] for r in perm_runs if r["level"] == "idle"]
        res["interim"] = {"idle_runs": len(idle), "idle_median": median(idle) if idle else None}
        if len(idle) >= 3 and solo["median"] and abs(median(idle) / solo["median"] - 1) > EARLY_FAIL:
            res["verdict"] = "EARLY-FAIL"
            res["reasons"].append(f"idle median over solo median is {median(idle) / solo['median']:.4f}")
        else:
            res["verdict"] = "NO-EARLY-FAIL"
        return res
    # model
    present = [l for l in levels if any(r["level"] == l for r in perm_runs)]
    missing_levels = [l for l in levels if l not in present]
    x, y = build_x(perm_runs, present, positions, n_all)
    fit = ols(x, y, boot, 1) if perm_runs and any(r["level"] == "idle" for r in perm_runs) else None
    names = ["b0"] + present + ([f"pos:{p}" for p in positions[:-1]] if len(positions) > 1 else []) + ["drift"]
    if fit is None:
        res["verdict"] = "UNDECIDED"
        res["reasons"].append("the model cannot be identified from the valid runs")
        res["fit"] = None
        return res
    res["fit"] = {"names": names, "beta": fit["beta"], "interval": fit["interval"], "t_interval": fit["t_interval"], "boot_interval": fit["boot_interval"], "se_hc3": fit["se_hc3"],
                  "df": fit["df"], "n": fit["n"], "sigma": fit["sigma"], "hc3": fit["hc3"]}
    b0, (lo, hi) = fit["beta"][0], fit["interval"][0]
    idle_fig = math.exp(b0)
    res["idle_figure"] = idle_fig
    res["idle_interval"] = (math.exp(lo), math.exp(hi))
    res["half_width"] = (math.exp(hi) - math.exp(lo)) / 2 / idle_fig
    res["interference"] = {l: {"factor": math.exp(fit["beta"][1 + i]), "interval": (math.exp(fit["interval"][1 + i][0]), math.exp(fit["interval"][1 + i][1]))} for i, l in enumerate(present)}
    if len(positions) > 1:
        off = 1 + len(present)
        pe = {p: fit["beta"][off + i] for i, p in enumerate(positions[:-1])}
        pe[positions[-1]] = -sum(pe.values())
        res["position_effects"] = {p: math.exp(v) for p, v in pe.items()}
    res["drift_over_pilot"] = math.exp(fit["beta"][-1])
    if solo["median"]:
        res["ratio_full"] = idle_fig / solo["median"]
        res["ratio_full_interval"] = (math.exp(lo) / solo["median"], math.exp(hi) / solo["median"])
    if ref["alone2"]["median"]:
        res["ratio_two_cpus"] = idle_fig / ref["alone2"]["median"]
    if not data:
        res["verdict"] = "SMOKE"
        res["reasons"].append("a smoke leg: shortened runs, no verdict")
        return res
    max_bad = math.floor(MAX_INVALID_SHARE * n_all)
    undec = list(ref_why)
    if n_invalid > max_bad:
        undec.append(f"{n_invalid} of {n_all} planned permuted runs are invalid or missing (at most {max_bad})")
    if fatal:
        undec.extend(fatal)
    if missing_levels:
        undec.append("no valid run at level " + ", ".join(missing_levels))
    if "ratio_full" not in res:
        undec.append("no solo reference")
    if undec:
        res["verdict"] = "UNDECIDED"
        res["reasons"] = undec
        return res
    r_lo, r_hi = res["ratio_full_interval"]
    if abs(res["ratio_full"] - 1) <= BAND and res["half_width"] <= BAND:
        res["verdict"] = "PASS"
    elif r_hi < 1 - BAND or r_lo > 1 + BAND:
        res["verdict"] = "FAIL"
    else:
        res["verdict"] = "UNDECIDED"
        res["reasons"].append("the interval is neither inside nor wholly outside the 3 percent band")
    return res


def class_verdicts(results):
    out = {}
    for r in results:
        out.setdefault(r["class"] or "none", []).append(r)
    verdict = {}
    for k, rs in out.items():
        vs = [r["verdict"] for r in rs]
        stand = all(r["standin"] for r in rs)
        if any(v == "FAIL" for v in vs):
            verdict[k] = "PROBE-FAIL" if stand else "FAIL"
        elif all(v == "PASS" for v in vs):
            verdict[k] = "PROBE-PASS" if stand else ("PASS" if len(rs) >= 2 else "UNDECIDED (fewer than 2 real cells)")
        else:
            verdict[k] = "UNDECIDED"
    return verdict


# ---- heat leg --------------------------------------------------------------------------------------------------------------------------------------------


def analyse_heat(order, rows):
    u = order["units"][0]
    lines, ok_all, res = [], True, []
    for lane in plan.LANES:
        r = rows.get((u["id"], lane))
        if r is None or r.get("status") not in ("ok", "partial") or r.get("throttle_ms") is None or not r.get("wall_s"):
            res.append({"lane": lane, "problem": "no usable row"})
            ok_all = False
            continue
        share = r["throttle_ms"] / (r["wall_s"] * 1000)
        good = share <= THROTTLE_SHARE and (r.get("pkg_c_max") or 999) <= HEAT_MAX_C
        ok_all = ok_all and good
        res.append({"lane": lane, "wall_s": r["wall_s"], "throttle_ms": r["throttle_ms"], "share": share, "pkg_c_start": r.get("pkg_c_start"), "pkg_c_max": r.get("pkg_c_max"), "good": good})
    verdict = "HEAT-PASS" if ok_all else "HEAT-FAIL"
    for x in res:
        lines.append("  " + (f"{x['lane']}: no usable row" if "problem" in x else f"{x['lane']}: wall {x['wall_s']:.0f} s, throttled {x['throttle_ms']} ms ({x['share'] * 100:.2f} percent), package {fmt(x['pkg_c_start'], 3)} C at start, {fmt(x['pkg_c_max'], 3)} C at most, {'ok' if x['good'] else 'NOT ok'}"))
    return verdict, lines, res


# ---- report ----------------------------------------------------------------------------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", required=True)
    ap.add_argument("--topup")
    ap.add_argument("--rows", nargs="+", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--interim", action="store_true")
    ap.add_argument("--boot", type=int, default=10000)
    a = ap.parse_args()
    order = json.load(open(a.order))
    units_all = list(order["units"])
    if a.topup:
        tu = json.load(open(a.topup))
        if tu["leg"] != order["leg"]:
            refuse("REFUSED: the top-up is of another leg")
        units_all += tu["units"]
    rows, bad, dup, files = load_rows(a.rows)
    if bad or dup or not rows:
        refuse(f"REFUSED: {bad} malformed lines, {len(dup)} repeated rows {dup[:3]}, {len(rows)} rows in {len(files)} files")
    if any(r.get("leg") not in (None, order["leg"]) for r in rows.values()):
        refuse("REFUSED: rows of another leg")
    os.makedirs(a.out_dir, exist_ok=True)
    out = [f"analysis of leg {order['leg']}: {order['title']}", f"order seed {order['seed']} salt {order['salt']}, plan.py sha256 {order['plan_py_sha256'][:16]}, analyze.py sha256 {hashlib.sha256(open(__file__, 'rb').read()).hexdigest()[:16]}",
           f"{len(rows)} rows from {len(files)} files, {len(units_all)} units" + (" (INTERIM, first half only)" if a.interim else "")]
    if order["units"][0]["kind"] == "heat":
        verdict, lines, res = analyse_heat(order, rows)
        out += [f"heat verdict: {verdict} (rule: throttled at most {THROTTLE_SHARE * 100:g} percent of the run and the package at most {HEAT_MAX_C:g} C, each lane)"] + lines
        open(os.path.join(a.out_dir, "analysis.txt"), "w").write("\n".join(out) + "\n")
        json.dump({"verdict": verdict, "lanes": res}, open(os.path.join(a.out_dir, "analysis.json"), "w"), indent=1, sort_keys=True)
        print("\n".join(out))
        return
    targets = order["targets"]
    if order["data"]:
        probs = plan.check_design(order["units"], targets, order["levels"], order["lanes_proven"], corr_max=order["corr_max"])
        if probs:
            refuse("REFUSED: the order is not a balanced design:\n  " + "\n  ".join(probs))
    results = [analyse_target(order, t, units_all, rows, a.boot, a.interim) for t in targets]
    invalid_ids = sorted({x["unit"] for r in results for x in r["invalid"] if not x["replaced"]} | {u["id"] for u in order["units"] if (u["id"], u["position"]) not in rows and u["id"] not in {x["replaces"] for x in units_all if x.get("replaces")}})
    for r in results:
        out.append("")
        out.append(f"target {r['target']}  (class {r['class']}, {'STAND-IN probe' if r['standin'] else 'real cell'})  VERDICT {r['verdict']}")
        for w in r["reasons"] + r.get("reference_problems", []):
            out.append("  reason: " + w)
        out.append(f"  permuted runs: planned {r['n_planned']}, valid {r['n_valid']}, invalid or missing {r['n_invalid']}")
        for x in r["invalid"]:
            out.append(f"    invalid {x['unit']}{' (replaced)' if x['replaced'] else ''}: {'; '.join(x['why'])}")
        ref = r["reference"]
        for kind in ("solo", "alone2"):
            k = ref[kind]
            out.append(f"  reference {k['name']}: median {fmt(k['median'], 7)} from {k['n_valid']} valid runs (start {fmt(k['median_start'], 7)}, end {fmt(k['median_end'], 7)}, middle {fmt(k['mid'], 7)}); spread by set {', '.join(f'{s} {v:.4f}' for s, v in k['spread'].items()) or '-'}")
        if "width_ratio" in r:
            out.append(f"  lane-width effect (two cpus alone over full width): {r['width_ratio']:.4f}")
        for n in r["notes"]:
            out.append("  " + n)
        for p in r["design_problems"]:
            out.append("  design as realised: " + p)
        if r.get("interim"):
            out.append(f"  interim: {r['interim']['idle_runs']} idle runs, median {fmt(r['interim']['idle_median'], 7)}")
        if r.get("fit"):
            f = r["fit"]
            out.append(f"  model: n {f['n']}, df {f['df']}, residual sd {f['sigma']:.4f} (log scale), {'HC3' if f['hc3'] else 'classical'} errors; interval = the wider of t and bootstrap")
            out.append(f"  figure with an idle neighbour: {r['idle_figure']:.7g} [{r['idle_interval'][0]:.7g}, {r['idle_interval'][1]:.7g}], half-width {r['half_width'] * 100:.2f} percent of the figure")
            if "ratio_full" in r:
                out.append(f"  over the solo figure: {r['ratio_full']:.4f} [{r['ratio_full_interval'][0]:.4f}, {r['ratio_full_interval'][1]:.4f}]; over the two-cpu alone figure: {r.get('ratio_two_cpus', float('nan')):.4f}")
            for l, v in r["interference"].items():
                out.append(f"  neighbour effect {l}: x{v['factor']:.4f} [{v['interval'][0]:.4f}, {v['interval'][1]:.4f}]")
            if "position_effects" in r:
                out.append("  lane position effects: " + ", ".join(f"{p} x{v:.4f}" for p, v in r["position_effects"].items()))
            out.append(f"  drift over the pilot: x{r['drift_over_pilot']:.4f}")
    cv = class_verdicts(results) if order["data"] and not a.interim else {}
    if cv:
        out.append("")
        out.append("class verdicts: " + "; ".join(f"{k}: {v}" for k, v in cv.items()))
    out.append("")
    out.append(f"units to replace in the top-up stage (invalid or missing, not yet replaced): {len(invalid_ids)}")
    text = "\n".join(out) + "\n"
    open(os.path.join(a.out_dir, "analysis.txt"), "w").write(text)
    json.dump({"leg": order["leg"], "results": results, "classes": cv, "invalid_units": invalid_ids}, open(os.path.join(a.out_dir, "analysis.json"), "w"), indent=1, sort_keys=True, default=str)
    json.dump(invalid_ids, open(os.path.join(a.out_dir, "invalid.json"), "w"))
    print(text)


if __name__ == "__main__":
    main()
