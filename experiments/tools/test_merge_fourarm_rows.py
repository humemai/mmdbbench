"""Tests of merge_fourarm_rows: the merge rule, the build in the key, and that --pull leaves no temporary directory behind (the scp is replaced by a local copy)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import merge_fourarm_rows as m  # noqa: E402


def w(d, name, rows):
    p = os.path.join(d, name)
    open(p, "w").write("".join(json.dumps(r) + "\n" for r in rows))
    return p


def test_a_clean_row_beats_error_rows_and_the_last_clean_row_wins(tmp_path):
    d = str(tmp_path)
    live_n = w(d, "a", [{"run_id": "x_r1", "v": 1}, {"run_id": "tw_r1", "error": "setting x was requested as false"}, {"run_id": "st_r1", "error": "server_not_ready"},
                        {"run_id": "only_err", "error": "e1"}])
    cu = w(d, "b", [{"run_id": "tw_r1", "v": 2}, {"run_id": "st_r1", "v": 3}, {"run_id": "tw_r1", "v": 4}, {"run_id": "only_err", "error": "e2"},
                    {"run_id": "x_r1", "error": "late failure"}])
    rows, seen = m.merge([live_n, cu])
    by = {r["run_id"]: r for r in rows}
    assert [r["run_id"] for r in rows] == ["x_r1", "tw_r1", "st_r1", "only_err"], rows
    assert by["x_r1"].get("v") == 1, "a clean row must not be replaced by a later error row"
    assert by["tw_r1"]["v"] == 4, "the last clean row of a run_id wins"
    assert by["st_r1"]["v"] == 3, "the catch-up row replaces the live error row"
    assert by["only_err"]["error"] == "e2", "an error-only run_id keeps its last error row"
    assert seen[live_n] == 4 and seen[cu] == 5


def test_the_jvm_and_the_native_chain_share_run_ids_and_both_stay(tmp_path):
    # the two chains write the SAME run_id for the same cell; run_id alone as the key kept 186 of 365 rows of the 2026-11-14 rehearsal
    d = str(tmp_path)
    jvm = w(d, "jvm", [{"run_id": "l2_graph_oltp_sf1_r1", "engine_backend": "jvm", "v": 1}, {"run_id": "l2_graph_oltp_sf1_r2", "engine_backend": "jvm", "v": 2}])
    nat = w(d, "nat", [{"run_id": "l2_graph_oltp_sf1_r1", "engine_backend": "native", "v": 3}, {"run_id": "l2_graph_oltp_sf1_r2", "engine_backend": "native", "error": "e"}])
    rows, _ = m.merge([jvm, nat])
    assert sorted((r["engine_backend"], r["run_id"][-2:]) for r in rows) == [("jvm", "r1"), ("jvm", "r2"), ("native", "r1"), ("native", "r2")], rows
    assert {(r["engine_backend"], r["run_id"][-2:]): r.get("v") for r in rows}[("jvm", "r1")] == 1, "a native row must not replace the JVM row of the same run_id"


def fake_scp_factory(src_dir, fail_on=None):
    def fake(cmd, *a, **k):
        remote, dst = cmd[-2], cmd[-1]
        base = remote.split(":", 1)[1].split("/benchmarks/")[0]
        if fail_on and fail_on in base:
            return subprocess.CompletedProcess(cmd, 1)
        src = os.path.join(src_dir, os.path.basename(base) if "catchup" not in base else "catchup-" + os.path.basename(base))
        if not os.path.exists(src):
            return subprocess.CompletedProcess(cmd, 1)
        shutil.copy(src, dst)
        return subprocess.CompletedProcess(cmd, 0)
    return fake


@pytest.mark.parametrize("fail_on,expect_exit", [(None, 0), ("fourarm-wt/native", 1)])
def test_pull_leaves_no_temporary_directory_behind(tmp_path, monkeypatch, fail_on, expect_exit):
    d, scratch = tmp_path / "src", tmp_path / "scratch"
    d.mkdir()
    scratch.mkdir()
    w(str(d), "jvm", [{"run_id": "a_r1", "engine_backend": "jvm"}])
    w(str(d), "native", [{"run_id": "a_r1", "engine_backend": "native"}])
    out = str(d / "out.jsonl")
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))      # mkdtemp now creates inside `scratch`, so a leak is visible there
    monkeypatch.setattr(sys, "argv", ["merge_fourarm_rows.py", "--out", out, "--pull", "abc123def"])
    monkeypatch.setattr(m.subprocess, "run", fake_scp_factory(str(d), fail_on))
    try:
        rc = m.main()
    except SystemExit as e:
        rc = 1 if e.code else 0
    assert rc == expect_exit, (fail_on, rc)
    assert os.listdir(scratch) == [], f"--pull left {os.listdir(scratch)} behind (fail_on={fail_on})"
    if expect_exit == 0:
        assert len(open(out).read().splitlines()) == 2, "both builds' rows of the shared run_id must be written"


def test_the_defaults_name_the_four_remote_directories_and_the_host():
    assert len(m.PULL) == 4 and sum("catchup" in p for p in m.PULL) == 2
    assert m.HOST == "mini" and m.RESULTS == "benchmarks/experiments/results"
