"""Merge dense-overlay directories into the one directory a landing reads (humemai/mmdbbench#28 and #29).

`make_paper_tables.dense_mp_dir()` reads `results/dense_mp5_<pin>` and nothing else, on purpose: an older overlay must never stand in for a
newer one. A landing that holds the arms of two engine pins (the comparators at one commit, ArcadeDB at another), or a live directory and a
catch-up directory of the same pin, therefore has to BUILD that one directory. This module builds it, and never lets one file silently
replace another of the same name:

- the same file name with the same bytes is fine; with different bytes it REFUSES and names both sources and the client each one names;
- the one replacement it allows: a file measured through the benchmark's own lean HTTP client replaces a file of the same name measured
  through the vendor driver or the PostgreSQL wire (a served ArcadeDB twin writes the same name as the headline job, and the page prints
  only the lean one; the exporter refuses the others), and the manifest says so;
- `exclude_arms` leaves an arm out (its JVM and native files), for a landing that does not print it;
- MANIFEST.txt beside the files says which source, pin and client each file came from.
"""
import hashlib
import json
import re
import shutil
from pathlib import Path

LEAN, OFFICIAL, PGWIRE = "lean", "official", "pgwire"
_NAME = re.compile(r"mp_(.+?)(?:_native)?_b\d+\.json")


def arm_of(name):
    m = _NAME.fullmatch(name)
    return m.group(1) if m else None


def client_of(path):
    """'lean', 'official' (the vendor driver), 'pgwire', or '' (no ArcadeDB client stamp: a comparator or an old file). The same test as
    make_paper_tables.is_official_client_row, read from the first pass of the file."""
    try:
        passes = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    p0 = passes[0] if isinstance(passes, list) and passes and isinstance(passes[0], dict) else (passes if isinstance(passes, dict) else {})
    client = str(p0.get("arcadedb_http_client") or "")
    if p0.get("arcadedb_client_wire") == "pgwire":
        return PGWIRE
    if p0.get("arcadedb_http_client_role") == "headline" or "arcadedb-driver" in client:
        return OFFICIAL
    return LEAN if "lean_http" in client else ""


def merge(sources, out, exclude_arms=()):
    """Merge `sources` [(label, directory)], in order, into directory `out`; returns the manifest lines. Refuses on a name collision."""
    out = Path(out)
    chosen, problems, replaced = {}, [], []
    for label, d in sources:
        for fp in sorted(Path(d).glob("mp_*_b*.json")):
            if arm_of(fp.name) in set(exclude_arms):
                continue
            sha = hashlib.sha256(fp.read_bytes()).hexdigest()
            client = client_of(fp)
            cur = chosen.get(fp.name)
            if cur is None:
                chosen[fp.name] = (label, fp, client, sha)
            elif cur[3] == sha:
                continue
            elif cur[2] in (OFFICIAL, PGWIRE) and client == LEAN:
                replaced.append(f"{fp.name}: {cur[0]} ({cur[2]}) replaced by {label} (lean)")
                chosen[fp.name] = (label, fp, client, sha)
            else:
                problems.append(f"{fp.name}: {cur[0]} ({cur[2] or 'no client stamp'}) differs from {label} ({client or 'no client stamp'})")
    if problems:
        raise SystemExit("REFUSING to merge the overlay directories: one file name, two different contents, and neither is a lean file "
                         "replacing a vendor-driver or PostgreSQL-wire file:\n  " + "\n  ".join(problems))
    out.mkdir(parents=True, exist_ok=True)
    lines = []
    for name, (label, fp, client, sha) in sorted(chosen.items()):
        dest = out / name
        if not (dest.exists() and dest.resolve() == fp.resolve()):
            shutil.copyfile(fp, dest)
        lines.append(f"{name}\t{label}\t{client or '-'}\t{sha[:12]}")
    manifest = ["# file\tsource@pin\tclient\tsha256[:12]"] + lines + [f"# replaced: {r}" for r in replaced]
    (out / "MANIFEST.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    return lines
