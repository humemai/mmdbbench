#!/usr/bin/env python3
"""Is every pin at the latest release that works? A report, never a change (humemai/mmdbbench#175, item 1).

    uv run python pin_freshness.py                    # read the sources and print the report as markdown
    uv run python pin_freshness.py --json report.json # the same report as data too
    uv run python pin_freshness.py --list             # the pins as the files carry them; no network

THE PINS are read from the files the images are built from and the cells start from (PIN_FILES): every `name==version` of build_images.sh,
every image pinned by digest in runner.py and the Dockerfiles, the pinned apt package and JPype version, and the base images that float.

THE SOURCES are PyPI, Docker Hub, GitHub releases and the PGDG apt index. pin_sources.json says where each image and apt package is read, which
version its digest stands for, which releases are stable, and which of those the lanes can use (`compatible`, with the row of
comparator_constraints.json that says why). A Python package is read from PyPI under its own name.

THE RULE: the latest release that every lane of a backend works with. Per pin:

    current   at the latest stable release
    blocked   at the latest compatible release, which is older than the latest one; the blocker is printed
    held      behind the latest compatible release, with an exception line (version, reason, date, who decided)
    behind    behind the latest compatible release with no exception line
    unread    the source could not be read, or its listing does not reach the pin; never counted as current
    floating  a base image named by tag, so there is no pin to compare
    own       ArcadeDB and its client layer, which are what is measured; listed, not judged

Exit status: 1 when a pin is behind, else 2 when a source is unread, else 0.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCES = HERE / "pin_sources.json"
CONSTRAINTS = HERE / "comparator_constraints.json"
PIN_FILES = ("runner.py", "build_images.sh", "Dockerfile.bench", "Dockerfile.client-arcadedb", "Dockerfile.composed", "Dockerfile.mongosearch",
             "Dockerfile.pgage")

IMAGE_RE = re.compile(r"(?P<name>[a-z0-9][a-z0-9._/-]*)(?::[A-Za-z0-9._-]+)?@sha256:(?P<digest>[0-9a-f]{64})")
PACKAGE_RE = re.compile(r"(?<![\w$.-])(?P<name>[A-Za-z][A-Za-z0-9_.-]*)(?:\[[a-z0-9_,-]+\])?==(?P<version>[0-9][0-9A-Za-z.]*)")
APT_RE = re.compile(r"\b(?P<name>postgresql-\d+-[a-z0-9-]+)=(?P<version>[0-9][^\s\\\"']*)")
JPYPE_RE = re.compile(r"^ARG JPYPE_VERSION=(?P<version>[0-9][0-9.]*)")
FROM_RE = re.compile(r"^FROM\s+(?P<name>[a-z0-9][a-z0-9._/-]*:[A-Za-z0-9._-]+)(?:\s|$)")
PYPI_STABLE = re.compile(r"^\d+(\.\d+)*(\.post\d+)?$")

DOCKERHUB_PAGES = 5          # of 100 tags, newest push first; an entry may ask for more
GITHUB_PAGES = 2
TIMEOUT_S = 60
ATTEMPTS = 3
RETRY_WAIT_S = 5


@dataclasses.dataclass(frozen=True)
class Pin:
    kind: str                # pypi, image, apt, floating
    name: str
    version: str | None      # None for an image: the files carry a digest, pin_sources.json the version
    digest: str | None
    files: tuple


def collect_pins(root: Path = HERE) -> list:
    """Every pin the files carry, once, with the files that carry it. Comments are not pins."""
    found = {}
    for name in PIN_FILES:
        for line in (root / name).read_text(encoding="utf-8").splitlines():
            code = re.split(r"(?:^|\s)#", line, maxsplit=1)[0]
            hits = [("image", m["name"], None, m["digest"]) for m in IMAGE_RE.finditer(code)]
            if name != "runner.py":        # in Python source `==` is a comparison
                hits += [("pypi", m["name"].lower(), m["version"], None) for m in PACKAGE_RE.finditer(code)]
            if name.startswith("Dockerfile"):
                hits += [("apt", m["name"], m["version"], None) for m in APT_RE.finditer(code)]
                m = JPYPE_RE.match(code)
                if m:
                    hits.append(("pypi", "jpype1", m["version"], None))
                m = FROM_RE.match(code)
                if m and not m["name"].startswith("dbbench:"):
                    hits.append(("floating", m["name"], None, None))
            for key in hits:
                files = found.setdefault(key, [])
                if name not in files:
                    files.append(name)
    return [Pin(*key, tuple(files)) for key, files in sorted(found.items(), key=lambda kv: tuple(str(x) for x in kv[0]))]


def version_key(version: str) -> tuple:
    """Order two versions of ONE source: the numbers, in order. A Debian pre-release ("1.8.0~rc0-2") sorts before its release."""
    version = re.sub(r"^\D+", "", version)     # "v3.2.6" and "RELEASE.2024-..." compare by their numbers
    head, tilde, tail = version.partition("~")
    numbers = lambda text: tuple(int(n) for n in re.findall(r"\d+", text))
    if tilde:
        return (numbers(head), 0, numbers(tail))
    upstream, _, revision = version.partition("-") if re.match(r"^[0-9.]+-\d", version) else (version, "", "")
    return (numbers(upstream), 1, numbers(revision))


def http_fetch(url: str) -> bytes:
    headers = {"User-Agent": "pin-freshness (python-urllib)", "Accept": "application/json"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token and urllib.parse.urlsplit(url).hostname == "api.github.com":
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=TIMEOUT_S) as response:
                return response.read()
        except urllib.error.HTTPError:
            raise                                  # the source answered: asking again changes nothing
        except OSError:
            if attempt == ATTEMPTS:
                raise
            time.sleep(RETRY_WAIT_S * attempt)


def source_url(spec: dict, name: str) -> str:
    """The page a reader opens to check the row."""
    source = spec["source"]
    if source == "pypi":
        return f"https://pypi.org/project/{name}/"
    if source == "dockerhub":
        repo = spec["repository"]
        return (f"https://hub.docker.com/_/{repo.split('/', 1)[1]}/tags" if repo.startswith("library/")
                else f"https://hub.docker.com/r/{repo}/tags")
    if source == "github":
        return f"https://github.com/{spec['repository']}/releases"
    return spec["url"]


def releases(spec: dict, name: str, fetch) -> list:
    """[(version, the tag or release string as the source writes it)] of the stable releases the source lists."""
    source = spec["source"]
    if source == "pypi":
        data = json.loads(fetch(f"https://pypi.org/pypi/{urllib.parse.quote(name)}/json"))
        return [(v, v) for v, files in data["releases"].items()
                if PYPI_STABLE.match(v) and any(not f.get("yanked") for f in files)]
    if source == "apt":
        out, package = [], None
        for line in gzip.decompress(fetch(spec["url"])).decode("utf-8", "replace").splitlines():
            if line.startswith("Package: "):
                package = line[9:].strip()
            elif line.startswith("Version: ") and package == name:
                out.append((line[9:].strip(), line[9:].strip()))
        return out
    stable = re.compile(spec["stable"])
    tags = []
    if source == "dockerhub":
        query = {"page_size": 100, "ordering": "last_updated"}
        if spec.get("name_filter"):
            query["name"] = spec["name_filter"]
        url = f"https://hub.docker.com/v2/repositories/{spec['repository']}/tags?{urllib.parse.urlencode(query)}"
        for _ in range(spec.get("pages", DOCKERHUB_PAGES)):
            data = json.loads(fetch(url))
            tags += [t["name"] for t in data.get("results") or []]
            url = data.get("next")
            if not url:
                break
    elif source == "github":
        for page in range(1, spec.get("pages", GITHUB_PAGES) + 1):
            data = json.loads(fetch(f"https://api.github.com/repos/{spec['repository']}/releases?per_page=100&page={page}"))
            tags += [r["tag_name"] for r in data if not r.get("draft") and not r.get("prerelease")]
            if len(data) < 100:
                break
    else:
        raise ValueError(f"unknown source {source!r}")
    return [(m["v"], t) for t in tags for m in [stable.match(t)] if m]


def _row(pin, status, pinned=None, latest=None, compatible=None, note="", url=""):
    return {"name": pin.name, "kind": pin.kind, "files": list(pin.files), "pinned": pinned or pin.version, "latest_stable": latest,
            "latest_compatible": compatible, "status": status, "note": note, "source": url}


def _exception(constraints: dict, wanted: str | None):
    if not wanted:
        return None
    return next(e for e in constraints["exceptions"] if e["backend"] == wanted)


def _exception_note(line: dict) -> str:
    return f"{line['reason']} ({line['date']}, {line['decided_by']})"


def judge(pin: Pin, sources: dict, constraints: dict, fetch, cache: dict) -> dict:
    """One pin against its source. Nothing here writes a file."""
    if pin.kind == "floating":
        spec = sources["floating"].get(pin.name, {})
        line = _exception(constraints, spec.get("exception"))
        return _row(pin, "floating", pinned=pin.name, note=_exception_note(line) if line else spec.get("note", ""))
    if pin.kind == "pypi":
        spec = dict(sources["packages"].get(pin.name, {}), source="pypi")
    else:
        spec = sources["images" if pin.kind == "image" else "apt"].get(pin.name)
        if spec is None:
            return _row(pin, "unread", note="no entry in pin_sources.json")
        if pin.kind == "image" and spec.get("digest") != pin.digest and not spec.get("own"):
            return _row(pin, "unread", note=f"the files pin digest {pin.digest[:12]}, pin_sources.json names {str(spec.get('digest'))[:12]}: "
                                            f"say which version the new digest is")
    pinned = pin.version or spec.get("version")
    if spec.get("own"):
        return _row(pin, "own", pinned=pinned or (pin.digest or "")[:12], note=spec["own"])
    url = source_url(spec, pin.name)
    key = (spec["source"], spec.get("repository") or spec.get("url"), pin.name if spec["source"] in ("pypi", "apt") else spec.get("stable"))
    try:
        if key not in cache:
            cache[key] = releases(spec, pin.name, fetch)
        listed = cache[key]
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError) as exc:
        return _row(pin, "unread", pinned=pinned, note=f"could not read the source: {type(exc).__name__}: {str(exc)[:120]}", url=url)
    rule = spec.get("compatible") or {}
    usable = [(v, tag) for v, tag in listed if not rule or re.search(rule["tags"], tag)]
    mine = version_key(pinned)
    if not usable or max(version_key(v) for v, _ in usable) < mine:
        return _row(pin, "unread", pinned=pinned, url=url,
                    note=f"the listing read ({len(listed)} stable releases) does not reach the pinned version")
    latest = max(listed, key=lambda r: version_key(r[0]))[0]
    compatible = max(usable, key=lambda r: version_key(r[0]))[0]
    line = _exception(constraints, spec.get("exception"))
    blocker = (f"{rule['because']} (comparator_constraints.json: {rule['constraint']})"
               if rule and version_key(compatible) < version_key(latest) else "")
    if mine < version_key(compatible):
        status = "held" if line else "behind"
        note = _exception_note(line) if line else "no exception line"
    elif blocker:
        status, note = "blocked", blocker
    else:
        status, note = "current", ""
    return _row(pin, status, pinned=pinned, latest=latest, compatible=compatible, note=note, url=url)


def report(fetch=http_fetch, root: Path = HERE, sources: dict | None = None, constraints: dict | None = None, today: str | None = None) -> dict:
    sources = sources if sources is not None else json.loads(SOURCES.read_text(encoding="utf-8"))
    constraints = constraints if constraints is not None else json.loads(CONSTRAINTS.read_text(encoding="utf-8"))
    cache = {}
    rows = [judge(pin, sources, constraints, fetch, cache) for pin in collect_pins(root)]
    return {"read_on": today or datetime.datetime.now(datetime.timezone.utc).date().isoformat(), "pins": rows}


def exit_status(result: dict) -> int:
    statuses = {r["status"] for r in result["pins"]}
    return 1 if "behind" in statuses else 2 if "unread" in statuses else 0


def markdown(result: dict) -> str:
    cell = lambda value: str(value if value not in (None, "") else "-").replace("|", "\\|")
    rows = result["pins"]
    counts = {s: sum(r["status"] == s for r in rows) for s in sorted({r["status"] for r in rows})}
    out = [f"# Pin freshness, read on {result['read_on']} (UTC)", "",
           f"{len(rows)} pins: " + ", ".join(f"{n} {s}" for s, n in counts.items()) + ". No pin was changed.", ""]
    for status, title in (("behind", "Behind the latest compatible release with no exception line"), ("unread", "Not read")):
        hit = [r for r in rows if r["status"] == status]
        if hit:
            out += [f"## {title}", ""] + [f"- `{r['name']}` {cell(r['pinned'])} (latest compatible {cell(r['latest_compatible'])}): {r['note']}"
                                          for r in hit] + [""]
    out += ["## Every pin", "", "| Pin | Pinned | Latest stable | Latest compatible | Status | Blocker, exception, or note | Source |",
            "|---|---|---|---|---|---|---|"]
    order = ("behind", "unread", "held", "blocked", "current", "floating", "own")
    for r in sorted(rows, key=lambda r: (order.index(r["status"]), r["name"])):
        out.append("| " + " | ".join(cell(r[k]) for k in ("name", "pinned", "latest_stable", "latest_compatible", "status", "note", "source")) + " |")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", metavar="PATH", help="also write the report as JSON to PATH")
    ap.add_argument("--list", action="store_true", help="print the pins the files carry and read no source")
    args = ap.parse_args(argv)
    if args.list:
        for pin in collect_pins():
            print(pin.kind, pin.name, pin.version or (pin.digest or "")[:12], ",".join(pin.files))
        return 0
    result = report()
    print(markdown(result), end="")
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return exit_status(result)


if __name__ == "__main__":
    sys.exit(main())
