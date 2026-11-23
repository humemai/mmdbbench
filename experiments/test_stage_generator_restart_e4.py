"""The server restart table and the e4 decomposition have stages in the final pass (humemai/mmdbbench#137, refs #114).

Run with `python -m pytest test_stage_generator_restart_e4.py -q -s` from this directory (`-s` prints the cell counts and the time estimate).

The 26.11.1 pass never measured the `restart` table or the e4 decomposition: the page has no restart table and lists e4 as pending. The rerun on 26.12.1
puts every page table on one release (PAGE-SPEC rule 3), so a table whose small rows stayed on 26.11.1 would refuse the page. Until now the generator had no
stage for either, and `check_coverage()` passed anyway because it excluded both lanes as "not a lane of this generator's table". Held here:

  * `--profile final-small` has four restart stages (one per model, because an arm runs the one model `l6_restart.MODEL` gives it, at that model's own sizes)
    and one e4 stage, in both chains where the arm has both builds (the four served restart arms) and in the JVM chain alone where it has one (`arcadedb_e4`);
  * `check_coverage()` owes both lanes a stage: it fails when either is removed, and it no longer lists them as excluded;
  * no other profile stages them, no 26.11.1 roster cell is added, and a call of the older profiles writes what it wrote (the byte-for-byte proof is
    `test_the_drafts_are_the_ones_on_file` and its list `stage_drafts_2611.sha256`, which holds the older cases unchanged and the two final chains new);
  * the written drafts lint clean, carry the guards of the source lanes and the caps of the cap rule, and the whole-cell check does not stop a stage for a
    lane whose cells have no query roster.
"""
import collections
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from test_stage_generator_2611 import run  # noqa: E402
from test_stage_generator_rerun import JVM_WHEEL, NATIVE_WHEEL, rerun_args  # noqa: E402
from test_stage_generator_sizes import FINAL, TYPED, TYPED_JVM_ONLY, cells_of, chain  # noqa: E402
import cap_rule  # noqa: E402
import landing_gates  # noqa: E402
import make_2611_stages as G  # noqa: E402
import runner  # noqa: E402

RESTART_ARMS = {"docs": "arcadedb_server", "graph": "arcadedb_graph_server", "dense": "arcadedb_dense_server", "ts": "arcadedb_ts_native_server"}
RESTART_SMALL = {"docs": "tpch1", "graph": "sf1", "dense": "small", "ts": "ts100"}


def restart_stages(stages):
    return [s for s in stages if s[2] == "restart"]


def _write(tmp_path, name, wheel):
    out = tmp_path / name
    r = run(rerun_args(wheel=wheel) + ["--after", "none", "--id-prefix", "qWV", "--profile", FINAL, "--out", str(out)])
    assert r.returncode == 0, r.stdout[-600:] + r.stderr[-400:]
    return out


# ------------------------------------------------------------------------------------------------ the stages and their cells
@pytest.mark.parametrize("build", ["jvm", "native"])
def test_the_final_chain_has_four_restart_stages_and_the_e4_stage_in_the_jvm_chain(build, monkeypatch):
    stages = chain(monkeypatch, build)[0]
    rs = restart_stages(stages)
    assert [G.stage_backends(s) for s in rs] == [[RESTART_ARMS[m]] for m in ("docs", "graph", "dense", "ts")]
    assert [s[4] for s in rs] == [[RESTART_SMALL[m]] for m in ("docs", "graph", "dense", "ts")]
    assert all(s[3] == ["restart"] for s in rs)
    e4 = [s for s in stages if s[2] == "e4"]
    cells = cells_of(stages)
    have = collections.Counter(c.lane for c in cells)
    print(f"\n{build} chain: {len(stages)} stages, {len(cells)} cells per build (restart {have['restart']}, e4 {have['e4']}): "
          + ", ".join(c.label for c in cells if c.lane in G.FINAL_LANES))
    assert have["restart"] == TYPED["restart"] == 4
    if build == "jvm":
        assert len(e4) == 1 and G.stage_backends(e4[0]) == ["arcadedb_e4"] and e4[0][3] == ["decomp"] and e4[0][4] == ["e2"]
        assert have["e4"] == TYPED_JVM_ONLY["e4"] == 1
    else:
        assert not e4 and have["e4"] == 0          # arcadedb_e4 has no native counterpart: build_less_served_arms()
    assert len(stages) == 8 + 4 + len(e4)
    assert len(cells) == 92 + 4 + len(e4)
    assert all(c.cls == "relaxed" and c.arm == "" and c.kind == "lane" for c in cells if c.lane in G.FINAL_LANES)   # no strict pass, no extra arm, no overlay


