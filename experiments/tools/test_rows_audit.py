"""Test of rows_audit.py. The script once shipped without `import collections` and `import json` and died with a NameError on its first line of work (found in the
2026-11-14 landing rehearsal), so the test RUNS it, on a tiny directory of rows, the way its docstring says."""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
row = lambda rep, **kw: dict({"backend": "arcadedb_graph_embedded", "lane": "l2", "scale": "sf1", "workload": "oltp", "durability_class": "relaxed", "rep": rep, "rc": 0}, **kw)


def _fresh(root):
    fresh = root / "fresh"
    fresh.mkdir()
    files = {"runs_fourarm-wt_jvm": [row(1), row(2), row(3)], "runs_fourarm-catchup-wt_jvm": [], "runs_fourarm-wt_native": [row(1), row(2, error="x")],
             "runs_fourarm-catchup-wt_native": [row(2)]}
    for name, rows in files.items():
        (fresh / (name + ".jsonl")).write_text("".join(json.dumps(r) + "\n" for r in rows))
    return fresh


def _check(done):
    assert done.returncode == 0, done.stderr[-600:]
    assert "JVM embedded" in done.stdout and "cells with 3 clean reps:   1" in done.stdout, done.stdout
    assert "NAT embedded" in done.stdout and "below 3:   1" in done.stdout, done.stdout   # native: reps 1 and 2 clean, rep 3 never run


def test_the_audit_runs_on_the_fresh_directory_beside_it(tmp_path):
    _fresh(tmp_path)
    _check(subprocess.run([sys.executable, "-I", str(HERE / "rows_audit.py")], cwd=tmp_path, capture_output=True, text=True))


def test_the_audit_takes_the_directory_as_an_argument(tmp_path):
    fresh = _fresh(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _check(subprocess.run([sys.executable, "-I", str(HERE / "rows_audit.py"), str(fresh)], cwd=elsewhere, capture_output=True, text=True))
