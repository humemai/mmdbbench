#!/usr/bin/env python3
"""qual_throttle_check.py: the heat check of the qualification plans of QUALIFICATION-PLAN.md. The analyzer of the lane kit (`qualify analyze`) reads the ratios of the
rows and not their throttle time (humem-ops#480, point 4), so this script reads the rows of a `qualify run` directory and lists every run whose evidence has a throttle
time above 1 percent of its probe time, or no throttle reading, with its case, probe, lane and round. READ-ONLY.

Run:  uv run --no-project python -I qual_throttle_check.py ROWS.jsonl [ROWS.jsonl ...]     (exit 0: no run is throttled; 1: some are; 2: input refused)
      uv run --no-project python -I qual_throttle_check.py --selftest
Row format: one JSON object per line as `qualify run` writes it (qualification.md, "The result rows"): case, probe, round, lane, status, `probe_seconds` (the time box the
probe ran with) and `evidence` with `throttle_ms`, `pkg_c_start`, `pkg_c_end`.
The rule is registered in QUALIFICATION-PLAN.md: a case with any throttled run is not read as QUALIFIED even if the analyzer says so; the plan goes on to its next rung
only after the owner has read this list.
"""
import json
import os
import sys
import tempfile

SHARE = 0.01


def check(paths):
    rows = []
    for p in paths:
        for ln in open(p, encoding="utf-8"):
            if ln.strip():
                try:
                    rows.append(json.loads(ln))
                except ValueError:
                    print(f"REFUSED: malformed line in {p}", file=sys.stderr)
                    sys.exit(2)
    if not rows:
        print("REFUSED: no rows", file=sys.stderr)
        sys.exit(2)
    bad = []
    for r in rows:
        if r.get("status") not in ("ok", "timeout"):
            continue
        ev = r.get("evidence") or {}
        tm, box = ev.get("throttle_ms"), r.get("probe_seconds")
        why = None
        if tm is None:
            why = "throttle not read"
        elif not box:
            why = "probe time box not in the row"
        elif tm > SHARE * box * 1000:
            why = f"throttled {tm} ms of {box * 1000:.0f} ms ({tm / (box * 1000) * 100:.2f} percent)"
        if why:
            bad.append((r.get("case"), r.get("probe"), r.get("round"), r.get("lane"), why, ev.get("pkg_c_end")))
    return len(rows), bad


def selftest():
    d = tempfile.mkdtemp(prefix="qual-throttle-")
    p = os.path.join(d, "rows.jsonl")
    base = {"status": "ok", "probe_seconds": 60, "lane": "compare1", "case": "all-compare", "probe": "io"}
    rows = [dict(base, round=1, evidence={"throttle_ms": 0, "pkg_c_end": 70}), dict(base, round=2, evidence={"throttle_ms": 900, "pkg_c_end": 90}), dict(base, round=3, evidence={}),
            dict(base, round=4, status="failed", evidence=None)]
    open(p, "w").write("\n".join(json.dumps(r) for r in rows) + "\n")
    n, bad = check([p])
    assert n == 4 and len(bad) == 2 and "throttled 900 ms" in bad[0][4] and bad[1][4] == "throttle not read", bad
    print("selftest ok: 4 rows, 2 listed (900 ms of 60000 ms is 1.5 percent; a missing reading is listed; a failed row is not a run)")


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        selftest()
        sys.exit(0)
    if not sys.argv[1:]:
        print(__doc__)
        sys.exit(2)
    n, bad = check(sys.argv[1:])
    print(f"{n} rows read, {len(bad)} runs with throttle above {SHARE * 100:g} percent or unread")
    for b in bad:
        print("  case %s probe %s round %s lane %s: %s (package at the end %s C)" % b)
    sys.exit(1 if bad else 0)
