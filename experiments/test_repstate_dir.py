"""The rep-state directory of a rehearsal (humemai/mmdbbench#162): stages generated with --repstate-dir neither read nor write the real state file of their pin.
Run with `python -m pytest test_repstate_dir.py -q` from this directory. Only drafts are written; the rep helpers of a generated stage run in bash.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import test_stage_generator_2611 as T  # noqa: E402

LABEL = "l1tpc/tpch1/arcadedb_embedded/oltp"
PIN = "abc123def"


def _generate(out, build, *extra):
    wheel = T.REL_WHEEL.replace("arcadedb_embedded-", "arcadedb_jvm-" if build == "jvm" else "arcadedb-")
    return T.run(T._release_args(**{"--wheel-name": wheel, "--wheel-url": "https://files.pythonhosted.org/packages/x/" + wheel})
                 + ["--after", "none", "--id-prefix", "qF", "--profile", "final-small", "--out", str(out), *extra])


def _lane_stages(directory):
    return [f for f in sorted(directory.glob("*.sh")) if re.search(r"^REPSTATE=", f.read_text(), re.M)]


@pytest.fixture(scope="module", params=["jvm", "native"])
def chains(request, tmp_path_factory):
    """(build, drafts without the option, drafts with it, the directory the option names)"""
    build = request.param
    root = tmp_path_factory.mktemp(build)
    baked = root / "baked"
    plain, rehearsal = root / "plain", root / "rehearsal"
    for out, extra in ((plain, []), (rehearsal, ["--repstate-dir", str(baked)])):
        r = _generate(out, build, *extra)
        assert r.returncode == 0, r.stdout[-800:] + r.stderr[-800:]
    return build, plain, rehearsal, baked


def _sh(stage, home, body, env=None):
    m = re.search(r"^REPSTATE(?:_DIR)?=.*?^rep_gate\(\) \{.*?^\}\n", stage.read_text(), re.M | re.S)
    assert m, "the rep helpers are not in the stage"
    script = f'set -u\nHOME="$1"; PIN={PIN}; PASS=1; REPS=3; ID=qF01\nsay() {{ echo "$*"; }}\n' + m.group(0) + body
    return subprocess.run(["bash", "-c", script, "bash", str(home)], capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin", **(env or {})})


def test_without_the_option_the_state_file_stays_in_home(chains):
    build, plain, _rehearsal, _baked = chains
    stages = _lane_stages(plain)
    assert stages
    for f in stages:
        t = f.read_text()
        assert re.findall(r"^REPSTATE=(.*)$", t, re.M) == [f"$HOME/rep-state-2026-11-$PIN-{build}.tsv"], f.name
        assert "BENCH_REPSTATE_DIR" not in t, f.name


def test_with_the_option_every_stage_takes_the_directory_and_nothing_else_changes(chains):
    build, plain, rehearsal, baked = chains
    stages = _lane_stages(rehearsal)
    assert [f.name for f in stages] == [f.name for f in _lane_stages(plain)]
    for f in stages:
        t = f.read_text()
        assert re.findall(r"^REPSTATE=(.*)$", t, re.M) == [f"$REPSTATE_DIR/rep-state-2026-11-$PIN-{build}.tsv"], f.name
        assert f"\nREPSTATE_DIR=${{BENCH_REPSTATE_DIR:-{baked}}}" in t and "$HOME/rep-state" not in t, f.name
        assert subprocess.run(["bash", "-n", str(f)], capture_output=True, text=True).returncode == 0, f.name
        # the only lines that differ from the stage without the option are the rep-state ones
        before = (plain / f.name).read_text().splitlines()
        assert [ln for ln in before if ln not in t.splitlines()] == [f"REPSTATE=$HOME/rep-state-2026-11-$PIN-{build}.tsv"], f.name


def test_a_rehearsal_neither_reads_nor_writes_the_real_state_of_its_pin(chains, tmp_path):
    build, plain, rehearsal, baked = chains
    home, scratch = tmp_path / "home", tmp_path / "scratch"
    home.mkdir()
    real = home / f"rep-state-2026-11-{PIN}-{build}.tsv"
    real.write_text(f"{LABEL}\t1\tok\n")
    # the stage without the option reads the real file: its clean cell is not run again
    assert _sh(_lane_stages(plain)[0], home, f'rep_gate "{LABEL}"').returncode == 1
    # the rehearsal stage runs the cell, and what it notes (headline and twin) lands in the named directory, which it creates
    stage = _lane_stages(rehearsal)[0]
    for env, where in (({}, baked), ({"BENCH_REPSTATE_DIR": str(scratch)}, scratch)):   # the variable wins over the generated directory
        for old in where.glob("*"):   # `baked` is shared by the stages of the module fixture
            old.unlink()
        r = _sh(stage, home, f'rep_gate "{LABEL}" || exit 9\nrep_note "{LABEL}" 1 ok\nrep_twin_only "{LABEL}" 1 3', env)
        assert r.returncode == 0, r.stdout + r.stderr
        assert sorted(p.name for p in where.iterdir()) == [f"rep-state-2026-11-{PIN}-{build}-pgwire.tsv", real.name]
    assert real.read_text() == f"{LABEL}\t1\tok\n" and [p.name for p in home.iterdir()] == [real.name]
    # the twin-only catch-ups move to their own files inside the same directory
    r = _sh(stage, home, 'echo "$REPSTATE"', {"BENCH_REPSTATE_DIR": str(scratch), "FOURARM_CLIENTS": "lean"})
    assert r.stdout.strip() == str(scratch / f"rep-state-2026-11-{PIN}-{build}-lean.tsv"), r.stdout + r.stderr


def test_a_directory_that_cannot_be_made_stops_the_stage(chains, tmp_path):
    _build, _plain, rehearsal, _baked = chains
    blocker = tmp_path / "a-file"
    blocker.write_text("")
    r = _sh(_lane_stages(rehearsal)[0], tmp_path, "echo reached", {"BENCH_REPSTATE_DIR": str(blocker / "sub")})
    assert r.returncode == 1 and "ABORT: no rep-state directory" in r.stdout and "reached" not in r.stdout, r.stdout + r.stderr


@pytest.mark.parametrize("bad", ["", "relative/dir", "/a b", "/a;rm", "/a/../b", "~root/x"])
def test_a_value_bash_could_read_as_more_than_an_absolute_path_is_refused(tmp_path, bad):
    out = tmp_path / "o"
    r = _generate(out, "jvm", f"--repstate-dir={bad}")
    assert r.returncode != 0 and "REFUSING: --repstate-dir" in r.stdout + r.stderr, r.stdout[-400:] + r.stderr[-400:]
    assert not out.exists()
