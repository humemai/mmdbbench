#!/usr/bin/env python3
"""merge_fourarm_rows.py: the one runs_page_<pin>_2611.jsonl that land_stage.py lands, built from the FOUR places the four-arm rows live.

land_stage.py pulls ONE file from ONE directory of the bench host. The four-arm rows are in two worktrees' own results directories (the symlink to the main
results directory was never made) and the catch-up rows are in two more:
    ~/fourarm-wt/jvm/...  ~/fourarm-wt/native/...  ~/fourarm-catchup-wt/jvm/...  ~/fourarm-catchup-wt/native/...   (each .../<results>/runs_page_<pin>_2611.jsonl)
Rule (per (engine_backend, run_id)): a clean row (no `error`) beats every error row of that (engine_backend, run_id) (the live failed twin and strict rows carry no data,
the catch-up row is the new row at its own pin); several clean rows of one key keep the LAST one in source order (catch-up after live, then by ts_utc); a key with only
error rows keeps its last error row. Row order otherwise follows the first appearance of the key. run_id alone is NOT a key: the JVM and the native chains write the same
run_id for the same cell and are told apart only by engine_backend. Prints one summary line per source and the totals to stderr.

    merge_fourarm_rows.py --out FILE SOURCE...          SOURCE = local jsonl path
    merge_fourarm_rows.py --pull PIN --out FILE         scp the four files of the bench host first (read-only there), then merge

then land with `BENCH_LAND_PULLED_FILE=FILE python land_stage.py ...` (PUBLISHING.md).

Environment, all optional:
    BENCH_LAND_HOST         the host the files are pulled from (default mini, the same variable land_stage.py reads)
    BENCH_FOURARM_PULL      the four remote directories, separated by colons (default ~/fourarm-wt/jvm:~/fourarm-wt/native:~/fourarm-catchup-wt/jvm:~/fourarm-catchup-wt/native)
    BENCH_FOURARM_RESULTS   the results directory below each of them (default benchmarks/experiments/results, the layout of the checkout the host runs from)
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

PULL = os.environ.get("BENCH_FOURARM_PULL",
                      "~/fourarm-wt/jvm:~/fourarm-wt/native:~/fourarm-catchup-wt/jvm:~/fourarm-catchup-wt/native").split(":")
HOST = os.environ.get("BENCH_LAND_HOST", "mini")
RESULTS = os.environ.get("BENCH_FOURARM_RESULTS", "benchmarks/experiments/results")


def merge(paths):
    first, best, order, seen = {}, {}, [], {}
    for path in paths:
        n = 0
        for line in open(path, errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            n += 1
            # run_id alone is not unique: the JVM and the native chains share it (l2_arcadedb_graph_embedded_oltp_sf1_r1 in both), so keying on
            # it kept 186 of 365 rows in the 2026-11-14 rehearsal; with the build in the key all 365 stay.
            rid = (r.get("engine_backend"), r.get("run_id"))
            if rid not in first:
                first[rid] = len(order)
                order.append(rid)
            clean = not r.get("error")
            cur = best.get(rid)
            if cur is None or clean or not cur[0]:   # a clean row always replaces; an error row replaces only another error row
                best[rid] = (clean, r)
        seen[path] = n
    rows = [best[rid][1] for rid in order]
    return rows, seen


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pull", metavar="PIN9")
    ap.add_argument("sources", nargs="*")
    a = ap.parse_args()
    srcs = list(a.sources)
    d = tempfile.mkdtemp(prefix="fourarm-rows-") if a.pull else None
    try:                                  # the pulled copies are removed whatever happens (a failed scp used to leave /tmp/fourarm-rows-* behind)
        if a.pull:
            for i, base in enumerate(PULL):
                dst = os.path.join(d, f"{i}-{os.path.basename(base)}.jsonl")
                r = subprocess.run(["scp", "-q", f"{HOST}:{base}/{RESULTS}/runs_page_{a.pull}_2611.jsonl", dst])
                if r.returncode != 0:
                    if "catchup" in base:
                        print(f"note: no catch-up file {base} (not started yet?)", file=sys.stderr)
                        continue
                    sys.exit(f"scp of {base} failed")
                srcs.append(dst)
        if not srcs:
            sys.exit("no source")
        rows, seen = merge(srcs)
        with open(a.out, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        for p, n in seen.items():
            print(f"{n:7d} rows  {p}", file=sys.stderr)
        errs = sum(1 for r in rows if r.get("error"))
        print(f"{len(rows)} rows after the merge ({errs} error rows) -> {a.out}", file=sys.stderr)
        return 0
    finally:
        if d:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
