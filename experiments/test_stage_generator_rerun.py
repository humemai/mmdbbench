"""`make_2611_stages.py` for a later ArcadeDB release on the same instrument: `--go-marker`, the `--id-prefix` check and `--harness-sha`.

Run with `python -m pytest test_stage_generator_rerun.py -q` from this directory.

A host that ran the 26.11.1 pass still holds three things of it, and each one would let a rerun start wrong while looking right:
the gate file `go-arcadedb-2611` (the gate of the new chain would be open before anyone opened it), the `ALL-DONE` lines of the stage
ids `qV00`... and `qN00`... in STATUS.txt (every wait of a new chain with the same prefix would be true at once), and a checkout whose
wheel directory holds that release's wheel. The rerun also runs from a worktree of this repository pinned at one commit, which cannot
pull. A call without the new arguments writes the 26.11.1 pass byte for byte: `test_the_drafts_are_the_ones_on_file` holds that.
"""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from test_stage_generator_2611 import DIGEST, WSHA, _release_args, run, waits  # noqa: E402
import bench_common  # noqa: E402
import make_2611_stages as G  # noqa: E402

RELEASE = "26.12.1"
JVM_WHEEL = f"arcadedb_jvm-{RELEASE}-py3-none-manylinux_2_28_x86_64.whl"
NATIVE_WHEEL = f"arcadedb-{RELEASE}-py3-none-manylinux_2_28_x86_64.whl"
GO = "$HOME/conf/go-arcadedb-2612"
HARNESS = "d" * 40
URL = "https://files.pythonhosted.org/packages/x/"


def rerun_args(wheel=JVM_WHEEL, go=GO, **over):
    a = _release_args(**{"--arcadedb-release": RELEASE, "--wheel-name": wheel, "--wheel-url": URL + wheel, **over})
    return a + (["--go-marker", go] if go else [])


def first_pass_status(tmp_path):
    """The lines a host keeps after the first pass: its stage ids, another chain's ids that only share letters, and a log line."""
    f = tmp_path / "STATUS.txt"
    f.write_text("qV00 ALL-DONE\nqV24 ALL-DONE\nqN00 ALL-DONE\nqN21 ALL-DONE\nqPG03 ALL-DONE\n"
                 "[2026-11-08T05:12:00+00:00] qWV01 ALL-DONE (a log line, not the marker)\nqWV ALL-DONE\n")
    return f


# ------------------------------------------------------------------------------------------------ the gate file
def test_another_release_is_refused_with_the_gate_file_of_the_first_pass(tmp_path):
    out = tmp_path / "o"
    r = run(rerun_args(go=None) + ["--after", "none", "--id-prefix", "qWV", "--lanes", "graph", "--out", str(out)])
    assert r.returncode != 0 and "--go-marker" in (r.stdout + r.stderr) and not list(out.glob("*.sh"))
    r = run(rerun_args(go=None) + ["--check"])
    assert r.returncode != 0 and "go-arcadedb-2611" in (r.stdout + r.stderr)


def test_the_first_pass_needs_no_gate_argument_and_keeps_its_text(tmp_path):
    out = tmp_path / "o"
    r = run(_release_args() + ["--after", "none", "--id-prefix", "qT", "--lanes", "graph", "--out", str(out)])
    assert r.returncode == 0, r.stdout[-400:] + r.stderr[-400:]
    pair, lane = (out / "qT00.sh").read_text(), (out / "qT01.sh").read_text()
    assert 'GO="$HOME/conf/go-arcadedb-2611"' in pair and "is 26.11.1, not before" in pair
    assert "(go-arcadedb-2611): the benchmark pin is not 26.11.1 yet" in lane
    assert 'git pull -q --ff-only || { say "$ID ABORT: pull"; exit 1; }' in pair and "dist-archive" in pair
    assert 'git pull -q --ff-only || { say "$ID ABORT: pull"; exit 1; }' in lane and "rev-parse" not in lane


