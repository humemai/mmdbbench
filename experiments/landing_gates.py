#!/usr/bin/env python3
"""Landing gates G1 to G3: a staged cell without rows, a dropped row and an unexplained collision stop the landing (humemai/mmdbbench#78, refs #52).

Round 2 lost all 18 GAV-on rows of l2 olap (#77) without a word, and every gate passed: they read what is in the store, not what should be in it.

  G1 roster_problems   the frozen rows against the roster of the 2611 pass (roster_2611.json, generated from make_2611_stages.stage_cells, with its sha256): every staged cell
                       (lane, scale, workload, backend, class, arm, build) has at least min(3, max rep) clean repetitions or a declared reason (an error or censored row); a cell with
                       no row is MISSING, a short one SHORT, and rows of a cell that is not in the roster are listed as ORPHAN. Runs as the eighth gate of refresh_web_page.py.
  G2 drop_problems     what a merge discards (merge_campaign, merge_fourarm_rows): each drop is reported with its key and reason, written to dropped_rows.jsonl beside the store, and
                       REFUSED when the two rows differ in gav, backend_arm, arcadedb_http_client, arcadedb_client_wire, durability_class, engine_backend, scale or workload.
  G3 collision_problems  groups of rows with one (lane, backend, workload, scale, rep, engine_backend, run_id): counted and printed, refused unless every group differs only in an arm
                       field the merge key includes (gav, backend_arm) or in the fields of a rerun or retry (wheel, version, error).
  page_problems        the page's table cells against the roster (the verifier chain): a staged cell the freeze holds but the page neither prints nor declares.

    uv run --no-project python landing_gates.py                    # G1 and G3 on the canonical frozen rows (the gate refresh_web_page.py runs)
    uv run --no-project python landing_gates.py roster-gen [--out roster_2611.json]
    uv run --no-project python landing_gates.py page --payload P.json --freeze runs_paper.csv     # roster against the page's tables
"""
import argparse
import collections
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROSTER = HERE / "roster_2611.json"
PENDING = HERE / "roster_pending.json"
IDENTITY_FIELDS = ("gav", "backend_arm", "arcadedb_http_client", "arcadedb_client_wire", "durability_class", "engine_backend", "scale", "workload")
COARSE_KEY = ("lane", "backend", "workload", "scale", "rep", "engine_backend", "run_id")
ARM_FIELDS = ("gav", "backend_arm")
RERUN_FIELDS = ("wheel_label", "wheel_name", "wheel_sha256", "engine_version", "ts_utc", "error", "rc", "timed_ts_utc", "timed_wheel", "build_figures_wheel",
                "build_figures_wheel_sha256", "build_figures_run_id", "build_figures_ts_utc", "build_figures_replaced")
# the landing's lane -> page table of the verifier step (export_web._TABLE_LANE says the same)
TABLE_OF = {("l2", "oltp"): "l2", ("l2", "olap"): "l2olap", ("e2", "hybrid"): "e2", ("e2", "atomicity"): "e2atom", ("l1tpc", "oltp"): "docs_oltp", ("l1tpc", "olap"): "docs_olap"}


def _gav_off(r):
    return r.get("gav") is False or str(r.get("gav")) == "False" or r.get("backend_arm") == "nogav"


def _norm(f, r):
    v = r.get(f)
    if f == "gav":
        return "off" if _gav_off(r) else "on"
    if f == "durability_class":
        return str(v or "relaxed")
    return "" if v in (None, "") else str(v)


def identity(r):
    return tuple((f, _norm(f, r)) for f in IDENTITY_FIELDS)


def differing(rs, fields):
    return [f for f in fields if len({_norm(f, r) if f in IDENTITY_FIELDS else str(r.get(f)) for r in rs}) > 1]


def _rep(r):
    try:
        return int(float(r.get("rep")))
    except (TypeError, ValueError):
        return None


def _clean(r):
    return not r.get("error") and str(r.get("rc") if r.get("rc") not in (None, "") else 0) in ("0", "0.0")


def _explains(r):
    """A row that says why its cell has fewer than three clean repetitions."""
    if r.get("error") or r.get("outcome") or str(r.get("oom_killed")).lower() == "true":
        return True
    return any(str(v).lower() == "true" for k, v in r.items() if str(k).endswith("censored")) or any(str(v).startswith("unexpressible") for v in r.values())


