"""The "Run it yourself" guide (docs/reproduce.md, humemai/mmdbbench#102) cannot name something that no longer exists.

Every fenced block that the guide marks `<!-- runnable: NAME -->` is the command a reader pastes and the command
`.github/workflows/reproduce-smoke.yml` runs. A rename of a script, a backend id, a scale or an environment variable, or a drift
of a pinned package, makes the guide wrong; these tests fail in the same pull request instead of at the next reader.

No docker, no data, no network, no engine runs here: the tests read the guide and the sources.
"""
import os
import re
import shlex
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
GUIDE = os.path.join(REPO, "docs", "reproduce.md")
sys.path.insert(0, os.path.join(HERE, "tools"))
import guide_blocks  # noqa: E402

with open(GUIDE, encoding="utf-8") as _f:
    GUIDE_TEXT = _f.read()
BLOCKS = guide_blocks.extract(GUIDE_TEXT)

SOURCES = {}
for _n in sorted(os.listdir(HERE)):
    if _n.endswith((".py", ".sh")):
        with open(os.path.join(HERE, _n), encoding="utf-8", errors="replace") as _f:
            SOURCES[_n] = _f.read()
ALL_SOURCE = "\n".join(SOURCES.values())
BUILD_IMAGES = SOURCES["build_images.sh"]


def commands():
    """[(block name, cwd relative to the repo root, tokens)] in file order; `cd` changes the cwd for the lines after it, as in a shell
    that runs the blocks one after the other (the order the workflow joins them in)."""
    cwd = ""
    out = []
    for name, _lang, code in BLOCKS:
        for raw in code.replace("\\\n", " ").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            toks = shlex.split(line, comments=True)
            if not toks:
                continue
            if toks[0] == "cd":
                cwd = os.path.normpath(os.path.join(cwd, toks[1])) if toks[1] != "-" else cwd
                cwd = "" if cwd == "." else cwd
                continue
            out.append((name, cwd, toks))
    return out


COMMANDS = commands()


def test_the_guide_has_runnable_blocks():
    names = [n for n, _, _ in BLOCKS]
    assert len(names) >= 4, names
    for want in ("e2-arcadedb",):
        assert want in names, f"the smoke workflow needs the block '{want}'"


def test_every_script_a_block_names_exists():
    missing = []
    for name, cwd, toks in COMMANDS:
        skip_next = False
        for t in toks:
            if skip_next:
                skip_next = False
                continue
            if t in ("--out", "-o", "--samples", "--data"):
                skip_next = True
                continue
            if t.startswith("-") or "$" in t or "://" in t or "=" in t.split("/")[0]:
                continue
            if t.endswith((".py", ".sh")):
                path = os.path.join(REPO, cwd, t)
                if not os.path.isfile(path):
                    missing.append(f"{name}: {os.path.join(cwd, t)}")
    assert not missing, "the guide names files that are not in the repository:\n" + "\n".join(missing)


def _script_of(toks, i):
    for j in range(i, -1, -1):
        if toks[j].endswith(".py") and not toks[j].startswith("-"):
            return toks[j]
    return None


def test_every_backend_and_scale_exists_in_its_script():
    """`--backend X` must be a backend id its lane script registers (`name = "X"` in a class of `BACKENDS`); `--scale X` must be a
    scale of the runner (`MEM_BY_SCALE`, which every lane's scale is in). A script without `BACKENDS` (the comparison tool) is not a lane."""
    bad = []
    runner = SOURCES["runner.py"]
    for name, cwd, toks in COMMANDS:
        for i, t in enumerate(toks):
            if t in ("--backend", "--scale") and i + 1 < len(toks):
                script = _script_of(toks, i)
                if script is None:
                    continue
                path = os.path.join(REPO, cwd, script)
                if not os.path.isfile(path):
                    continue
                with open(path, encoding="utf-8") as f:
                    src = f.read()
                if "BACKENDS" not in src:
                    continue
                val = toks[i + 1]
                if t == "--backend":
                    ok = re.search(r"name\s*=\s*[\"']" + re.escape(val) + r"[\"']", src)
                else:
                    ok = re.search(r"[\"']" + re.escape(val) + r"[\"']\s*:", runner)
                if not ok:
                    bad.append(f"{name}: {script} {t} {val}")
    assert not bad, "the guide names a backend or a scale its script does not know:\n" + "\n".join(bad)


