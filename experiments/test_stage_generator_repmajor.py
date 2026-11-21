"""make_2611_stages.py emits the subset REP-MAJOR and in engine priority order (the user, 2026-10-23: "order the comparators in
priority ... do n=1 for all dbs and then do the n=2, etc.").

Run with `python -m pytest test_stage_generator_repmajor.py -q` from this directory.

Pass 1 of every stage first (core lanes, then the second list), then pass 2, then pass 3. Inside a lane the engines run in
ENGINE_PRIORITY. A stage runs one repetition (`--only-reps $PASS`); a pass above 1 runs a cell only when rep 1 of it was clean
(the rep-1-first rule), and the state that says which reps exist is a file, so a pass can be stopped and the next one resumed
with no regeneration. The bash is exercised for real here, against a stub runner.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import make_2611_stages as G  # noqa: E402
from test_stage_generator_2611 import run, waits  # noqa: E402


@pytest.fixture(scope="module")
def chain(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("rm")
    out = tmp / "stages"
    r = run(["--no-tiers", "--profile", "full", "--second-list", "--after", "none", "--status-file", "none", "--reps", "3", "--out", str(out)], tmp)   # the plain rep-major chain; the tiered one is tested in test_stage_generator_2611.py
    assert r.returncode == 0, r.stdout[-600:] + r.stderr[-600:]
    return out


def stage_pass(path):
    return int(re.search(r"^PASS=(\d+)", path.read_text(), re.M).group(1))


def test_the_chain_is_pass_1_of_every_stage_then_pass_2_then_pass_3(chain):
    files = sorted(chain.glob("*.sh"))
    passes = [stage_pass(f) for f in files]
    assert passes == sorted(passes) and set(passes) == {1, 2, 3}
    per_pass = [passes.count(p) for p in (1, 2, 3)]
    assert per_pass[0] >= 10 and per_pass[1] <= per_pass[0] and per_pass[2] <= per_pass[1]
    # the stages of a later pass are pass-1 stages, in the same order
    def roster(f):
        return re.search(r'^BACKENDS="([^"]*)"', f.read_text(), re.M).group(1)
    first = [roster(f) for f in files if stage_pass(f) == 1]
    second = [roster(f) for f in files if stage_pass(f) == 2]
    it = iter(first)
    assert all(any(r == x for x in it) for r in second)
    for prev, cur in zip(files, files[1:]):
        assert waits(cur) == [prev.stem]
    assert "rep pass 2 of 3" in files[per_pass[0]].read_text()


def test_every_cell_runs_one_rep_and_the_state_file_drives_the_passes(chain):
    for f in chain.glob("*.sh"):
        t = f.read_text()
        assert '--only-reps "$PASS"' in t and "--only-reps 1 " not in t and 'seq -s, 2 "$REPS"' not in t, f.name
        assert "rep_gate" in t and "REPSTATE=$HOME/rep-state-2026-11-$PIN.tsv" in t


def test_engines_run_in_priority_order_inside_every_stage(chain):
    for f in chain.glob("*.sh"):
        bes = re.search(r'^BACKENDS="([^"]*)"', f.read_text(), re.M).group(1).split()
        ranks = [G.engine_rank(b) for b in bes]
        assert ranks == sorted(ranks), (f.name, bes)
    # the stated order, on the documents lane that holds the most engines
    spec = next(s for s in G.subset_specs(G.parse_engines(None, "comparators"), G.parse_lanes("documents", False)))
    engs = []
    for b in G.stage_backends(spec):
        e = G.engine_of(b)
        if not engs or engs[-1] != e:
            engs.append(e)
    want = [e for e in G.ENGINE_PRIORITY if e in engs]
    assert engs == want and len(engs) >= 4   # (SurrealDB's documents cells at tpch1 are the biggest and have their own stage)


def test_priority_names_every_subset_engine_and_arcadedb_leads():
    assert set(G.ENGINES) <= set(G.ENGINE_PRIORITY)
    assert G.ENGINE_PRIORITY[0] == "arcadedb"
    assert list(G.ENGINE_PRIORITY[1:14]) == ["surrealdb", "arangodb", "postgresql", "mongodb", "redis", "qdrant-neo4j", "composed-embedded",
                                              "neo4j", "qdrant", "duckdb", "sqlite", "memgraph", "ladybug"]
    assert G.ENGINE_PRIORITY[-1] == "cratedb"
    # both comparator batches are merged: Redis with its dense arm, CrateDB (last in priority) with its three lanes
    assert "redis" in G.ENGINES and "cratedb" in G.ENGINES


def test_a_single_rep_keeps_the_ids_and_one_pass(tmp_path):
    out = tmp_path / "o"
    r = run(["--after", "none", "--status-file", "none", "--reps", "1", "--lanes", "graph", "--out", str(out)], tmp_path)
    assert r.returncode == 0
    assert {stage_pass(f) for f in out.glob("*.sh")} == {1}


# ------------------------------------------------------------------------------------------ the bash, for real
HARNESS = r"""
set -u
T=$1; PASS=$2; shift 2
S=$T/status; ID=qT; PIN=abc123; export HOME=$T; RF=rows.jsonl; REPS=${REPS:-3}; lane=l1tpc
say() { echo "$*" >> "$S"; }
cat "$T/helpers.sh" > "$T/h.sh"
source "$T/h.sh"
export PATH=$T/bin:$PATH
"$@"
"""


def _helpers(chain):
    t = (chain / "qS03.sh").read_text() if (chain / "qS03.sh").exists() else next(iter(sorted(chain.glob("*.sh")))).read_text()
    a = t.index("declare -A CENSORED_AT")
    m = re.search(r"^run_cell\(\) \{.*?^\}\n", t[a:], re.M | re.S)
    return t[a:a + m.end()]


@pytest.fixture()
def env(tmp_path, chain):
    (tmp_path / "bin").mkdir()
    stub = tmp_path / "bin" / "python3"
    stub.write_text('#!/bin/bash\necho "$*" >> "$T_CALLS"\nexit "$(cat "$T_RC")"\n')
    stub.chmod(0o755)
    (tmp_path / "helpers.sh").write_text(_helpers(chain))
    return tmp_path


def cell(env, pass_no, label, rc=0, reps=3, **extra):
    (env / "rc").write_text(str(rc))
    e = dict(os.environ, T_CALLS=str(env / "calls"), T_RC=str(env / "rc"), REPS=str(reps), BENCH_GATE_HWMON=str(env / "no-hwmon"), **extra)   # no coretemp here: the temperature gate lets the stub cell go at once
    p = subprocess.run(["bash", "-c", HARNESS, "bash", str(env), str(pass_no), "run_cell", label, "tpch1", "600", "surrealdb_tpc",
                        "q1", ""], env=e, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    calls = (env / "calls").read_text().splitlines() if (env / "calls").exists() else []
    return calls


def test_pass_1_runs_rep_1_and_pass_2_runs_rep_2_only_after_a_clean_rep_1(env):
    c = cell(env, 1, "l1tpc/tpch1/surrealdb_tpc/q1")
    assert len(c) == 1 and "--only-reps 1 " in c[0] and "--reps 3" in c[0]
    c = cell(env, 2, "l1tpc/tpch1/surrealdb_tpc/q1")
    assert len(c) == 2 and "--only-reps 2 " in c[1]
    c = cell(env, 3, "l1tpc/tpch1/surrealdb_tpc/q1")
    assert len(c) == 3 and "--only-reps 3 " in c[2]
    # a cell that never ran rep 1 is not run at pass 2
    before = len((env / "calls").read_text().splitlines())
    c = cell(env, 2, "l1tpc/tpch1/other/q1")
    assert len(c) == before
    assert "no clean rep 1, rep 2 not run" in (env / "status").read_text()


def test_a_failed_rep_1_is_not_repeated_and_a_restart_retries_it(env):
    assert len(cell(env, 1, "L", rc=1)) == 1
    assert len(cell(env, 2, "L")) == 1          # pass 2: rep 1 left no clean row, so nothing ran
    assert "rep 1 failed, not repeating it" in (env / "status").read_text()
    assert len(cell(env, 1, "L")) == 2          # the restart of pass 1 retries the failed cell ...
    assert len(cell(env, 1, "L")) == 2          # ... and a clean rep 1 is not rerun by a second restart
    assert len(cell(env, 2, "L")) == 3          # now pass 2 may run it


def test_a_stage_with_fewer_reps_stops_after_them(env):
    assert len(cell(env, 1, "M", reps=2)) == 1 and len(cell(env, 2, "M", reps=2)) == 2
    assert len(cell(env, 3, "M", reps=2)) == 2   # REPS=2 declared: no third pass for this cell


def test_stopping_after_pass_2_leaves_a_state_a_third_pass_can_use(env):
    cell(env, 1, "Z"), cell(env, 2, "Z")
    st = (env / "rep-state-2026-11-abc123.tsv").read_text().splitlines()
    assert st == ["Z\t1\tok", "Z\t2\tok"]
    assert len(cell(env, 3, "Z")) == 3


# ------------------------------------------------------------------------------------ humemai/mmdbbench#22: a failed twin is not a failed cell
# The stub runner exits with the code in T_RC. 3 is runner.EXIT_PGWIRE_TWIN_ONLY: the runner's failed cell-runs were all PostgreSQL-wire twins.
STATE = "rep-state-2026-11-abc123.tsv"
TWIN_STATE = "rep-state-2026-11-abc123-pgwire.tsv"


def test_a_twin_that_fails_in_rep_1_leaves_the_headline_rep_ok_and_rep_2_runs(env):
    """The acceptance of #22: the twin failed in rep 1 and the headline rows were clean, so rep 1 is ok, the twin's failure is its own line, and rep 2 runs."""
    assert len(cell(env, 1, "L", rc=3)) == 1
    assert (env / STATE).read_text().splitlines() == ["L\t1\tok"]
    assert (env / TWIN_STATE).read_text().splitlines() == ["L\t1\tfail"]
    status = (env / "status").read_text()
    assert "only the PostgreSQL-wire twin failed" in status and "not repeating it" not in status
    c = cell(env, 2, "L")                                       # the twin's failure did not stop the later pass
    assert len(c) == 2 and "--only-reps 2 " in c[1]
    assert "no clean rep 1" not in (env / "status").read_text()
    assert (env / STATE).read_text().splitlines() == ["L\t1\tok", "L\t2\tok"]
    assert len(cell(env, 3, "L")) == 3                          # and rep 3
    # a restart of pass 1 does not rerun the clean headline rep either
    assert len(cell(env, 1, "L")) == 3


