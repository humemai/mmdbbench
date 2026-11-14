#!/usr/bin/env python3
"""Publish the data behind the page as a checkable artifact (DECISIONS #97, #331).

Most readers who doubt a benchmark do not want to run it; they want the rows.
This bundles what the page was generated from: the raw rows of the landing
store (runs.jsonl), the frozen per-cell CSV and the payload the site renders,
with a manifest naming the sha256 of each, the engine pin, the comparator
pins, and the gate status at publish time, and attaches it to a GitHub release
of humemai/mmdbbench so a table can be checked against its own data without a
machine, a corpus, or a container. The raw rows are scanned first: a file with
an email address, a token, a secret assignment, a tailnet name or a home
directory is refused (private_findings), and nothing is written.

    python publish_results_asset.py --tag bench-2026-11-14 [--notes-file NOTES.md] [--publish]

Without --publish it writes the bundle and prints the exact gh commands it
would run, which is the same dry-run-then-apply shape land_stage.py uses.
"""
import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import time
from pathlib import Path

from publish_instrument import PUBLISH_INSTRUMENT, refuse_other_instruments, results_dir

HERE = Path(__file__).resolve().parent
RESULTS = results_dir()
REPO = HERE.parent

# This bundles the one set the lane pages are built from: results/runs_paper.csv,
# results/web_benchmarks.json and the gate status beside the generated tables.
# Its own two outputs under generated/ -- the manifest and the tarball -- are
# gitignored.


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


REPO_SLUG = "humemai/mmdbbench"
PAGE_URL = "https://humem.ai/research/mmdbbench"
DEFAULT_NOTES = ("The raw rows, the frozen table and the payload behind the tables at " + PAGE_URL + ", with the pins and the gate status they were published under.")

# WHAT MUST NOT GO INTO A PUBLIC RELEASE. A rows file is the raw record of the benchmark hosts, and nothing but this scan stood between it and a public asset.
# The containers' own user (/home/arcadedb) and docker bridge addresses are part of the record and are not private; a person's home directory, an email
# address, a token, a secret assignment and a tailnet name or address are. Counted per kind, so a refusal says what was found without printing it.
PRIVATE_PATTERNS = {
    "email address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z][A-Za-z0-9.-]*"),
    "token": re.compile(r"ghp_[A-Za-z0-9]{20,}|github_pat_|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-|-----BEGIN|eyJ[A-Za-z0-9_-]{20,}"),
    "secret assignment": re.compile(r"(?i)(?:password|passwd|secret|api[_-]?key|auth[_-]?token)[\"']?\s*[:=]\s*[\"'][^\"']{4,}"),
    "tailnet name or address": re.compile(r"\.ts\.net\b|(?i:tailscale)|\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"),
    "home directory": re.compile(r"/home/(?!arcadedb\b)[A-Za-z0-9_.-]+|/Users/[A-Za-z0-9_.-]+|C:\\\\Users"),
}


