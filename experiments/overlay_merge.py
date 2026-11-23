"""Merge dense-overlay directories into the one directory a landing reads (humemai/mmdbbench#28 and #29), and name and resolve the overlay
files of the served ArcadeDB arms by client (humemai/mmdbbench#62).

`make_paper_tables.dense_mp_dir()` reads `results/dense_mp5_<pin>` and nothing else, on purpose: an older overlay must never stand in for a
newer one. A landing that holds the arms of two engine pins (the comparators at one commit, ArcadeDB at another), or a live directory and a
catch-up directory of the same pin, therefore has to BUILD that one directory. This module builds it, and never lets one file silently
replace another of the same name:

- the same file name with the same bytes is fine; with different bytes it REFUSES and names both sources and the client each one names;
- the one replacement it allows: a file measured through the benchmark's own lean HTTP client replaces a file of the same name measured
  through the vendor driver or the PostgreSQL wire (a served ArcadeDB twin of the 26.11.1 campaign wrote the same name as the headline job,
  and the page prints only the lean one; the exporter refuses the others), and the manifest says so;
- `exclude_arms` leaves an arm out (its JVM and native files), for a landing that does not print it. An entry is `ARM`, which leaves the arm
  out of every source, or `ARM@LABEL` (humemai/mmdbbench#147), which leaves it out of the one source called LABEL and keeps it from the others:
  the overlay of an old pin (the comparators and ArcadeDB's old arms) and the one of the new pin (ArcadeDB's new arms) both hold `mp_fp32_*`,
  and only the old files may go;
- MANIFEST.txt beside the files says which source, pin and client each file came from.

THE CLIENT IN THE FILE NAME (humemai/mmdbbench#62). A served ArcadeDB arm runs one cell as up to three jobs (the vendor driver, the lean twin, the
PostgreSQL-wire twin). Until 2026-11-22 all three wrote one name (`mp_arcsrv_b1.json`), so the last job to finish kept the file. The runner now
puts the client after the arm (`label_for`): `mp_arcsrv_clientlean_b1.json`, `mp_arcsrv_clientofficial_b1.json`, `mp_arcsrv_clientpgwire_b1.json`
(and `sp_arc_srv_clientlean_small.json` in the sparse overlay). A reader still asks for the PLAIN name (`mp_arcsrv_b1.json`) through `files()` or
`pick()`: it gets the file named for the lean client when there is one, else the plain file (the files of the 26.11.1 campaign), and never a file
named for another client. A plain file beside a lean-named one follows the same rule as the merge.
"""
import fnmatch
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

LEAN, OFFICIAL, PGWIRE = "lean", "official", "pgwire"
CLIENTS = (LEAN, OFFICIAL, PGWIRE)
_NAME = re.compile(r"mp_(.+?)(?:_native)?_b\d+\.json")
_CLIENT_IN_NAME = re.compile(r"_client(" + "|".join(CLIENTS) + r")(?=_)")


def label_for(label, client):
    """The arm label the runner puts in an overlay file name: `label` for a job with no client axis (`client` empty), else `<label>_client<client>`."""
    if not client:
        return label
    if client not in CLIENTS:
        raise ValueError(f"overlay client must be one of {CLIENTS}, got {client!r}")
    return f"{label}_client{client}"


def client_in_name(name):
    """'lean', 'official', 'pgwire', or '' for a name that carries no client (a comparator, an embedded arm, a file of the 26.11.1 campaign)."""
    m = _CLIENT_IN_NAME.search(os.path.basename(str(name)))
    return m.group(1) if m else ""


def plain_name(name):
    """The file name without the client: `mp_arcsrv_clientlean_native_b2.json` -> `mp_arcsrv_native_b2.json`. A reader's patterns match this."""
    return _CLIENT_IN_NAME.sub("", os.path.basename(str(name)), count=1)


def arm_of(name):
    m = _NAME.fullmatch(plain_name(name))
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


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _decide(name, cs):
    """The one rule (humemai/mmdbbench#61) for the candidates [(label, path, client, sha256)] of one plain file name. Returns (chosen, replaced, problem),
    two of them None: identical bytes are fine (the first candidate); with one lean candidate and every other candidate naming the vendor driver or the
    PostgreSQL wire the lean file is chosen and `replaced` says what it replaced; anything else that differs is a `problem` that names all candidates."""
    if len({c[3] for c in cs}) == 1:
        return cs[0], None, None
    lean = [c for c in cs if c[2] == LEAN]
    others = [c for c in cs if c[2] != LEAN]
    if lean and len({c[3] for c in lean}) == 1 and all(c[2] in (OFFICIAL, PGWIRE) for c in others):
        return lean[-1], f"{name}: " + ", ".join(f"{c[0]} ({c[2]})" for c in others) + f" replaced by {lean[-1][0]} (lean)", None
    return None, None, f"{name}: " + "; ".join(f"{c[0]} ({c[2] or 'no client stamp'}, {c[3][:8]})" for c in cs)


