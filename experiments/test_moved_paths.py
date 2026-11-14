"""Every path the harness names resolves in this repository's layout.

The harness was written for `benchmarks/experiments/` of another repository and found its root by counting directory levels
(`parents[n]`, `../..`). Here it sits one level below the root, as `experiments/`. This test proves that no lookup was left at the old
depth: every module imports, the root constants it defines point at this repository, and every file a module names relative to its
own directory or to the repository root exists. A module that needs a package the hermetic suite does not install is skipped, not failed.

Run with `python -m pytest test_moved_paths.py -q` from this directory.
"""
import ast
import importlib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

THIS = Path(__file__).name
MODULES = sorted(p.stem for p in HERE.glob("*.py") if not p.name.startswith("test_") and p.name != "conftest.py")
TESTS = sorted(p.stem for p in HERE.glob("test_*.py") if p.name != THIS)
SCRIPTS = sorted(HERE.glob("*.sh"))
HARNESS_NAMES = {p.stem for p in HERE.glob("*.py")}

# Named in the code and absent from a clean checkout on purpose: raw output and corpora (generated or downloaded), the staged wheels, the
# runbook of the benchmark host (not copied), the private notes repository, the engine bindings, the sibling site checkout, caches.
ABSENT_OK = ("results", "data", "docker-wheels", "log", "CAMPAIGN.md", ".notes", "bindings", "humem.ai", "__pycache__", ".venv", ".git")
# The python-bindings artifact stays in the repository the harness came from. The code keeps naming it by its path from the repository
# root (benchmarks/python-bindings), so a copy of it put there later is found; nothing else may start with benchmarks/.
ABSENT_PREFIX = ("benchmarks", "python-bindings")


@pytest.fixture
def isolated_imports():
    """Importing a module runs its top level: sparse_cliff_probe sets BENCH_SPARSE_SOURCE=bigann, which would reach every later test that
    starts a subprocess. Put the environment, sys.path and the harness modules this test loaded back as they were."""
    env, path, before = dict(os.environ), list(sys.path), set(sys.modules)
    yield
    os.environ.clear()
    os.environ.update(env)
    sys.path[:] = path
    for loaded in set(sys.modules) - before:
        if loaded in HARNESS_NAMES:
            del sys.modules[loaded]


def _chain(node):
    """`HERE / "a" / "b"` gives ("HERE", ["a", "b"]); `HERE.parent / "a"` is the repository root; anything else gives None."""
    parts = []
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        if not (isinstance(node.right, ast.Constant) and isinstance(node.right.value, str)):
            return None
        parts.append(node.right.value)
        node = node.left
    if parts and isinstance(node, ast.Name) and node.id in ("HERE", "REPO"):
        return node.id, parts[::-1]
    if parts and isinstance(node, ast.Attribute) and node.attr == "parent" and isinstance(node.value, ast.Name) and node.value.id == "HERE":
        return "REPO", parts[::-1]
    return None


def test_the_harness_sits_one_level_below_the_repository_root():
    assert HERE.name == "experiments"
    assert (ROOT / "experiments").samefile(HERE)
    assert (ROOT / "README.md").is_file() and (ROOT / "LICENSE").is_file()
    assert not (ROOT / "benchmarks").exists(), "the old layout is back"


def test_the_copy_is_not_empty():
    # a layout test that finds nothing passes for the wrong reason
    assert len(MODULES) > 50 and len(TESTS) > 50 and len(SCRIPTS) >= 5


@pytest.mark.parametrize("name", MODULES)
def test_the_module_imports_and_its_root_constants_point_here(name, isolated_imports):
    try:
        mod = importlib.import_module(name)
    except ModuleNotFoundError as e:
        if e.name in HARNESS_NAMES:
            raise
        pytest.skip(f"{name} needs {e.name}, which the hermetic suite does not install")
    for attr, want in (("HERE", HERE), ("REPO", ROOT)):
        got = getattr(mod, attr, None)
        if isinstance(got, Path):
            assert got.resolve() == want, f"{name}.{attr} is {got}, expected {want}"


@pytest.mark.parametrize("name", MODULES + TESTS)
def test_every_file_a_module_names_exists(name):
    tree = ast.parse((HERE / f"{name}.py").read_text(encoding="utf-8"))
    base = {"HERE": HERE, "REPO": ROOT}
    missing, checked = [], 0
    for node in ast.walk(tree):
        c = _chain(node)
        if c is None:
            continue
        root_name, parts = c
        if parts[0] in ABSENT_OK or parts[0].startswith(("/", "~")) or any(ch in p for p in parts for ch in "*?{}<>$["):
            continue
        if tuple(parts[:2]) == ABSENT_PREFIX or (root_name == "REPO" and parts == ["benchmarks"]):
            continue
        checked += 1
        target = base[root_name].joinpath(*parts)
        if not target.exists():
            missing.append(f"{root_name} / {'/'.join(parts)}")
    assert not missing, f"{name} names files that are not in the repository: {sorted(set(missing))}"


@pytest.mark.parametrize("name", MODULES + TESTS)
def test_no_lookup_is_left_at_the_old_depth(name):
    """In the old layout the root was parents[1] and a sibling checkout parents[2]; here they are parent and parents[1]."""
    src = (HERE / f"{name}.py").read_text(encoding="utf-8")
    assert not re.search(r"parents\[[2-9]\]", src), f"{name} climbs more levels than the layout has"
    assert "parent.parent.parent" not in src


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_shell_scripts_parse_and_find_the_root_one_level_up(script):
    r = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "/../.." not in script.read_text(encoding="utf-8"), f"{script.name} climbs two levels"