def private_findings(path) -> dict:
    """{kind: count} of the private content in a rows file; empty when there is none."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return {kind: len(pat.findall(text)) for kind, pat in PRIVATE_PATTERNS.items() if pat.search(text)}


def release_commands(tag, bundle, notes_file=None):
    """The exact gh commands a publish runs, as argv lists: one release created with the bundle attached."""
    create = ["gh", "release", "create", tag, "--repo", REPO_SLUG, "--title", f"Raw rows and page payload {tag}"]
    create += ["--notes-file", str(notes_file)] if notes_file else ["--notes", DEFAULT_NOTES]
    return [create + [str(bundle)]]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", required=True, help="release tag to attach to, created if absent")
    ap.add_argument("--publish", action="store_true", help="upload; default writes and prints only")
    ap.add_argument("--out", default=str(RESULTS / "generated"))
    ap.add_argument("--rows", default="", help="the raw rows file of the landing store (default results/runs.jsonl)")
    ap.add_argument("--notes-file", default="", help="release notes for a new release (default: one plain sentence)")
    args = ap.parse_args()

    payload = RESULTS / "web_benchmarks.json"
    frozen = RESULTS / "runs_paper.csv"
    rows_path = Path(args.rows) if args.rows else RESULTS / "runs.jsonl"
    for p in (payload, frozen, rows_path):
        if not p.exists():
            print(f"missing {p}; run refresh_web_page.py first", file=sys.stderr)
            return 2

    doc = json.loads(payload.read_text())
    if doc.get("instrument") != PUBLISH_INSTRUMENT or doc.get("skeleton"):
        print(f"REFUSING: {payload} is stamped instrument {doc.get('instrument')!r}, "
              f"skeleton={doc.get('skeleton')!r}; a release asset bundles {PUBLISH_INSTRUMENT} "
              f"measured rows only.", file=sys.stderr)
        return 1
    with open(frozen, newline="", encoding="utf-8") as fh:
        refuse_other_instruments(list(csv.DictReader(fh)), str(frozen))
    found = private_findings(rows_path)
    if found:
        print(f"REFUSING: {rows_path} holds private content ({', '.join(f'{k}: {v}' for k, v in sorted(found.items()))}); nothing was written. "
              f"Remove it from the rows or leave the rows out of the release.", file=sys.stderr)
        return 1
    raw = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    manifest = {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "engine": doc.get("arcadedb_engines"),
        "arcadedb_commits": doc.get("arcadedb_commits"),
        "tables": [t["id"] for t in doc.get("tables", [])],
        "rows_in_frozen_csv": sum(1 for _ in open(frozen)) - 1,
        "files": {p.name: {"bytes": p.stat().st_size, "sha256": _sha256(p)}
                  for p in (payload, frozen, rows_path)},
        "rows_in_raw_rows": len(raw),
        "raw_rows_instruments": dict(sorted({k: sum(1 for r in raw if str(r.get("instrument") or "") == k)
                                             for k in {str(r.get("instrument") or "") for r in raw}}.items())),
        # make_paper_tables writes the gate status beside the .tex tables it gates
        "gates": (RESULTS / "generated" / "tables" / "GATE_STATUS.txt").read_text().strip()
                 if (RESULTS / "generated" / "tables" / "GATE_STATUS.txt").exists() else None,
        "how_to_check": (
            "Every table on the MMDBBench page at " + PAGE_URL + " is generated from "
            "web_benchmarks.json, which is aggregated from runs_paper.csv, one row per "
            "cell per repetition; runs.jsonl is the raw record of the landing store that "
            "runs_paper.csv was frozen from. A published cell is the median across repetitions of "
            "the rows sharing its lane, scale, backend, and workload."),
    }
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle = out_dir / f"benchmark-results-{args.tag}.tar.gz"
    man_path = out_dir / "results_manifest.json"
    man_path.write_text(json.dumps(manifest, indent=2) + "\n")
    with tarfile.open(bundle, "w:gz") as tar:
        for p in (payload, frozen, rows_path, man_path):
            tar.add(p, arcname=p.name)
    print(f"bundle {bundle} ({bundle.stat().st_size/1e6:.1f} MB)")
    print(f"  engine {manifest['engine']}  tables {len(manifest['tables'])}  "
          f"rows {manifest['rows_in_frozen_csv']}")
    cmds = release_commands(args.tag, bundle, args.notes_file or None)
    print(f"  raw rows {manifest['rows_in_raw_rows']} {manifest['raw_rows_instruments']}, sha256 {manifest['files'][rows_path.name]['sha256']}")
    if not args.publish:
        print("dry run: pass --publish to run:")
        for c in cmds:
            print("  " + " ".join(c))
        return 0
    have = subprocess.run(["gh", "release", "view", args.tag, "--repo", REPO_SLUG],
                          capture_output=True, text=True).returncode == 0
    if not have:
        subprocess.run(cmds[0], check=True)
    else:
        subprocess.run(["gh", "release", "upload", args.tag, str(bundle), "--clobber", "--repo", REPO_SLUG], check=True)
    print(f"attached to release {args.tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