def test_a_twin_failure_does_not_censor_the_larger_sizes_but_a_headline_timeout_does(env):
    """cap_rule_note reads the last `[n/m]` line of the log: a twin that timed out last must not censor the headline at a larger size."""
    def script(first, second):
        return HARNESS.rsplit('"$@"', 1)[0] + (
            'printf "  [3/3] l1_x_clientpgwire_tiny_r1 9.0s (s0) -> timeout_after_600s\\n" >> "$S"\n'
            f'run_cell {first} tpch1 600 surrealdb_tpc q1 ""\n'
            f'run_cell {second} tpch10 600 surrealdb_tpc q1 ""\n')

    def go(first, second, rc):
        (env / "rc").write_text(str(rc))
        e = dict(os.environ, T_CALLS=str(env / "calls"), T_RC=str(env / "rc"), REPS="3", BENCH_GATE_HWMON=str(env / "no-hwmon"))
        p = subprocess.run(["bash", "-c", script(first, second), "bash", str(env), "1"], env=e, capture_output=True, text=True, timeout=60)
        assert p.returncode == 0, p.stderr
        return (env / "calls").read_text().splitlines()

    assert len(go("A", "B", 3)) == 2 and "censored" not in (env / "status").read_text()          # only the twin failed: the larger size ran
    (env / "calls").unlink()
    assert len(go("C", "D", 1)) == 1 and "D not run: censored at tpch1" in (env / "status").read_text()    # the same last line after a headline failure censors it