def files(directory, pattern="*.json"):
    """The overlay files of `directory` that a table reads, as paths (str) sorted by plain name. `pattern` is matched against the PLAIN name, so a
    reader asks for `mp_arcsrv_b*.json` as it always did. Per plain name: the file named for the lean client when there is one, else the plain file.
    A file named for the vendor driver or the PostgreSQL wire is never returned. A plain file beside a lean-named one follows `_decide`: the same
    bytes are fine, a plain file that names the vendor driver or the PostgreSQL wire loses, anything else refuses."""
    d = str(directory)
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    got = {}
    for n in names:
        client = client_in_name(n)
        if client not in ("", LEAN):
            continue
        plain = plain_name(n)
        if fnmatch.fnmatchcase(plain, pattern):
            got.setdefault(plain, {})["named" if client else "plain"] = os.path.join(d, n)
    out = []
    for plain in sorted(got):
        g = got[plain]
        if len(g) == 2:
            chosen, _, problem = _decide(plain, [(os.path.basename(g[k]), g[k], client_of(g[k]), _sha(g[k])) for k in ("named", "plain")])
            if problem:
                raise SystemExit(f"REFUSING to read {os.path.basename(d)}: a file named for the lean client and a plain file of the same arm and "
                                 f"repetition differ, and the plain one is not a vendor-driver or PostgreSQL-wire file:\n  {problem}")
            out.append(chosen[1])
        else:
            out.append(g.get("named") or g["plain"])
    return out


def pick(directory, plain):
    """The path to read for one plain file name (`mp_arcsrv_b1.json`): the lean-named file when the directory holds one, else the plain path
    itself, whether or not it exists (the caller tests that, as it did before)."""
    got = files(directory, plain)
    return got[0] if got else os.path.join(str(directory), plain)


def parse_exclude(specs):
    """The `--overlay-exclude` values as (arms, per_source): `arms` is the set of ARM entries (left out of every source, the form that always
    existed) and `per_source` the list of (arm, label) from `ARM@LABEL` entries. An empty ARM or an empty LABEL refuses."""
    arms, per_source = set(), []
    for spec in specs:
        arm, at, label = str(spec).partition("@")
        if not arm or (at and not label):
            raise SystemExit(f"REFUSING: --overlay-exclude {spec!r} must be ARM or ARM@LABEL")
        if at:
            per_source.append((arm, label))
        else:
            arms.add(arm)
    return arms, per_source


def is_excluded(arm, source_label, arms, per_source):
    """True when `arm` of the source called `source_label` is left out. A source label is `LABEL@PIN` (`comparators@e85469273`); an
    `ARM@LABEL` entry names the source by LABEL alone, or by the whole `LABEL@PIN`."""
    if arm is None:
        return False
    if arm in arms:
        return True
    return any(a == arm and l in (source_label, source_label.split("@", 1)[0]) for a, l in per_source)


def merge(sources, out, exclude_arms=()):
    """Merge `sources` [(label, directory)], in order, into directory `out`; returns the manifest lines. Refuses on a name collision.
    `exclude_arms` takes `ARM` and `ARM@LABEL` entries (`parse_exclude`).

    The decision is made ONCE per plain file name (`plain_name`: a file named for the lean client and a plain file of the same arm and repetition are
    candidates for one place), over every candidate, so it does not depend on the order of the sources (humemai/mmdbbench#87): identical
    bytes are fine; with one lean candidate and every other candidate naming the vendor driver or the PostgreSQL wire the lean file is chosen; anything else
    that differs refuses and names all candidates. The chosen file keeps its own name. A file NAMED for the vendor driver or the PostgreSQL wire is not
    merged (no table reads it; it stays on the host) and the manifest lists it."""
    out = Path(out)
    arms, per_source = parse_exclude(exclude_arms)
    cands, left = {}, []
    for label, d in sources:
        for fp in sorted(Path(d).glob("mp_*_b*.json")):
            if is_excluded(arm_of(fp.name), label, arms, per_source):
                continue
            if client_in_name(fp.name) not in ("", LEAN):
                left.append(f"{label}/{fp.name}")
                continue
            cands.setdefault(plain_name(fp.name), []).append((label, fp, client_of(fp), _sha(fp)))
    chosen, problems, replaced = {}, [], []
    for name, cs in sorted(cands.items()):
        pick_, repl, problem = _decide(name, cs)
        if problem:
            problems.append(problem)
            continue
        chosen[name] = pick_
        if repl:
            replaced.append(repl)
    if problems:
        raise SystemExit("REFUSING to merge the overlay directories: one file name, different contents, and not (one lean file beside vendor-driver or "
                         "PostgreSQL-wire files):\n  " + "\n  ".join(problems))
    out.mkdir(parents=True, exist_ok=True)
    lines = []
    for _plain, (label, fp, client, sha) in sorted(chosen.items()):
        dest = out / fp.name
        if not (dest.exists() and dest.resolve() == fp.resolve()):
            shutil.copyfile(fp, dest)
        lines.append(f"{fp.name}\t{label}\t{client or '-'}\t{sha[:12]}")
    manifest = (["# file\tsource@pin\tclient\tsha256[:12]"] + lines + [f"# replaced: {r}" for r in replaced]
                + [f"# not merged, named for another client: {x}" for x in left])
    (out / "MANIFEST.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    return lines