# ------------------------------------------------------------------------------------------------ G2
def drop_problems(pairs):
    """pairs: [(dropped_row, kept_row, reason)] -> sentences for the drops whose two rows differ in an identity field (empty: every drop is a retry of one row)."""
    out = []
    for d, k, why in pairs:
        diff = differing([d, k], IDENTITY_FIELDS)
        if diff:
            out.append(f"{why}: the dropped row ({d.get('run_id')}, ts {d.get('ts_utc')}) and the kept one ({k.get('run_id')}, ts {k.get('ts_utc')}) differ in {', '.join(diff)}")
    return out


def drop_record(d, k, why):
    return {"reason": why, "run_id": d.get("run_id"), "key": [str(d.get(x)) for x in COARSE_KEY], "dropped_ts_utc": d.get("ts_utc"), "kept_ts_utc": k.get("ts_utc"),
            "identity": dict(identity(d)), "differs_from_kept_in": differing([d, k], IDENTITY_FIELDS)}


def write_dropped(path, records):
    Path(path).write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8")
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ------------------------------------------------------------------------------------------------ G3
def collision_groups(rows):
    g = collections.defaultdict(list)
    for r in rows:
        g[tuple(str(r.get(k)) for k in COARSE_KEY)].append(r)
    return {k: v for k, v in g.items() if len(v) > 1}


def collision_problems(rows):
    """(sentences, counts by kind): a group is `arms` (differs in gav or backend_arm), `rerun` (differs in the fields of a rerun or retry) or refused."""
    probs, kinds = [], collections.Counter()
    for k, rs in sorted(collision_groups(rows).items()):
        diff = differing(rs, IDENTITY_FIELDS + RERUN_FIELDS)
        other = [f for f in diff if f in IDENTITY_FIELDS and f not in ARM_FIELDS]
        if other:
            probs.append(f"{len(rs)} rows share {dict(zip(COARSE_KEY, k))} and differ in {', '.join(other)}, which the merge key does not include")
            kinds["refused"] += 1
        elif not [f for f in diff if f != "ts_utc"]:
            probs.append(f"{len(rs)} rows share {dict(zip(COARSE_KEY, k))} and differ in nothing but the time: a duplicate")
            kinds["refused"] += 1
        else:
            kinds["arms" if any(f in ARM_FIELDS for f in diff) else "rerun"] += 1
    return probs, dict(kinds)


# ------------------------------------------------------------------------------------------------ G1
_CELL_KEYS = ("lane", "scale", "workload", "backend", "cls", "arm")


def _roster_split():
    """(inside, outside, dropped): the cells of make_2611_stages.STAGES split by the generator's own rules. OUTSIDE arms are not in the subset at all; the arms the paper-2611
    PROFILE drops (drop_reason: quantized dense arms, Neo4j and Memgraph dense, the second list) are in the subset and left out of the pass in the open, with a reason each."""
    import make_2611_stages as M
    inside, outside, dropped = set(), set(), {}
    for spec in M.STAGES:
        for c in M.stage_cells(spec):
            if c.kind != "lane":
                continue
            key = (c.lane, c.scale, c.workload, c.backend, c.cls, c.arm)
            why = M.drop_reason(M.DEFAULT_PROFILE, c.lane, c.backend)
            if M.is_outside(c.backend):
                outside.add(key)
            elif why:
                dropped[key] = why
            else:
                inside.add(key)
    return inside, outside, dropped


def roster_cells():
    """(cells, outside_cells): the staged cells of the paper pass, and the cells of the registered arms the pass leaves out by design (make_2611_stages.OUTSIDE:
    no stage script mentions them and the mini holds no row for them). The cells the paper-2611 profile drops are neither: see roster_dropped."""
    inside, outside, _dropped = _roster_split()
    f = lambda cs: [dict(zip(_CELL_KEYS, c)) for c in sorted(cs)]
    return f(inside), f(outside)


