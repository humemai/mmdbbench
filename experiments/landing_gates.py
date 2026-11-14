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
def roster_cells():
    import make_2611_stages as M
    cells = set()
    for spec in M.STAGES:
        for c in M.stage_cells(spec):
            if c.kind == "lane":
                cells.add((c.lane, c.scale, c.workload, c.backend, c.cls, c.arm))
    return [dict(zip(("lane", "scale", "workload", "backend", "cls", "arm"), c)) for c in sorted(cells)]


def roster_doc():
    cells = roster_cells()
    return {"cells": cells, "cells_sha256": hashlib.sha256(json.dumps(cells, sort_keys=True).encode()).hexdigest(),
            "generated_by": "landing_gates.py roster-gen (make_2611_stages.STAGES, stage_cells)"}


def load_roster(path=ROSTER):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if hashlib.sha256(json.dumps(doc["cells"], sort_keys=True).encode()).hexdigest() != doc["cells_sha256"]:
        raise SystemExit(f"REFUSING: {path} does not match its own sha256; regenerate it with landing_gates.py roster-gen")
    return doc


def declared_by_page(payload, c):
    """True when the page says why this staged cell has no row: a declared absence of its arm on its table (censored, withheld, not expressible, not measured) or the arm is
    off the page by name (page_check.OFF_PAGE_ARMS, an ablation that stays in the rows)."""
    import export_web as EW
    import page_check as PC
    label = EW.display_name(c["backend"])
    if c["backend"] in getattr(PC, "OFF_PAGE_ARMS", {}) or label in getattr(PC, "OFF_PAGE_ARMS", {}):
        return True
    tid = TABLE_OF.get((c["lane"], c["workload"]))
    for t in payload.get("tables", []):
        if t["id"] == tid:
            return any(str(a.get("backend")).startswith(label) for a in t.get("declared_absences") or [])
    return False


def roster_problems(rows, roster, lanes=None, need=3, payload=None):
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
    probs, ok, short_explained, in_roster = [], 0, 0, set()
    for c in cells:
        bs = builds if c["backend"].startswith("arcadedb") and AI.built({"backend": c["backend"]}) else [None]
        for b in bs:
            key = (c["lane"], c["scale"], c["workload"], c["backend"], c["cls"], c["arm"], b)
            rs = have.get(key, [])
            in_roster.add(key)
            reps = {_rep(r) for r in rs if _clean(r)} - {None}
            label = f"{c['lane']}/{c['scale']}/{c['workload']}/{c['backend']}/{c['cls']}" + (f"/{c['arm']}" if c["arm"] else "") + (f"/{b}" if b else "")
            if len(reps) >= need:
                ok += 1
            elif any(_explains(r) for r in rs):
                short_explained += 1
            elif payload is not None and declared_by_page(payload, c):
                short_explained += 1
            elif not rs:
                probs.append(f"MISSING {label}: staged, no row")
            else:
                probs.append(f"SHORT {label}: {len(reps)} clean repetition(s) of {need}, no row says why")
    orphans = sorted({k for k in have if k not in in_roster})
    summary = {"roster_cells": len(cells), "complete": ok, "explained_short": short_explained, "unexplained": len(probs), "orphan_cells": len(orphans), "orphans": orphans}
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
        if not tid or c["lane"] not in lanes or tid not in tables or c["cls"] != "relaxed":
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
    probs, summ = roster_problems(rows, roster, lanes, payload=payload)
    cprobs, kinds = collision_problems(rows)
    for p in probs + cprobs:
        print("  " + p)
    print(f"  roster {roster['cells_sha256'][:12]}: {summ['roster_cells']} staged cells, {summ['complete']} complete, {summ['explained_short']} short with a stated reason, "
          f"{summ['unexplained']} unexplained, {summ['orphan_cells']} orphan cell(s); collisions {kinds or 'none'}")
    return 1 if probs or cprobs else 0


if __name__ == "__main__":
    sys.exit(main())
