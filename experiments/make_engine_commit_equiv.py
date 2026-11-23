#!/usr/bin/env python3
"""make_engine_commit_equiv.py: generate the evidence that two engine commits of ONE release are the same engine, never typed by hand.

2026-11-07. The 26.11.1 release has two commits in its official artifacts: the JVM image, the jars and both wheels were built at BASE
(a3a5d12457), upstream's native-image.yml built the `-native` server image at the release tag HEAD ("Set release version to 26.11.1", 0f3bb2238c).
verify_native_server_image.sh, runner.engine_commit_problems, arm_identity and provenance_check compare the server-reported commit to the pin,
so the pair needs ONE explicit, evidence-backed rule. This script computes the evidence from git and writes it:

  ENGINE-COMMIT-EQUIV-<release>.md   the diff stat, the files, the classification, the two images' reported commits, the rule
  --out-json PATH                    the machine-readable registry entry (harness repo: experiments/engine_commit_equiv.json)

CLASSIFICATION (exact): `git diff -U0 BASE HEAD` is split into hunks. In a hunk the removed and the added lines are paired in order. A pair is a
VERSION-STRING change when, after replacing every occurrence of the old or the new release string (optionally followed by -SNAPSHOT) with a
placeholder in both lines, the two lines are equal and they were not equal before. That covers <version> in the poms, "version" in
studio/package.json and package-lock.json and the docker identifiers (arcadedata/arcadedb:26.10.2 -> :26.11.1) in server.json. A hunk whose
removed and added line counts differ, a pair that is equal only without the replacement of any other number, and every other line are NON-VERSION lines.
The rule accepts the pair only at 0 non-version lines AND exactly one commit between BASE and HEAD (`git log BASE..HEAD`); any other result
writes RESULT: REFUSED, no JSON, and exits 1.

EXIT STATUS: 0 accepted (the markdown says RESULT: ACCEPTED, and the JSON entry is written when --out-json is given). 1 refused (the markdown says
RESULT: REFUSED and lists the non-version lines, no JSON is written, the first 20 non-version lines go to stderr). 1 also for a --release that is
not A.B.C and for a failing git command (a traceback); nothing is written then. 2 is argparse's usage error.

example: make_engine_commit_equiv.py --repo DIR --base SHA --head SHA --release 26.11.1 --old-release 26.10.2 --status STATUS.txt --out-md F [--out-json F]
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def git(repo, *a):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, check=True).stdout


def classify(diff, old, new):
    """(version_lines, non_version [(file, line)]) from a -U0 diff."""
    tok = re.compile("(?:" + re.escape(old) + "|" + re.escape(new) + r")(?:-SNAPSHOT)?")
    ver, non, cur = 0, [], None
    rem, add = [], []

    def flush():
        nonlocal ver
        if len(rem) == len(add):
            for r, a in zip(rem, add):
                if r != a and tok.sub("@V@", r) == tok.sub("@V@", a):
                    ver += 2
                else:
                    non.extend([(cur, "-" + r), (cur, "+" + a)])
        else:
            non.extend([(cur, "-" + r) for r in rem] + [(cur, "+" + a) for a in add])
        rem.clear()
        add.clear()

    for line in diff.splitlines():
        if line.startswith("diff --git"):
            flush()
            cur = line.split(" b/", 1)[1]
        elif line.startswith("@@"):
            flush()
        elif line.startswith(("---", "+++", "index ", "new file", "deleted file", "similarity", "rename ", "old mode", "new mode", "Binary")):
            continue
        elif line.startswith("-"):
            rem.append(line[1:])
        elif line.startswith("+"):
            add.append(line[1:])
    flush()
    return ver, non


def evidence_lines(status, saved):
    """The PAIR VERIFIED and NATIVE_SERVER lines of the dry run. STATUS.txt is truncated by the next dry run, so the first extraction is
    saved beside the md and read back when the status file no longer has them."""
    want = ("PAIR VERIFIED", "NATIVE_SERVER_VERSION=", "NATIVE_SERVER_COMMIT=", "NATIVE SERVER UNVERIFIED")
    got = []
    if status and Path(status).exists():
        got = [re.sub(r"\s+(wheel|repo)=.*$", "", l.rstrip("\n")) for l in open(status) if l.startswith(want)]
    if got:
        if not Path(saved).exists():
            Path(saved).write_text("\n".join(got) + "\n")
        return got, status
    if Path(saved).exists():
        return Path(saved).read_text().splitlines(), str(saved)
    return [], None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, help="a git checkout of the engine that has both commits (read only: only git diff, log, rev-parse run in it)")
    ap.add_argument("--base", required=True, help="the pin: the commit of the JVM image, the jars and both wheels (any revision git rev-parse resolves; written as 40 hex)")
    ap.add_argument("--head", required=True, help="the commit the native server image reports (the release tag commit); must be exactly one commit after --base")
    ap.add_argument("--release", required=True, help="the release, A.B.C (for example 26.12.1); a dev version is refused")
    ap.add_argument("--old-release", required=True, help="the release before it (for example 26.11.1): its string is replaced like --release in the classification")
    ap.add_argument("--status", help="the four-arm dry run STATUS file: its PAIR VERIFIED and NATIVE_SERVER lines go into the markdown; without it the lines saved beside --out-md (.status-lines.txt) are used")
    ap.add_argument("--out-md", required=True, help="the evidence markdown, written for an accepted and for a refused pair")
    ap.add_argument("--out-json", help="the registry entry, written only when accepted: a JSON object with ONE key, the release, replacing the file at this path. The registry experiments/engine_commit_equiv.json holds one key per release, so merge the object into it, never point this at the registry itself")
    ap.add_argument("--evidence", help="the text of the entry's `evidence` field (default: ENGINE-COMMIT-EQUIV-<release>.md)")
    a = ap.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", a.release):
        sys.exit("REFUSING: the equivalence is for a RELEASE pair (A.B.C), never a dev pair")
    base, head = (git(a.repo, "rev-parse", x).strip() for x in (a.base, a.head))
    stat = git(a.repo, "diff", "--stat=140", base, head)
    names = git(a.repo, "diff", "--name-only", base, head).split()
    shortstat = git(a.repo, "diff", "--shortstat", base, head).strip()
    subj = git(a.repo, "log", "--format=%h %s", f"{base}..{head}").strip().splitlines()
    ver, non = classify(git(a.repo, "diff", "-U0", "--no-color", base, head), a.old_release, a.release)
    ok = not non and len(subj) == 1
    ev, ev_src = evidence_lines(a.status, str(Path(a.out_md).with_suffix(".status-lines.txt")))
    md = [f"# ENGINE-COMMIT-EQUIV-{a.release}",
          "",
          f"RESULT: {'ACCEPTED' if ok else 'REFUSED'} {a.release} pin={base} equivalent={head} version_string_lines={ver} non_version_lines={len(non)}",
          "",
          "Generated by make_engine_commit_equiv.py (never edit by hand). Re-run it to refresh; a differing diff makes it exit 1 and write REFUSED.",
          "",
          f"## The two commits of {a.release}",
          "",
          f"- `{base}`: the commit of the JVM server image `arcadedata/arcadedb:{a.release}`, the jars, and both wheels (the pin in every study and in the four-arm pins).",
          f"- `{head}`: the commit upstream's native-image.yml built `arcadedata/arcadedb:{a.release}-native` at (the release tag).",
          f"- commits between them (`git log {base[:10]}..{head[:10]}`): {len(subj)}" + "".join(f"\n  - {s}" for s in subj),
          "",
          f"## `git diff --stat {base[:10]} {head[:10]}`",
          "",
          "```",
          stat.rstrip(),
          "```",
          "",
          f"shortstat: {shortstat}",
          "",
          "## Changed files",
          "",
          *[f"- `{n}`" for n in names],
          "",
          "## Classification",
          "",
          f"A removed/added line pair is a version-string change when it is equal after replacing every `{a.old_release}` and `{a.release}` (optionally followed by `-SNAPSHOT`) with a placeholder and was not equal before. "
          "That covers the poms, `studio/package.json`, `studio/package-lock.json` and the docker identifiers of `server.json` "
          f"(`arcadedata/arcadedb:{a.old_release}` to `:{a.release}`). A hunk with unequal removed and added counts, and any other line, is a non-version line.",
          "",
          f"- version-string changed lines: {ver}",
          f"- non-version changed lines: {len(non)}",
          *[f"  - `{f}`: `{l[:120]}`" for f, l in non[:40]],
          "",
          "## What the two images report",
          "",
          f"From {ev_src or 'no status file given'} (the four-arm dry run on the released artifacts):",
          "",
          "```",
          *(ev or ["(no PAIR VERIFIED or NATIVE_SERVER lines found)"]),
          "```",
          "",
          "## The rule",
          "",
          f"1. The equivalence is accepted for the RELEASE pair {a.release} only (pin `{base[:10]}`, equivalent `{head[:10]}`). Never for a dev pair: a dev-commit pair builds its native image at the pair's commit (verify_native_server_image.sh header).",
          "2. It is accepted only at 0 non-version changed lines and one commit between the two. Any other diff fails this script, and the registry entry is then not written.",
          "3. It is opt-in per run: `NATIVE_SERVER_EQUIV_SHAS` in the pins (run.sh exports it) AND the entry in `experiments/engine_commit_equiv.json`. Rows keep `engine_commit` = the pin; the native server's own commit stays visible in `server_engine_commit` and in STATUS as `NATIVE_SERVER_EQUIV=...`.",
          "4. It applies to the native SERVER image only. The native wheel's jars, the JVM wheel and both server-side JVM images still have to equal the pin exactly (verify_pair_c25.sh).",
          ""]
    Path(a.out_md).write_text("\n".join(md))
    if not ok:
        print(f"REFUSED: {len(non)} non-version changed lines, {len(subj)} commits between the two", file=sys.stderr)
        for f, l in non[:20]:
            print(f"  {f}: {l[:120]}", file=sys.stderr)
        sys.exit(1)
    if a.out_json:
        entry = {a.release: {"pin": base, "equivalent": [head], "files_changed": len(names), "version_string_lines": ver,
                             "non_version_lines": 0, "evidence": a.evidence or f"ENGINE-COMMIT-EQUIV-{a.release}.md",
                             "scope": "the native server image only; release pair only"}}
        Path(a.out_json).write_text(json.dumps(entry, indent=2) + "\n")
    print(f"ACCEPTED {a.release}: {len(names)} files, {ver} version-string lines, 0 non-version lines; {base[:10]} == {head[:10]}")


if __name__ == "__main__":
    main()
