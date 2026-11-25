"""pin_freshness.py (humemai/mmdbbench#175, item 1): the pins it reads from the files, the data it judges them with, and what it says.

No network: the sources are faked. Run with `python -m pytest test_pin_freshness.py -q` from this directory.
"""
import gzip
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pin_freshness as P  # noqa: E402

SOURCES = json.loads(P.SOURCES.read_text(encoding="utf-8"))
CONSTRAINTS = json.loads(P.CONSTRAINTS.read_text(encoding="utf-8"))
DIGEST, OTHER = "a" * 64, "b" * 64


def _code_lines(name):
    return [line for line in (HERE / name).read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#")]


# ------------------------------------------------------------------ the pins, as the files carry them
def test_every_image_digest_in_the_code_is_a_pin():
    collected = {p.digest for p in P.collect_pins() if p.kind == "image"}
    in_code = {d for name in P.PIN_FILES for line in _code_lines(name) for d in re.findall(r"@sha256:([0-9a-f]{64})", line)}
    assert in_code and in_code == collected


def test_the_packages_the_apt_pin_the_jpype_pin_and_the_floating_base_are_read():
    names = {(p.kind, p.name) for p in P.collect_pins()}
    for want in (("pypi", "duckdb"), ("pypi", "psycopg"), ("pypi", "pymilvus"), ("pypi", "jpype1"), ("pypi", "arcadedb-driver"),
                 ("apt", "postgresql-18-age"), ("floating", "python:3.12-slim"), ("image", "postgres"),
                 ("image", "mongodb/mongodb-community-search")):
        assert want in names, want


def test_a_pin_in_a_comment_is_not_a_pin_and_python_comparisons_are_not_packages(tmp_path):
    root = _root(tmp_path, {"build_images.sh": f"# old==9.9 x@sha256:{OTHER}\nPKGS=\"alpha==1.0 beta[extra]==2.0\"  # gamma==3.0\n",
                            "runner.py": f"if rep==1:\n    image = \"repo/app@sha256:{DIGEST}\"  # was repo/app@sha256:{OTHER}\n"})
    assert [(p.kind, p.name, p.version, p.digest) for p in P.collect_pins(root)] == [
        ("image", "repo/app", None, DIGEST), ("pypi", "alpha", "1.0", None), ("pypi", "beta", "2.0", None)]


# ------------------------------------------------------------------ the data holds to the files
def test_every_image_and_apt_pin_has_an_entry_that_names_the_version_of_its_digest():
    pins = P.collect_pins()
    for p in (p for p in pins if p.kind == "image"):
        spec = SOURCES["images"].get(p.name)
        assert spec, f"{p.name}: no entry in pin_sources.json"
        if not spec.get("own"):
            assert spec["digest"] == p.digest, f"{p.name}: the files pin another digest; say in pin_sources.json which version it is"
            assert spec["version"] and re.compile(spec["stable"])
    for section, kind in (("images", "image"), ("apt", "apt"), ("floating", "floating")):
        assert set(SOURCES[section]) == {p.name for p in pins if p.kind == kind}, f"{section}: an entry no file pins, or a pin with none"
    assert set(SOURCES["packages"]) <= {p.name for p in pins if p.kind == "pypi"}


def test_every_exception_and_constraint_an_entry_names_exists_and_names_the_pinned_version():
    exceptions = {e["backend"]: e for e in CONSTRAINTS["exceptions"]}
    components = {c["component"] for c in CONSTRAINTS["constraints"]}
    pins = P.collect_pins()
    for section in ("images", "packages", "apt", "floating"):
        for name, spec in SOURCES[section].items():
            if "compatible" in spec:
                assert spec["compatible"]["constraint"] in components, (name, spec["compatible"]["constraint"])
                assert re.compile(spec["compatible"]["tags"]) and spec["compatible"]["because"]
            if "exception" not in spec:
                continue
            assert spec["exception"] in exceptions, (name, spec["exception"])
            named = exceptions[spec["exception"]]["pinned"]
            if section == "images":
                versions = [spec["version"]]
            elif section == "floating":
                versions = [name]
            else:
                versions = [p.version.split("~")[0] for p in pins if p.name == name]
            assert any(v in named for v in versions), f"{name}: the exception line names {named!r}, the files pin {versions}: a stale line"


# ------------------------------------------------------------------ what it says
def _root(tmp_path, contents):
    for name in P.PIN_FILES:
        (tmp_path / name).write_text(contents.get(name, ""), encoding="utf-8")
    return tmp_path


def _pypi(*versions, yanked=()):
    return json.dumps({"releases": {v: [{"yanked": v in yanked}] for v in versions}}).encode()


def _hub(tags, next_url=None):
    return json.dumps({"results": [{"name": t} for t in tags], "next": next_url}).encode()


def _fetcher(answers):
    def fetch(url):
        for part, body in answers.items():
            if part in url:
                if isinstance(body, Exception):
                    raise body
                return body
        raise AssertionError(f"unexpected read of {url}")
    return fetch


def _case(tmp_path):
    root = _root(tmp_path, {
        "build_images.sh": 'PKGS="newest==2.0 stale==1.0 kept==1.0 gone==1.0 short==5.0 mine==0.1"\n',
        "Dockerfile.pgage": f"FROM db@sha256:{DIGEST}\nRUN apt-get install -y postgresql-18-ext=1.0.0~rc0-1\n"})
    sources = {
        "images": {"db": {"digest": DIGEST, "version": "18.7", "source": "dockerhub", "repository": "library/db",
                          "stable": r"^(?P<v>\d+\.\d+)$",
                          "compatible": {"tags": r"^18\.", "because": "the extension stops at 18", "constraint": "ext"}}},
        "packages": {"kept": {"exception": "Kept"}, "mine": {"own": "ours"}},
        "apt": {"postgresql-18-ext": {"source": "apt", "url": "https://apt.example/Packages.gz"}},
        "floating": {}}
    constraints = {"constraints": [{"component": "ext"}],
                   "exceptions": [{"backend": "Kept", "pinned": "1.0", "reason": "a major", "date": "2026-01-01", "decided_by": "someone"}]}
    packages = "Package: other\nVersion: 9\n\nPackage: postgresql-18-ext\nVersion: 1.0.0~rc0-1\n\nPackage: postgresql-18-ext\nVersion: 1.0.0-1\n"
    answers = {
        "/newest/": _pypi("1.0", "2.0", "3.0rc1", "2.5", yanked=("2.5",)),
        "/stale/": _pypi("1.0", "1.2", "1.10"),
        "/kept/": _pypi("1.0", "2.0"),
        "/gone/": OSError("no route"),
        "/short/": _pypi("1.0", "2.0"),
        "library/db/tags?": _hub(["19.0", "19beta1", "latest"], "https://hub.example/page2"),
        "hub.example/page2": _hub(["18.7", "18.6"]),
        "apt.example": gzip.compress(packages.encode()),
    }
    return root, sources, constraints, answers


def test_each_status_says_what_it_is_and_the_report_carries_the_date_and_the_sources(tmp_path):
    root, sources, constraints, answers = _case(tmp_path)
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    result = P.report(fetch=_fetcher(answers), root=root, sources=sources, constraints=constraints, today="2026-02-03")
    rows = {r["name"]: r for r in result["pins"]}
    assert {n: r["status"] for n, r in rows.items()} == {
        "newest": "current", "stale": "behind", "kept": "held", "gone": "unread", "short": "unread", "mine": "own",
        "db": "blocked", "postgresql-18-ext": "behind"}
    assert rows["newest"]["latest_stable"] == "2.0"                       # neither the release candidate nor the yanked release
    assert rows["stale"]["latest_compatible"] == "1.10"                   # numbers, not text
    assert (rows["db"]["latest_stable"], rows["db"]["latest_compatible"]) == ("19.0", "18.7") and "stops at 18" in rows["db"]["note"]
    assert "a major (2026-01-01, someone)" == rows["kept"]["note"]
    assert rows["postgresql-18-ext"]["latest_compatible"] == "1.0.0-1"    # the release is newer than its release candidate
    assert P.exit_status(result) == 1
    text = P.markdown(result)
    assert "2026-02-03" in text and "https://pypi.org/project/stale/" in text and "https://hub.docker.com/_/db/tags" in text
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before     # a report never changes a pin


def test_the_exit_status_is_behind_before_unread_before_clean():
    rows = lambda *statuses: {"pins": [{"status": s} for s in statuses]}
    assert P.exit_status(rows("current", "unread", "behind")) == 1
    assert P.exit_status(rows("current", "unread", "held")) == 2
    assert P.exit_status(rows("current", "blocked", "held", "own", "floating")) == 0


def test_a_new_digest_with_the_old_version_is_not_judged(tmp_path):
    root, sources, constraints, answers = _case(tmp_path)
    sources["images"]["db"]["digest"] = OTHER
    result = P.report(fetch=_fetcher(answers), root=root, sources=sources, constraints=constraints, today="2026-02-03")
    row = next(r for r in result["pins"] if r["name"] == "db")
    assert row["status"] == "unread" and "say which version" in row["note"]


def test_versions_of_one_source_order_by_their_numbers():
    for older, newer in (("18.7", "18.10"), ("v3.2.6", "v4.0.1"), ("1.8.0~rc0-2.pgdg12+2", "1.8.0-1.pgdg12+1"),
                         ("1.8.0~rc0-2.pgdg12+1", "1.8.0~rc0-2.pgdg12+2"),
                         ("RELEASE.2024-12-18T13-15-44Z", "RELEASE.2025-04-08T15-41-24Z")):
        assert P.version_key(older) < P.version_key(newer), (older, newer)