def test_a_rerun_chain_carries_its_own_gate_and_names_its_release(tmp_path):
    out = tmp_path / "o"
    r = run(rerun_args() + ["--after", "none", "--id-prefix", "qWV", "--lanes", "graph,dense", "--out", str(out)])
    assert r.returncode == 0, r.stdout[-400:] + r.stderr[-400:]
    files = sorted(out.glob("qWV*.sh"))
    assert files[0].name == "qWV00.sh" and len(files) >= 4
    pair = files[0].read_text()
    assert f'GO="{GO}"' in pair and "is 26.12.1, not before" in pair
    assert pair.index('while [ ! -f "$GO" ]') < pair.index("trap 'echo")     # a killed waiter hands nothing on, as before
    for f in files[1:]:
        t = f.read_text()
        assert f'[ -f "{GO}" ] || ' in t and f"ABORT: no {GO} (go-arcadedb-2612): the benchmark pin is not 26.12.1 yet" in t, f.name
        assert t.index("trap 'echo") < t.index(f"ABORT: no {GO}"), f.name
    for f in files:
        t = f.read_text()
        assert "go-arcadedb-2611" not in t and "26.11.1" not in t, f.name
        assert "export BENCH_INSTRUMENT=2026-11" in t or f.name == "qWV00.sh"   # the instrument stays
        assert f.name == "qWV00.sh" or 'RF="runs_page_${PIN}_2611.jsonl"' in t


def test_the_lint_asks_for_the_gate_the_chain_was_generated_with(tmp_path):
    out = tmp_path / "o"
    r = run(rerun_args() + ["--after", "none", "--id-prefix", "qWV", "--lanes", "graph", "--out", str(out)])
    assert r.returncode == 0, r.stdout[-400:] + r.stderr[-400:]
    r = run(rerun_args() + ["--check", "--drafts", str(out), "--lanes", "graph"])
    assert r.returncode == 0, r.stdout[-600:]
    other = "$HOME/conf/go-arcadedb-other"
    r = run(rerun_args(go=other) + ["--check", "--drafts", str(out), "--lanes", "graph"])
    assert r.returncode == 1 and "qWV00.sh: the pair install does not wait for the go-arcadedb-other marker" in r.stdout
    assert "qWV01.sh: runs an ArcadeDB arm but has no go-arcadedb-other gate" in r.stdout


@pytest.mark.parametrize("bad", ["$HOME/conf/go 2612", "$HOME/conf/../go-arcadedb-2612", "$HOME/conf/go-2612", "go-arcadedb-2612",
                                 '$HOME/conf/go-arcadedb-2612"; rm -rf x; "', "$HOME/conf/go-arcadedb-"])
def test_a_gate_path_that_bash_could_read_as_more_than_a_file_name_is_refused(bad, tmp_path):
    out = tmp_path / "o"
    r = run(rerun_args(go=bad) + ["--after", "none", "--id-prefix", "qWV", "--lanes", "graph", "--out", str(out)])
    assert r.returncode != 0 and "--go-marker" in (r.stdout + r.stderr) and not list(out.glob("*.sh"))


def test_a_call_after_a_rerun_call_in_one_process_is_the_first_pass_again(monkeypatch):
    """main() sets the gate, its release and the harness pin on every call (as it does CHAIN_BUILD), so one call does not leak into the next."""
    monkeypatch.delenv("BENCH_INSTRUMENT", raising=False)
    monkeypatch.delenv("BENCH_STAGE_REPO", raising=False)
    monkeypatch.setattr(bench_common, "INSTRUMENT", G.INSTRUMENT)
    for name in ("GO_ARCADEDB_MARKER", "GO_RELEASE", "HARNESS_SHA", "CHAIN_BUILD"):     # restored whatever this test does
        monkeypatch.setattr(G, name, getattr(G, name))
    assert G.main(rerun_args() + ["--harness-sha", HARNESS, "--check"]) == 0
    assert (G.GO_ARCADEDB_MARKER, G.GO_RELEASE, G.HARNESS_SHA) == (GO, RELEASE, HARNESS)
    assert G.main(["--check"]) == 0
    assert (G.GO_ARCADEDB_MARKER, G.GO_RELEASE, G.HARNESS_SHA) == (G.DEFAULT_GO_MARKER, "26.11.1", "")
    assert G.DEFAULT_GO_MARKER.endswith("conf/go-arcadedb-2611") and G.go_tag() == "go-arcadedb-2611"