def test_every_environment_variable_is_read_by_the_harness():
    bad = []
    for name, _cwd, toks in COMMANDS:
        names = []
        if toks[0] == "export":
            names = [t.split("=", 1)[0] for t in toks[1:] if "=" in t]
        else:
            names = [t.split("=", 1)[0] for t in toks if re.match(r"^[A-Z][A-Z0-9_]*=", t)]
        for n in names:
            if n in ("HOME", "PATH"):
                continue
            if n not in ALL_SOURCE:
                bad.append(f"{name}: {n}")
    assert not bad, "the guide sets variables that no script of experiments/ mentions:\n" + "\n".join(bad)


def test_pinned_packages_are_the_pins_of_the_images():
    """The harness's own libraries (numpy, pandas, pyarrow, duckdb, ...) are pinned in build_images.sh; the guide installs the same
    versions, so a re-pin there that forgets the guide fails here (the freshness rule of #175 applies to the guide too)."""
    bad = []
    for name, _cwd, toks in COMMANDS:
        for i, t in enumerate(toks):
            if t == "--with" and i + 1 < len(toks) and "==" in toks[i + 1]:
                pkg, ver = toks[i + 1].split("==", 1)
                if pkg in ("arcadedb-jvm", "arcadedb"):
                    continue
                pinned = set(re.findall(re.escape(pkg) + r"==([0-9][\w.]*)", BUILD_IMAGES))
                if pinned and ver not in pinned:
                    bad.append(f"{name}: {pkg}=={ver}, build_images.sh pins {sorted(pinned)}")
    assert not bad, "\n".join(bad)


def test_the_engine_version_is_one_the_published_rows_carry():
    """The guide names the ArcadeDB wheel that the published rows ran; after a landing of a newer release the version moves
    here in the same pull request (PUBLISHING.md, landing)."""
    pd = pytest.importorskip("pandas")
    versions = set(pd.read_csv(os.path.join(HERE, "results", "runs_paper.csv"), usecols=["engine_version"])["engine_version"].dropna().astype(str))
    wanted = set()
    for _name, _cwd, toks in COMMANDS:
        for i, t in enumerate(toks):
            if t == "--with" and i + 1 < len(toks):
                m = re.match(r"^arcadedb(?:-jvm)?==(.+)$", toks[i + 1])
                if m:
                    wanted.add(m.group(1))
    assert wanted, "no block installs an ArcadeDB wheel"
    for v in wanted:
        assert v in versions, f"the guide installs ArcadeDB {v}; the published rows carry {sorted(versions)}"


def test_the_cost_table_is_the_one_the_rows_give():
    """#121: the time and memory per small cell are generated from runs_paper.csv by tools/small_cell_cost.py, never typed."""
    pytest.importorskip("pandas")
    import small_cell_cost
    table = small_cell_cost.render(small_cell_cost.table())
    assert table in GUIDE_TEXT, "paste this table into docs/reproduce.md (python tools/small_cell_cost.py):\n" + table


def test_the_guide_says_uv_add_never_pip_install():
    assert "pip install" not in GUIDE_TEXT
    assert "uv pip" not in GUIDE_TEXT


def test_the_guide_is_in_the_navigation_and_the_readme_links_it():
    with open(os.path.join(REPO, "mkdocs.yml"), encoding="utf-8") as f:
        assert "reproduce.md" in f.read()
    with open(os.path.join(REPO, "README.md"), encoding="utf-8") as f:
        assert "docs/reproduce.md" in f.read()


def test_extract_rejects_a_mark_without_a_block():
    with pytest.raises(ValueError):
        guide_blocks.extract("<!-- runnable: x -->\n\nsome text\n")
    with pytest.raises(ValueError):
        guide_blocks.extract("<!-- runnable: x -->\n```bash\na\n```\n<!-- runnable: x -->\n```bash\nb\n```\n")
    assert guide_blocks.extract("<!-- runnable: x -->\n\n```bash\na\n```\n") == [("x", "bash", "a\n")]