def test_the_new_lanes_run_after_the_second_list(monkeypatch):
    lanes = [s[2] for s in chain(monkeypatch, "jvm")[0]]
    assert lanes[-5:] == ["restart"] * 4 + ["e4"]
    assert lanes[-6] == "l4" and lanes.index("restart") > max(i for i, lane in enumerate(lanes) if lane in G.SECOND_LANES)


def test_every_restart_arm_is_staged_once_at_the_sizes_of_its_own_model():
    model_of, tiers = G._restart_tables()
    assert set(model_of) == set(runner.LANES["restart"][1])          # the lane's own table and the registered roster are one list
    owned = collections.Counter()
    for s in restart_stages(G.FINAL_STAGES):
        arms = G.stage_backends(s)
        models = {model_of[b] for b in arms}
        assert len(models) == 1, (s[0], arms)                         # one model per stage
        assert set(s[4]) == tiers[models.pop()], (s[0], s[4])         # and every size of that model, no other (micro, the laptop smoke tier, is not staged)
        owned.update(arms)
    assert owned == collections.Counter(runner.LANES["restart"][1])  # each arm in exactly one stage
    # small first: the sizes of a stage are in the order of their class, and every one has a class
    for s in restart_stages(G.FINAL_STAGES):
        classes = [G.scale_class("restart", x) for x in s[4]]
        assert classes == ["small", "large"], (s[0], classes)


def test_the_small_sizes_are_the_ones_of_size_classes():
    kept = {(lane, sc) for (lane, sc), cls in G._SC.SIZE_CLASS.items() if lane in G.FINAL_LANES and cls in ("small", "extra")}
    assert kept == {("restart", x) for x in RESTART_SMALL.values()} | {("e4", "e2")}


# ------------------------------------------------------------------------------------------------ the coverage gate
def test_coverage_passes_with_the_stages_and_no_longer_excludes_the_two_lanes():
    problems, excluded, counts = G.check_coverage()
    assert problems == []
    assert not {lane for lane, _why in excluded} & set(G.FINAL_LANES)
    assert counts["restart"] == len(runner.LANES["restart"][1]) == 16 and counts["e4"] == len(runner.LANES["e4"][1]) == 1


@pytest.mark.parametrize("lane,workload", [("restart", "restart"), ("e4", "decomp")])
def test_coverage_fails_when_the_stage_of_either_lane_is_removed(lane, workload):
    rest = [s for s in G.ALL_STAGES if s[2] != lane]
    problems, excluded, _counts = G.check_coverage(rest)
    assert problems == [f"{lane}/{workload}: on the page, in no stage"]
    assert not {name for name, _why in excluded} & set(G.FINAL_LANES)          # the lane is owed a stage, not excluded
    # the 26.11.1 table alone, without any final stage, fails for both
    assert len(G.check_coverage(G.STAGES)[0]) == 2


def test_coverage_names_the_arm_of_a_removed_restart_stage():
    docs = restart_stages(G.FINAL_STAGES)[0]
    problems, _e, _c = G.check_coverage([s for s in G.ALL_STAGES if s != docs])
    assert problems and all("in 0 stages, expected exactly 1" in p for p in problems)
    assert {p.split(": ")[0] for p in problems} == {f"restart/restart/{b}" for b in G.stage_backends(docs)}


