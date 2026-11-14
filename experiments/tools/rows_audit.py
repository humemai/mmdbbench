#!/usr/bin/env python3
"""rows_audit.py: clean reps per ArcadeDB cell and CLIENT SERIES, from the result ROWS (not the rep-state files).
Why: the rep-state files do not name the client, and an audit that unions the main and the -pgwire files counts the PostgreSQL-wire reps as if they were HTTP reps (that hid 7 served cells with ONE HTTP rep).
Usage: copy the four `runs_page_<pin>_2611.jsonl` (the live and the catch-up worktrees, JVM and native, from the bench host) into a directory as runs_fourarm-wt_jvm.jsonl, runs_fourarm-wt_native.jsonl, runs_fourarm-catchup-wt_jvm.jsonl, runs_fourarm-catchup-wt_native.jsonl, then run `uv run --no-project python -I rows_audit.py [DIR]` (DIR defaults to ./fresh).
Series: embedded; srv-lean (arcadedb_http_client lean_http: the paper's headline client, DECISIONS #268); srv-official (arcadedb-driver, role `headline` in the data); srv-pgwire; srv-other (rows without a client field: the failed attempts)."""
import collections
import json
import os
import sys


def L(f): return [json.loads(l) for l in open(f)]
def ok(r): return r.get("rc") == 0 and not r.get("error")
D = sys.argv[1] if len(sys.argv) > 1 else "fresh"
files = {"JVM": [os.path.join(D, "runs_fourarm-wt_jvm.jsonl"), os.path.join(D, "runs_fourarm-catchup-wt_jvm.jsonl")],
         "NAT": [os.path.join(D, "runs_fourarm-wt_native.jsonl"), os.path.join(D, "runs_fourarm-catchup-wt_native.jsonl")]}
reps = collections.defaultdict(set)   # (tag, cell, series) -> reps with a clean row
seen = collections.defaultdict(set)
for tag, fs in files.items():
    for f in fs:
        for r in L(f):
            b = r.get("backend", "")
            if not b.startswith("arcadedb") or b == "arcadedb_imgdefaults_server" or r.get("backend_arm") == "nogav": continue
            dep = "srv" if b.endswith("_server") else "emb"
            if dep == "emb": series = "embedded"
            elif r.get("arcadedb_client_wire") == "pgwire": series = "srv-pgwire"
            else:
                cl = r.get("arcadedb_http_client", "") or ""
                series = "srv-lean" if cl.startswith("lean_http") else ("srv-official" if cl.startswith("arcadedb-driver") else "srv-other")
            cell = (r.get("lane"), r.get("scale"), b, r.get("workload"), r.get("durability_class"))
            key = (tag, cell, series)
            seen[key].add(r.get("rep"))
            if ok(r) and r.get("rep") in (1, 2, 3): reps[key].add(r["rep"])
short = collections.Counter()
rows = []
for key in sorted(seen, key=str):
    n = len(reps.get(key, ()))
    short[(key[0], key[2], n >= 3)] += 1
    if n < 3: rows.append((key[0], key[2], n, sorted(seen[key]), key[1]))
for (tag, series, full), c in sorted(short.items()): print(f"{tag} {series:13s} cells with 3 clean reps: {c if full else 0:3d}   below 3: {0 if full else c:3d}")
print("--- series with fewer than 3 clean reps (tag, series, clean, reps seen, cell)")
for r in rows: print(r)