def roster_dropped():
    """The cells the default profile (make_2611_stages.DEFAULT_PROFILE) drops, DERIVED from the generator (drop_reason), each with its reason, and the rule behind each reason with
    its source line. They are not staged cells of the paper pass, so the gate does not owe them a row."""
    import ast
    import make_2611_stages as M
    _inside, _outside, dropped = _roster_split()
    line = next(n.lineno for n in ast.walk(ast.parse(Path(M.__file__).read_text(encoding="utf-8")))
                if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "DROP_WHY" for t in n.targets))
    reasons = sorted(set(dropped.values()))
    return {"profile": M.DEFAULT_PROFILE,
            "rules": {w: {"why": M.DROP_WHY[w], "source": f"experiments/make_2611_stages.py:{line}"} for w in reasons},
            "cells": [dict(zip(_CELL_KEYS, k), reason=dropped[k]) for k in sorted(dropped)]}


def _outside_rule():
    import ast
    import make_2611_stages as M
    line = next(n.lineno for n in ast.walk(ast.parse(Path(M.__file__).read_text(encoding="utf-8")))
                if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "OUTSIDE" for t in n.targets))
    return {"rule": "registered arms that are not in the subset of the paper pass (make_2611_stages.OUTSIDE)", "prefixes": list(M.OUTSIDE),
            "source": f"experiments/make_2611_stages.py:{line}"}


def _sha(cells, outside, dropped=None):
    doc = {"cells": cells, "outside_cells": outside}
    if dropped:
        doc["profile_dropped"] = dropped
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()


def roster_doc():
    cells, outside = roster_cells()
    dropped = roster_dropped()
    return {"cells": cells, "outside": _outside_rule(), "outside_cells": outside, "profile_dropped": dropped, "cells_sha256": _sha(cells, outside, dropped),
            "generated_by": "landing_gates.py roster-gen (make_2611_stages.STAGES, stage_cells, drop_reason)"}


def outside_section(roster):
    """Lines for the cells outside the profile by design: printed, never a failure."""
    out = roster["outside"]
    by = collections.Counter(c["backend"] for c in roster["outside_cells"])
    return [f"  outside the profile (by design, source: {out['source']}): {len(roster['outside_cells'])} cell(s) of " + ", ".join(f"{b} {n}" for b, n in sorted(by.items()))]


def dropped_section(roster):
    """Lines for the cells the paper-2611 profile drops: printed with their reason and source line, never a failure."""
    d = roster.get("profile_dropped") or {}
    out = []
    for why, rule in sorted((d.get("rules") or {}).items()):
        cs = [c for c in d.get("cells", []) if c["reason"] == why]
        out.append(f"  dropped by the {d.get('profile')} profile ({why}; source: {rule['source']}): {len(cs)} cell(s) of " + ", ".join(sorted({c["backend"] for c in cs})))
    return out


def load_error_rows(results, lanes=None):
    """The rows of the store (results/runs.jsonl) of the publishing instrument that are NOT clean (an error, a timeout, a non-zero rc): the freeze skips failed cells, so the frozen
    rows cannot say why a staged cell has none. Empty when the store is absent."""
    import publish_instrument
    path = Path(results) / "runs.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if str(r.get("instrument") or "") == publish_instrument.PUBLISH_INSTRUMENT and not _clean(r) and (not lanes or r.get("lane") in lanes):
            out.append(r)
    return out


def _cap_rule_skip(lane, scale, workload, backend, cls, arm, b, errs):
    """The scale below, in the lane's chain, at which the arm-cell timed out: the cap rule (DECISIONS #188) censors the arm at every larger scale and does not run it there."""
    import cap_rule
    for small in cap_rule.smaller_scales(lane, scale):
        for r in errs.get((lane, small, workload, backend, cls, arm, b), []):
            if str(r.get("error") or "").startswith("timeout"):
                return small
    return None


def load_pending(path=PENDING):
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else []


def load_roster(path=ROSTER):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if _sha(doc["cells"], doc["outside_cells"], doc.get("profile_dropped")) != doc["cells_sha256"]:
        raise SystemExit(f"REFUSING: {path} does not match its own sha256; regenerate it with landing_gates.py roster-gen")
    return doc