def test_a_restart_arm_at_another_models_size_is_refused():
    docs = restart_stages(G.FINAL_STAGES)[0]
    bad = list(docs[:4]) + [["sf1"]] + list(docs[5:])                          # arcadedb_server and its four documents siblings at the graph model's size
    problems, _e, _c = G.check_coverage([s for s in G.ALL_STAGES if s != docs] + [tuple(bad)])
    assert any("arcadedb_server runs the docs model" in p and "sf1 is another model's size" in p for p in problems), problems
    assert G.restart_model_problems(G.ALL_STAGES) == []


def test_a_page_table_that_is_a_directory_needs_its_reader_in_export_web(monkeypatch):
    assert G.DIRECTORY_TABLES == {"e4": ("decomp", "E4_DIR")} and G.directory_table_problems() == []
    monkeypatch.setattr(G, "DIRECTORY_TABLES", {"e4": ("decomp", "NO_SUCH_DIR")})
    assert any("e4/decomp" in p and "NO_SUCH_DIR" in p for p in G.directory_table_problems())
    assert any("NO_SUCH_DIR" in p for p in G.check_coverage()[0])


# ------------------------------------------------------------------------------------------------ the other profiles stay as they were
def test_no_other_profile_stages_the_new_lanes_and_the_26_11_1_table_does_not_hold_them():
    assert not {s[2] for s in G.STAGES} & set(G.FINAL_LANES) and {s[2] for s in G.FINAL_STAGES} == set(G.FINAL_LANES)
    for profile in ("paper-2611", "full"):
        assert not set(G.profile_lanes(profile)) & set(G.FINAL_LANES)
        assert G.drop_reason(profile, "restart", "arcadedb_server") == G.DROP_FINAL_LANES == G.drop_reason(profile, "e4", "arcadedb_e4")
        lanes = G.parse_lanes(None, profile == "full", profile)
        for build_skip in ((), tuple(G.build_less_served_arms())):
            specs = G.subset_specs(["arcadedb"], lanes, "biggest-last", tuple(G.profile_skip(profile)) + build_skip, True)
            assert not {s[2] for s in specs} & set(G.FINAL_LANES)
    assert G.drop_reason(FINAL, "restart", "arcadedb_server") is None and G.profile_lanes(FINAL)[-2:] == G.FINAL_LANES
    r = run(["--check", "--lanes", "restart"])
    assert r.returncode != 0 and "--profile final-small" in (r.stdout + r.stderr)
    r = run(["--check", "--profile", "full", "--second-list", "--lanes", "e4"])
    assert r.returncode != 0 and "--profile final-small" in (r.stdout + r.stderr)
    r = run(rerun_args() + ["--check", "--profile", FINAL, "--lanes", "restart,e4"])
    assert r.returncode == 0, r.stdout[-500:]
    assert "lanes: restart, e4\n" in r.stdout


def test_the_roster_of_the_26_11_1_pass_owes_no_restart_or_e4_cell():
    doc = landing_gates.load_roster()
    assert not {c["lane"] for c in doc["cells"] + doc["outside_cells"] + doc["profile_dropped"]["cells"]} & set(G.FINAL_LANES)
    assert (doc["cells"], doc["outside_cells"]) == landing_gates.roster_cells()