# ------------------------------------------------------------------------------------------------ the id prefix
def test_ids_of_a_prefix_are_the_prefix_and_digits_as_whole_lines(tmp_path):
    f = first_pass_status(tmp_path)
    assert G.done_ids("qV", str(f)) == ["qV00", "qV24"]
    assert G.done_ids("qN", str(f)) == ["qN00", "qN21"]
    assert G.done_ids("qP", str(f)) == []          # qPG03 is another chain's id
    assert G.done_ids("qWV", str(f)) == []         # a log line and a marker without digits are not stage ids
    assert G.prefix_problems("qWV", str(f)) == [] and G.prefix_problems("qV", None) == []
    assert "no such file" in G.prefix_problems("qV", str(tmp_path / "missing.txt"))[0]


@pytest.mark.parametrize("prefix", ["qV", "qN"])
def test_a_prefix_the_machine_already_used_is_refused_and_nothing_is_written(prefix, tmp_path):
    out = tmp_path / "o"
    r = run(rerun_args() + ["--after", "none", "--status-file", str(first_pass_status(tmp_path)), "--id-prefix", prefix,
                            "--lanes", "graph", "--out", str(out)])
    assert r.returncode == 1 and f"--id-prefix {prefix}: 2 stage id(s) of this prefix already have an ALL-DONE line" in r.stdout
    assert not list(out.glob("*.sh"))


def test_a_new_prefix_is_accepted_with_the_same_status_file_and_none_still_means_no_check(tmp_path):
    status = first_pass_status(tmp_path)
    out = tmp_path / "o"
    r = run(rerun_args() + ["--after", "none", "--status-file", str(status), "--id-prefix", "qWV", "--lanes", "graph", "--out", str(out)])
    assert r.returncode == 0, r.stdout[-400:] + r.stderr[-400:]
    assert waits(out / "qWV01.sh") == ["qWV00"]
    used = tmp_path / "used"
    r = run(rerun_args() + ["--after", "none", "--status-file", "none", "--id-prefix", "qV", "--lanes", "graph", "--out", str(used)])
    assert r.returncode == 0, r.stdout[-400:] + r.stderr[-400:]      # no file, no check: what the first pass's own generation said
    r = run(rerun_args() + ["--after", "none", "--status-file", str(tmp_path / "missing.txt"), "--id-prefix", "qWV", "--lanes", "graph",
                            "--out", str(tmp_path / "o3")])
    assert r.returncode == 1 and "no such file" in r.stdout


def test_check_drafts_refuses_drafts_whose_own_markers_are_already_in_status(tmp_path):
    status = first_pass_status(tmp_path)
    used = tmp_path / "used"
    r = run(rerun_args() + ["--after", "none", "--status-file", "none", "--id-prefix", "qV", "--lanes", "graph", "--out", str(used)])
    assert r.returncode == 0, r.stdout[-400:] + r.stderr[-400:]
    r = run(rerun_args() + ["--check", "--drafts", str(used), "--status-file", str(status), "--lanes", "graph"])
    assert r.returncode == 1 and "qV00.sh: its own marker `qV00 ALL-DONE` is already a line" in r.stdout
    r = run(rerun_args() + ["--check", "--drafts", str(used), "--lanes", "graph"])       # without a file: the old lint only
    assert r.returncode == 0, r.stdout[-400:]