def off_page_arms():
    """The backend keys export_web.OFF_PAGE_ARMS keeps off the result tables (an ablation that stays in the rows), read from its source without importing it."""
    import ast
    tree = ast.parse((HERE / "export_web.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "OFF_PAGE_ARMS" for t in node.targets) and isinstance(node.value, ast.Dict):
            return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    return set()


def declared_by_page(payload, c):
    """True when the page says why this staged cell has no row: a declared absence of its arm on its table (censored, withheld, not expressible, not measured) or the arm is
    off the page by name (page_check.OFF_PAGE_ARMS, an ablation that stays in the rows)."""
    import export_web as EW
    label = EW.display_name(c["backend"])
    if c["backend"] in off_page_arms():
        return True
    tid = TABLE_OF.get((c["lane"], c["workload"]))
    for t in payload.get("tables", []):
        if t["id"] == tid:
            return any(str(a.get("backend")).startswith(label) for a in t.get("declared_absences") or [])
    return False


def roster_problems(rows, roster, lanes=None, need=3, payload=None, pending=None, errors=None):
    """(problems, summary): MISSING and SHORT staged cells (unexplained) and ORPHAN cells (rows that are in no roster cell). With the page's payload, a cell the page
    declares absent (declared_by_page) is explained."""
    import arm_identity as AI
    lanes = set(lanes or {c["lane"] for c in roster["cells"]})
    builds = sorted(AI.builds_in(rows)) or [None]
    cells = [c for c in roster["cells"] if c["lane"] in lanes]
    have = collections.defaultdict(list)
    for r in rows:
        if r.get("lane") in lanes:
            have[(r.get("lane"), str(r.get("scale")), r.get("workload"), r.get("backend"), str(r.get("durability_class") or "relaxed"),
                  "nogav" if _gav_off(r) else "", r.get("engine_backend") or None)].append(r)
    max_rep = max([_rep(r) or 0 for r in rows] or [0])
    need = min(need, max_rep) if max_rep else need
    errs = collections.defaultdict(list)       # the store's error rows by cell key: a stated reason, never a repetition
    for r in errors or []:
        errs[(r.get("lane"), str(r.get("scale")), r.get("workload"), r.get("backend"), str(r.get("durability_class") or "relaxed"),
              "nogav" if _gav_off(r) else "", r.get("engine_backend") or None)].append(r)
    probs, ok, short_explained, in_roster = [], 0, 0, set()
    # PENDING (roster_pending.json): a staged cell that was skipped, not run, and is waiting for a rerun. Printed, not a failure, and refused once a row exists for it, so the
    # entry cannot go stale; an entry that names no staged cell is refused too.
    names = {f"{c['lane']}/{c['scale']}/{c['workload']}/{c['backend']}/{c['cls']}" + (f"/{c['arm']}" if c["arm"] else ""): c for c in cells}
    pend = {p["cell"]: p for p in pending or []}
    pending_now = []
    for name in sorted(pend):
        c = names.get(name)
        if c is None:
            probs.append(f"UNKNOWN PENDING {name}: roster_pending.json names a cell that is not a staged cell of the roster")
        elif any(k[:6] == (c["lane"], c["scale"], c["workload"], c["backend"], c["cls"], c["arm"]) for k in have):
            probs.append(f"STALE PENDING {name}: a row exists for the cell now ({pend[name].get('since')}); remove it from roster_pending.json")
        else:
            pending_now.append(name)
    for c in cells:
        if f"{c['lane']}/{c['scale']}/{c['workload']}/{c['backend']}/{c['cls']}" + (f"/{c['arm']}" if c["arm"] else "") in pending_now:
            continue
        bs = builds if c["backend"].startswith("arcadedb") and AI.built({"backend": c["backend"]}) else [None]
        for b in bs:
            key = (c["lane"], c["scale"], c["workload"], c["backend"], c["cls"], c["arm"], b)
            rs = have.get(key, [])
            in_roster.add(key)
            reps = {_rep(r) for r in rs if _clean(r)} - {None}
            label = f"{c['lane']}/{c['scale']}/{c['workload']}/{c['backend']}/{c['cls']}" + (f"/{c['arm']}" if c["arm"] else "") + (f"/{b}" if b else "")
            if len(reps) >= need:
                ok += 1
            elif any(_explains(r) for r in rs) or errs.get(key):
                short_explained += 1
            elif _cap_rule_skip(*key, errs):
                short_explained += 1
            elif payload is not None and declared_by_page(payload, c):
                short_explained += 1
            elif not rs:
                probs.append(f"MISSING {label}: staged, no row")
            else:
                probs.append(f"SHORT {label}: {len(reps)} clean repetition(s) of {need}, no row says why")
    orphans = sorted({k for k in have if k not in in_roster})
    summary = {"roster_cells": len(cells), "complete": ok, "explained_short": short_explained, "unexplained": len(probs), "pending": pending_now, "orphan_cells": len(orphans), "orphans": orphans}
    return probs, summary


# ------------------------------------------------------------------------------------------------ the verifier step
def page_problems(payload, rows, roster, lanes=None):
    """A staged cell the frozen rows hold clean reps for, that no entry of the page's table prints (GAV is in the label of the view arm)."""
    lanes = set(lanes or {w[0] for w in TABLE_OF})
    tables = {t["id"]: t for t in payload.get("tables", [])}
    out = []
    held = {(r.get("lane"), str(r.get("scale")), r.get("workload"), r.get("backend"), "nogav" if _gav_off(r) else "", str(r.get("durability_class") or "relaxed"))
            for r in rows if _clean(r)}
    for c in roster["cells"]:
        tid = TABLE_OF.get((c["lane"], c["workload"]))
        if not tid or c["lane"] not in lanes or tid not in tables or c["cls"] != "relaxed" or c["backend"] in off_page_arms():
            continue
        if (c["lane"], c["scale"], c["workload"], c["backend"], c["arm"], "relaxed") not in held:
            continue
        gav_arm = tid == "l2olap" and c["backend"].startswith("arcadedb")
        printed = [e for e in tables[tid]["entries"] if e.get("backend_key") == c["backend"] and str(e.get("scale")) == c["scale"]
                   and (not gav_arm or (", GAV" in e["backend"] or "(GAV" in e["backend"]) == (c["arm"] == ""))]
        if not printed:
            out.append(f"{tid}: the freeze holds {c['lane']}/{c['scale']}/{c['workload']}/{c['backend']}" + (f"/{c['arm']}" if c["arm"] else "") + ", the page prints no entry for it")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", nargs="?", default="gate", choices=["gate", "roster-gen", "page"])
    ap.add_argument("--out", default=str(ROSTER))
    ap.add_argument("--payload")
    ap.add_argument("--freeze")
    ap.add_argument("--roster", default=str(ROSTER))
    a = ap.parse_args(argv)
    if a.mode == "roster-gen":
        doc = roster_doc()
        Path(a.out).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"roster: {len(doc['cells'])} staged cells, sha256 {doc['cells_sha256']}")
        return 0
    roster = load_roster(a.roster)
    lanes = {x.strip() for x in os.environ.get("BENCH_ONLY_LANES", "").split(",") if x.strip()} or None
    if a.mode == "page":
        import csv
        rows = list(csv.DictReader(open(a.freeze, newline="", encoding="utf-8")))
        probs = page_problems(json.load(open(a.payload, encoding="utf-8")), rows, roster, lanes)
        for p in probs:
            print("  " + p)
        print(f"roster against the page: {len(probs)} staged cell(s) the freeze holds and the page does not print")
        return 1 if probs else 0
    import make_paper_tables as M
    rows = M.load_canonical()
    exported = Path(M.RESULTS) / "web_benchmarks.json"
    payload = json.load(open(exported, encoding="utf-8")) if exported.exists() else None
    pending = load_pending()
    errors = load_error_rows(M.RESULTS, lanes)
    probs, summ = roster_problems(rows, roster, lanes, payload=payload, pending=pending, errors=errors)
    cprobs, kinds = collision_problems(rows)
    for p in probs + cprobs:
        print("  " + p)
    for name in summ["pending"]:
        pe = next(p for p in pending if p["cell"] == name)
        print(f"  PENDING {name}: {pe['reason']} ({pe['ref']}; {pe['since']})")
    print("\n".join(outside_section(roster)))
    for line in dropped_section(roster):
        print(line)
    print(f"  roster {roster['cells_sha256'][:12]}: {summ['roster_cells']} staged cells, {summ['complete']} complete, {summ['explained_short']} short with a stated reason, "
          f"{summ['unexplained']} unexplained, {len(summ['pending'])} pending, {summ['orphan_cells']} orphan cell(s); collisions {kinds or 'none'}")
    return 1 if probs or cprobs else 0


if __name__ == "__main__":
    sys.exit(main())