# ------------------------------------------------------------------------------------------------ the check and the written drafts
def test_check_lists_the_new_stages_for_both_chains():
    jvm = run(rerun_args() + ["--check", "--profile", FINAL])
    native = run(rerun_args(wheel=NATIVE_WHEEL) + ["--check", "--profile", FINAL])
    for r in (jvm, native):
        assert r.returncode == 0 and "PROBLEM" not in r.stdout, r.stdout[-800:]
        assert "lanes: l2, e2, l1tpc, l3d, l3s, l4, lifecycle, restart, e4\n" in r.stdout
        for model, scale in RESTART_SMALL.items():
            assert re.search(rf"restart\s+{scale}\s+1 arms\s+tier 1\s+server restart, ", r.stdout), (model, r.stdout[-1500:])
        assert "kept    e2/e2, e4/e2, " in r.stdout and "restart/tpch1" in r.stdout and "restart/tpch10 (large)" in r.stdout
    assert re.search(r"e4\s+e2\s+1 arms\s+tier 1\s+E4 deployment decomposition", jvm.stdout)
    assert "E4 deployment decomposition" not in native.stdout


def test_the_written_drafts_of_both_final_chains_lint_clean_and_cover_the_new_cells(tmp_path):
    jvm, native = _write(tmp_path, "jvm", JVM_WHEEL), _write(tmp_path, "native", NATIVE_WHEEL)
    model_of, tiers = G._restart_tables()
    for name, out, n_files, e4_runs in (("jvm", jvm, 40, 3), ("native", native, 37, 0)):
        files = sorted(out.glob("qWV*.sh"))
        assert len(files) == n_files                       # the pair install, and 12 or 13 stages x 3 passes
        seen = collections.Counter()
        for f in files:
            text = f.read_text()
            assert subprocess.run(["bash", "-n", str(f)], capture_output=True).returncode == 0, f.name
            lane = re.search(r"--lanes (\w+) ", text)
            if not lane or lane.group(1) not in G.FINAL_LANES:
                continue
            arms = re.findall(r'^BACKENDS="([^"]*)"', text, re.M)[0].split()
            cells = re.findall(r'^[ \t]*run_cell "([a-z0-9]+)/([a-z0-9_]+)/\$BE/([a-z]+)" ([a-z0-9_]+) (\d+) ', text, re.M)
            assert len(cells) == 1 and arms and cells[0][1] == cells[0][3], f.name        # one cell per arm and pass: a size and its cap
            lane_, scale, wl, _s, cap = cells[0]
            for be in arms:
                seen[(lane_, scale, be, wl)] += 1
                if lane_ == "restart":
                    assert scale in tiers[model_of[be]], (f.name, be, scale)               # no arm at another model's size
            want = min(runner.TIMEOUT_BY_SCALE[scale], cap_rule.rule_cap(lane_, scale, wl, "") or 10 ** 9)
            assert int(cap) == want, (f.name, cap, want)                                    # the tier cap lowered by the cap rule
            assert "this tier's budgets do not fit its cap" in text and f"cell_cost_check.py --lane {lane_} " in text
            assert "version_pin_check.py --runtime" in text and "ABORT: pair unverified at the pin" in text and 'ARCADEDB_ENGINE_COMMIT=$PIN' in text
            assert '$ID: images present: ' in text and 'go-arcadedb-2612' in text                  # the image check and the ArcadeDB gate of the rerun
        want_cells = {("restart", RESTART_SMALL[m], RESTART_ARMS[m], "restart"): 3 for m in RESTART_ARMS}
        if e4_runs:
            want_cells[("e4", "e2", "arcadedb_e4", "decomp")] = 3
        assert dict(seen) == want_cells, (name, dict(seen))                                 # every cell once per pass, three passes, nothing else
        r = run(rerun_args(wheel=JVM_WHEEL if name == "jvm" else NATIVE_WHEEL) + ["--check", "--profile", FINAL, "--drafts", str(out)])
        assert r.returncode == 0, r.stdout[-800:]
    assert G.chain_served_problems(str(jvm), str(native)) == []                              # each chain runs the restart arms of its own build once
    text = {f.name: f.read_text() for f in jvm.glob("qWV*.sh")}
    guards = {"restart/tpch1": "sf10_lineitem.parquet", "restart/sf1": "ldbc/sf10", "restart/ts100": "cpu_influx_s1000.lp"}   # the guards of the lane whose loader the model uses
    for label, needle in guards.items():
        scripts = [t for t in text.values() if f'run_cell "{label}/$BE/restart"' in t]
        assert scripts and all(needle in t for t in scripts), label