# ------------------------------------------------------------------------------------------------ the pinned worktree
def test_a_pinned_chain_checks_head_never_pulls_and_fills_its_own_wheel_directory(tmp_path):
    out = tmp_path / "o"
    tree = "$HOME/rerun-wt/jvm"
    r = run(rerun_args() + ["--harness-sha", HARNESS, "--after", "none", "--id-prefix", "qWV", "--lanes", "graph", "--out", str(out)],
            env_extra={"BENCH_STAGE_REPO": tree})
    assert r.returncode == 0, r.stdout[-400:] + r.stderr[-400:]
    files = sorted(out.glob("qWV*.sh"))
    check = f'cd "$REPO" && [ "$(git rev-parse HEAD)" = "{HARNESS}" ] || {{ say "$ID ABORT: worktree is not at the harness pin {HARNESS}"; exit 1; }}'
    for f in files:
        t = f.read_text()
        assert t.count(check) == 1 and "git pull" not in t, f.name
        assert f"REPO={tree}" in t and "R=$REPO/experiments" in t, f.name
        assert "BINDINGS_REPO=${BINDINGS_REPO:-$REPO}; export BINDINGS_REPO" in t, f.name
        assert t.index("trap 'echo") < t.index("ABORT: worktree is not at the harness pin"), f.name     # the abort still hands on
    pair = files[0].read_text()
    assert 'D="$BINDINGS_REPO/bindings/python/dist"' in pair and 'mkdir -p "$D"' in pair and 'mv "$T/$WN" "$D/"' in pair
    assert "dist-archive" not in pair and "ABORT: dist swap" not in pair
    # the wheel directory is filled after the download was verified and before the image is built from it
    assert pair.index("ABORT: PyPI wheel download or sha256") < pair.index('mv "$T/$WN" "$D/"') < pair.index("build_images.sh arcadedb")
    # another release's wheel in the worktree's directory is refused, the chain's own wheel (a restarted pair install) is not
    assert '[ ! -e "$_w" ] || [ "$(basename "$_w")" = "$WN" ] || { say "$ID ABORT: $D holds another wheel' in pair
    assert f'W="$BINDINGS_REPO/bindings/python/dist/{JVM_WHEEL}"' in files[1].read_text()
    assert G.lint_drafts(str(out), {"arcadedb"}) != []       # this process still lints for the first pass's gate: the chain names its own
    r = run(rerun_args() + ["--harness-sha", HARNESS, "--check", "--drafts", str(out), "--lanes", "graph"])
    assert r.returncode == 0, r.stdout[-600:]


@pytest.mark.parametrize("bad", ["d" * 39, "D" * 40, "main", "d" * 41])
def test_a_harness_pin_that_is_not_a_full_commit_is_refused(bad, tmp_path):
    out = tmp_path / "o"
    r = run(rerun_args() + ["--harness-sha", bad, "--after", "none", "--id-prefix", "qWV", "--lanes", "graph", "--out", str(out)])
    assert r.returncode != 0 and "--harness-sha" in (r.stdout + r.stderr) and not list(out.glob("*.sh"))


# ------------------------------------------------------------------------------------------------ both chains
def test_the_jvm_and_the_native_chain_of_a_rerun_lint_clean_together(tmp_path):
    """The two generator runs of a rerun: one wheel each, own prefix, own worktree, one gate, one harness pin, the same status file."""
    status = first_pass_status(tmp_path)
    nd = "sha256:" + "ef" * 32
    common = ["--native-image-digest", nd, "--harness-sha", HARNESS, "--after", "none", "--status-file", str(status)]
    jvm, native = tmp_path / "jvm", tmp_path / "native"
    r = run(rerun_args() + common + ["--id-prefix", "qWV", "--out", str(jvm)], env_extra={"BENCH_STAGE_REPO": "$HOME/rerun-wt/jvm"})
    assert r.returncode == 0, r.stdout[-400:] + r.stderr[-400:]
    r = run(rerun_args(wheel=NATIVE_WHEEL) + common + ["--id-prefix", "qWN", "--out", str(native)], env_extra={"BENCH_STAGE_REPO": "$HOME/rerun-wt/native"})
    assert r.returncode == 0, r.stdout[-400:] + r.stderr[-400:]
    r = run(rerun_args() + common + ["--check", "--drafts", str(jvm), "--also-drafts", str(native), "--id-prefix", "qWV"])
    assert r.returncode == 0, r.stdout[-600:]
    n1 = (native / "qWN01.sh").read_text()
    assert f'export ARCADEDB_NATIVE_SERVER_IMAGE="arcadedata/arcadedb@{nd}"' in n1 and "REPO=$HOME/rerun-wt/native" in n1
    assert "REPSTATE=$HOME/rep-state-2026-11-$PIN-native.tsv" in n1          # the instrument stays; a new engine commit is a new file
    assert f"DIG={DIGEST}" in (jvm / "qWV00.sh").read_text() and f"WSHA={WSHA}" in (jvm / "qWV00.sh").read_text()
    for d, pre in ((jvm, "qWV"), (native, "qWN")):
        files = sorted(d.glob("*.sh"))
        assert [f.stem for f in files] == [f"{pre}{i:02d}" for i in range(len(files))]
        for prev, cur in zip(files, files[1:]):
            assert waits(cur) == [prev.stem]