def test_any_other_failure_is_a_fail_and_a_twin_failure_is_a_plain_fail_in_the_catch_up(env):
    assert len(cell(env, 1, "H", rc=1)) == 1 and (env / STATE).read_text().splitlines() == ["H\t1\tfail"]
    assert not (env / TWIN_STATE).exists()                      # exit 1 is not a twin failure
    assert len(cell(env, 2, "H")) == 1 and "no clean rep 1, rep 2 not run" in (env / "status").read_text()
    # the twin-only catch-up: every row of the stage is a twin row, so exit 3 is the failure of what it ran and goes to its own file as fail
    assert len(cell(env, 1, "T", rc=3, FOURARM_CLIENTS="pgwire")) == 2
    assert (env / TWIN_STATE).read_text().splitlines() == ["T\t1\tfail"] and "T\t1\tok" not in (env / STATE).read_text()
    assert "--clients pgwire" in (env / "calls").read_text().splitlines()[-1]
    assert len(cell(env, 2, "T", FOURARM_CLIENTS="pgwire")) == 2        # rep 1 of the twin is not ok, so rep 2 of the twin is not run
    assert "T has no clean rep 1, rep 2 not run" in (env / "status").read_text()


def overlay(env, pass_no, label, rc):
    (env / "rc").write_text(str(rc))
    e = dict(os.environ, T_CALLS=str(env / "calls"), T_RC=str(env / "rc"), REPS="3", BENCH_GATE_HWMON=str(env / "no-hwmon"))
    p = subprocess.run(["bash", "-c", HARNESS, "bash", str(env), str(pass_no), "run_overlay", label, "tpch1", "600", "surrealdb_tpc", "q1", "drv.py",
                        "out", "ov.jsonl", "3", ""], env=e, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    return (env / "calls").read_text().splitlines() if (env / "calls").exists() else []


def test_the_overlay_notes_a_twin_only_failure_the_same_way(env):
    """run_overlay is the stage's other runner call; it reads the exit code in an `if ... else`, where $? is the runner's."""
    assert len(overlay(env, 1, "O", 3)) == 1
    assert (env / STATE).read_text().splitlines() == ["O\t1\tok"] and (env / TWIN_STATE).read_text().splitlines() == ["O\t1\tfail"]
    assert len(overlay(env, 2, "O", 0)) == 2                   # rep 2 of the overlay runs
    assert len(overlay(env, 1, "P", 1)) == 3 and "P\t1\tfail" in (env / STATE).read_text()
    assert len(overlay(env, 2, "P", 0)) == 3 and "no clean rep 1, rep 2 not run" in (env / "status").read_text()
