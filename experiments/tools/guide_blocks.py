#!/usr/bin/env python3
"""The runnable command blocks of docs/reproduce.md (the "Run it yourself" guide, humemai/mmdbbench#102).

A fenced block is runnable when the line before it, ignoring blank lines, is an HTML comment `<!-- runnable: NAME -->`.
The guide is the one place the commands live: `.github/workflows/reproduce-smoke.yml` runs them with this script, and
`test_reproduce_guide.py` checks that every file, backend id, scale and environment variable they name still exists, so a
rename in the harness breaks a test and not a reader.

  uv run --no-project python experiments/tools/guide_blocks.py docs/reproduce.md --list
  uv run --no-project python experiments/tools/guide_blocks.py docs/reproduce.md --name e2-arcadedb   # prints the block
"""
import argparse
import re
import sys

MARK = re.compile(r"^<!--\s*runnable:\s*([A-Za-z0-9._-]+)\s*-->\s*$")
FENCE = re.compile(r"^```(\w*)\s*$")


def extract(text):
    """[(name, lang, code)] in file order. A mark must be followed by a fenced block; a mark without one is an error."""
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        m = MARK.match(lines[i].strip())
        if not m:
            i += 1
            continue
        name = m.group(1)
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        f = FENCE.match(lines[j]) if j < len(lines) else None
        if not f:
            raise ValueError(f"runnable mark '{name}' (line {i + 1}) is not followed by a fenced block")
        k = j + 1
        body = []
        while k < len(lines) and not lines[k].startswith("```"):
            body.append(lines[k])
            k += 1
        if k >= len(lines):
            raise ValueError(f"runnable block '{name}' (line {i + 1}) is never closed")
        out.append((name, f.group(1), "\n".join(body) + "\n"))
        i = k + 1
    names = [n for n, _, _ in out]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ValueError(f"runnable names used twice: {dup}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("guide")
    ap.add_argument("--list", action="store_true", help="print the names of the runnable blocks")
    ap.add_argument("--name", action="append", default=[], help="print this block (repeatable: the blocks are joined in the order given)")
    args = ap.parse_args(argv)
    with open(args.guide, encoding="utf-8") as f:
        blocks = extract(f.read())
    by = {n: c for n, _, c in blocks}
    if args.list:
        print("\n".join(by))
        return 0
    for n in args.name:
        if n not in by:
            print(f"no runnable block '{n}' in {args.guide}; have: {', '.join(by)}", file=sys.stderr)
            return 1
        sys.stdout.write(by[n])
    return 0


if __name__ == "__main__":
    sys.exit(main())
