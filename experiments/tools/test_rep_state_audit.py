"""Test of rep_state_audit.sh. The comparator section read only rep-state-2026-11-e85469273.tsv, so the PG+AGE cells that were rerun at n=3 (the ok reps are in the
-comprerun file) printed as ok=0 (found in the 2026-11-14 landing rehearsal). The script is run with HOME pointed at a directory of tiny rep-state files."""
import os
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
tsv = lambda cell, rs, st: "".join(f"{cell}\t{r}\t{st}\n" for r in rs)


def _run(d, **env):
    return subprocess.run(["bash", str(HERE / "rep_state_audit.sh")], env={"HOME": str(d), "PATH": os.environ["PATH"], **env}, capture_output=True, text=True)


def _write(d):
    (d / "rep-state-2026-11-e85469273.tsv").write_text(tsv("l1/sf1/pgage/oltp", (1, 2, 3), "fail") + tsv("l1/sf1/other/oltp", (1, 2, 3), "ok"))
    (d / "rep-state-2026-11-e85469273-comprerun.tsv").write_text(tsv("l1/sf1/pgage/oltp", (1, 2, 3), "ok"))


def test_the_comprerun_ok_reps_count_for_the_comparators(tmp_path):
    _write(tmp_path)
    done = _run(tmp_path)
    assert done.returncode == 0, done.stderr
    section = done.stdout.split("== comparators and the original pin, e85469273", 1)[1].split("note:", 1)[0]
    assert "pgage" not in section, "the -comprerun ok reps must count:" + section
    assert "cells in the union: 2" in section, section


def test_n_and_the_directory_come_from_the_environment(tmp_path):
    (tmp_path / "elsewhere").mkdir()
    _write(tmp_path / "elsewhere")
    done = _run(tmp_path, REP_STATE_DIR=str(tmp_path / "elsewhere"), N="4")
    assert done.returncode == 0, done.stderr
    assert "(cells with fewer than 4 ok reps)" in done.stdout
    section = done.stdout.split("== comparators and the original pin, e85469273", 1)[1].split("note:", 1)[0]
    assert "l1/sf1/other/oltp" in section and "ok=3" in section, section      # three ok reps are fewer than four