def test_the_final_chain_lint_refuses_drafts_of_a_profile_that_does_not_stage_the_new_lanes(tmp_path):
    out = _write(tmp_path, "jvm", JVM_WHEEL)
    problems = G.lint_drafts(str(out), profile="paper-2611")
    assert any("lane restart" in p and "final-pass-lanes" in p for p in problems), problems[:4]
    assert any("lane e4" in p and "final-pass-lanes" in p for p in problems)
    r = run(rerun_args() + ["--check", "--profile", FINAL, "--drafts", str(out)])               # the profile that carries the lanes lints the same drafts clean
    assert r.returncode == 0, r.stdout[-600:]


# ------------------------------------------------------------------------------------------------ the whole-cell check and the time
@pytest.mark.parametrize("lane,tier,arm", [("restart", "tpch1", "arcadedb_server"), ("e4", "e2", "arcadedb_e4")])
def test_the_whole_cell_check_does_not_stop_a_stage_of_these_lanes(lane, tier, arm, tmp_path):
    """rc 1 aborts a stage ("projected cell cost exceeds the cap"). These lanes have no query roster and no cold_* field, so the tool must answer 2 (not scored) before
    any row exists and 0 once rows exist, and never 1."""
    tool = HERE / "cell_cost_check.py"
    rows = tmp_path / "rows.jsonl"

    def check():
        return subprocess.run([sys.executable, str(tool), "--lane", lane, "--tier", tier, "--backends", arm, "--rows", str(rows)], cwd=HERE,
                              capture_output=True, text=True).returncode
    assert check() == 2                                                       # no file: no rows
    rows.write_text(json.dumps({"lane": lane, "scale": tier, "backend": arm, "workload": "restart", "ingest_s": 12.0}) + "\n")
    assert check() == 0


def test_the_time_of_a_rep_is_far_below_two_hours(capsys):
    """The estimate in the pull request, from the only timings of these cells the repository holds: the pass-1 cell lines of the 2026-10 pass (cap_rule_2610.json,
    pin d36b4ca3a), the slowest ArcadeDB arm's median per cell. The runner adds a lean-client twin job to every served ArcadeDB arm (ARCADEDB_HTTP_ARMS) that runs
    the whole cell again; e4 has none. The 26.11.1 pass did not run either lane, so there are no 26.11.1 rows to read."""
    caps = cap_rule.load()["caps"]
    cells = [("restart", RESTART_SMALL[m], "restart") for m in RESTART_ARMS] + [("e4", "e2", "decomp")]
    median = {c: caps[cap_rule.key_of(*c, "")]["arcadedb_max_median_s"] for c in cells}
    twin = {c: 2 if c[0] == "restart" else 1 for c in cells}
    per_rep = sum(median[c] * twin[c] for c in cells)
    with capsys.disabled():
        print("\n" + "\n".join(f"  {l}/{sc}: {m:7.1f} s median x {twin[(l, sc, wl)]} job(s)" for (l, sc, wl), m in median.items())
              + f"\n  one rep of all five cells: {per_rep:.0f} s = {per_rep / 60:.1f} min; three reps {3 * per_rep / 3600:.2f} h")
    assert max(median[c] * twin[c] for c in cells) < 7200 and per_rep < 7200          # no cell, and not all five together, takes two hours a rep
    assert {b for b in RESTART_ARMS.values()} <= set(runner.ARCADEDB_HTTP_ARMS)       # the four restart arms are the ones that get a lean twin
    assert "arcadedb_e4" not in runner.ARCADEDB_HTTP_ARMS
