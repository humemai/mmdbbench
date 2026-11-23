"""`make_2611_stages.py --sizes small` and `--profile final-small`: the stages of the 26.12.1 rerun (humemai/mmdbbench#136, refs #114).

Run with `python -m pytest test_stage_generator_sizes.py -q -s` from this directory (`-s` prints the cell counts per lane).

The rerun is the small size of every table, solo, n=3. Before this change a chain carried both sizes of every lane, so it would have run the
large sizes too (about 70 hours of deep10m, tpch10, sf10 and e2_500k) and, on the default profile, skipped sparse, time series and lifecycle.
Three things are held here, and each would fail quietly if it broke:

  * the filter reads `size_classes.SIZE_CLASS` and not `runner.LARGE_SCALES`: that tuple holds `sf1full` (a small size) and lacks `sf10`,
    `e2_500k`, `lc10m`, `ts1000` and `medium`;
  * the final profile has the lanes of `full` with the second list, less the arms that no page table prints (the int8 dense arms and the
    `nocompact` sparse arms), and it cannot be run at all sizes;
  * a call without the new arguments writes the 26.11.1 pass byte for byte (`test_the_drafts_are_the_ones_on_file` holds that for six
    generations, both builds, the default and the full profile).

The expected cell counts are derived from `SIZE_CLASS` and the generator's own cell lists (`stage_cells` over the unfiltered stage table), not
typed; `TYPED` is the one number per lane that was counted by hand.
"""
import collections
import filecmp
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from test_stage_generator_2611 import run  # noqa: E402
from test_stage_generator_rerun import NATIVE_WHEEL, rerun_args  # noqa: E402
import make_2611_stages as G  # noqa: E402
import runner  # noqa: E402
import size_classes  # noqa: E402

FINAL = "final-small"
KEPT = ("small", "extra")
LANE_ORDER = G.CORE_LANES + G.SECOND_LANES

# Counted by hand, per build, for `--profile final-small`:
#   l2         sf1 oltp: 2 arms x (relaxed, strict) = 4, sf1full olap: 2 arms x (GAV on, GAV off) = 4
#   e2         hybrid (relaxed, strict) + atomicity = 3 cells x 2 arms
#   l1tpc      oltp (relaxed, strict) + olap = 3 cells x 2 arms
#   l3d        2 fp32 arms x (lane cell, multipass overlay)
#   l3s        4 arms (embedded, embedded_fp32, server, server_fp32) x 2 sizes (tiny, small) x (lane cell, overlay)
#   l4         4 arms x ts100
#   lifecycle  2 arms x 8 workloads x 3 sizes (lc10k, lc100k, lc1m)
TYPED = {"l2": 8, "e2": 6, "l1tpc": 6, "l3d": 4, "l3s": 16, "l4": 4, "lifecycle": 48}
# the arms of `full` that the final profile leaves out, and the arms it keeps beside them
OUT_ARMS = {"arcadedb_dense_embedded_int8", "arcadedb_dense_server_int8", "arcadedb_sparse_embedded_nocompact"}
IN_ARMS = {"arcadedb_dense_embedded", "arcadedb_dense_server", "arcadedb_sparse_embedded", "arcadedb_sparse_embedded_fp32",
           "arcadedb_sparse_server", "arcadedb_sparse_server_fp32"}
SMALL_PAIRS = {("l2", "sf1"), ("l2", "sf1full"), ("e2", "e2"), ("l1tpc", "tpch1"), ("l3d", "small"), ("l3s", "tiny"), ("l3s", "small"),
               ("l4", "ts100"), ("lifecycle", "lc10k"), ("lifecycle", "lc100k"), ("lifecycle", "lc1m")}
LARGE_SCALE_NAMES = {"sf10", "tpch10", "e2_500k", "deep10m", "lc10m", "ts1000", "medium"}


def chain(monkeypatch, build, profile=FINAL, sizes=None):
    """The stages main() makes for ArcadeDB's chain of one build, with the same calls in the same order. CHAIN_BUILD is set the way main() sets it and
    put back after the test."""
    monkeypatch.setattr(G, "CHAIN_BUILD", "native" if build == "native" else "")
    sizes = G.resolve_sizes(profile, sizes)
    lanes = G.parse_lanes(None, bool(G.PROFILES[profile].get("second_list")) or profile == "full", profile)
    skip = tuple(G.profile_skip(profile)) + (tuple(G.build_less_served_arms()) if build == "native" else ())
    return G.number(G.subset_specs(["arcadedb"], lanes, "biggest-last", skip, True, sizes), "qZ"), lanes, skip, sizes


def cells_of(stages):
    return [c for st in stages for c in G.stage_cells(st)]


def table_cells(build):
    """Every ArcadeDB cell of the unfiltered stage table for one build's chain: what the filters start from, read without them."""
    skip = set(G.build_less_served_arms()) if build == "native" else set()
    return [c for spec in G.STAGES for c in G.stage_cells(spec) if G.engine_of(c.backend) == "arcadedb" and c.backend not in skip]


def expected_per_lane(build):
    """The cells the final profile owes: the table's cells whose size class is small or extra, less the arms the profile drops."""
    return collections.Counter(c.lane for c in table_cells(build)
                               if size_classes.SIZE_CLASS[(c.lane, c.scale)] in KEPT and G.drop_reason(FINAL, c.lane, c.backend) is None)


# ------------------------------------------------------------------------------------------------ the cells of the final chain
@pytest.mark.parametrize("build", ["jvm", "native"])
def test_the_cells_per_lane_of_the_final_small_chain(build, monkeypatch):
    stages, _lanes, _skip, sizes = chain(monkeypatch, build)
    assert sizes == "small"
    have = collections.Counter(c.lane for c in cells_of(stages))
    per_size = collections.Counter((c.lane, c.scale) for c in cells_of(stages))
    print(f"\n{build} chain, --profile {FINAL}: " + ", ".join(f"{lane} {have[lane]}" for lane in LANE_ORDER) + f"; total {sum(have.values())} cells per build")
    print("  per size: " + ", ".join(f"{lane}/{sc} {n}" for (lane, sc), n in sorted(per_size.items())))
    assert have == expected_per_lane(build)          # derived from SIZE_CLASS and the stage table
    assert dict(have) == TYPED                       # the hand count
    assert len(cells_of(stages)) == len(set(cells_of(stages)))      # nothing doubled


def test_both_chains_run_the_same_cells_at_the_small_sizes(monkeypatch):
    """The one build-specific arm, the JVM image-defaults arm, runs at tpch10 only, which is a large size."""
    jvm = sorted(c.label for c in cells_of(chain(monkeypatch, "jvm")[0]))
    native = sorted(c.label for c in cells_of(chain(monkeypatch, "native")[0]))
    assert jvm == native and jvm


def test_sf1full_stays_and_every_large_size_is_gone(monkeypatch):
    """sf1full is in runner.LARGE_SCALES and a small size of graph analytics; sf10, e2_500k, lc10m, ts1000 and medium are large sizes the tuple lacks."""
    for build in ("jvm", "native"):
        stages = chain(monkeypatch, build)[0]
        pairs = {(c.lane, c.scale) for c in cells_of(stages)}
        assert pairs == SMALL_PAIRS
        assert ("l2", "sf1full") in pairs
        assert not {sc for _l, sc in pairs} & LARGE_SCALE_NAMES
        for st in stages:
            assert st[4] and not set(st[4]) & LARGE_SCALE_NAMES, st[0]
            assert all(size_classes.SIZE_CLASS[(st[2], x)] in KEPT for x in st[4]), st[0]
    # and the pairs are what SIZE_CLASS says for the lanes of this chain (restart and e4 are lanes of #137, not of the generator's table yet)
    assert SMALL_PAIRS == {(lane, sc) for (lane, sc), cls in size_classes.SIZE_CLASS.items() if cls in KEPT and lane in LANE_ORDER}


def test_the_filter_reads_size_class_and_not_the_large_scales_tuple(monkeypatch):
    base = sorted(c.label for c in cells_of(chain(monkeypatch, "jvm")[0]))
    for fake in ((), ("sf1", "tpch1", "small", "tiny", "ts100", "e2", "lc1m"), tuple(sorted(LARGE_SCALE_NAMES | {"sf1full"}))):
        monkeypatch.setattr(G, "LARGE_SCALES", fake)       # it moves stage boundaries (the tiers of subset_specs), never the cells
        assert sorted(c.label for c in cells_of(chain(monkeypatch, "jvm")[0])) == base, fake


def test_a_stage_left_with_no_scale_is_dropped(monkeypatch):
    every = chain(monkeypatch, "jvm", "full", "all")[0]
    small = chain(monkeypatch, "jvm", "full", "small")[0]
    only_large = [s for s in every if all(size_classes.SIZE_CLASS[(s[2], x)] == "large" for x in s[4])]
    assert any(G.stage_backends(s) == ["arcadedb_imgdefaults_server"] for s in only_large)        # the JVM image-defaults arm runs at tpch10 only
    assert len(small) == len(every) - len(only_large)
    assert not any("arcadedb_imgdefaults_server" in G.stage_backends(s) for s in small)
    assert all(s[4] for s in small)


def test_a_size_without_a_class_is_refused_and_never_guessed(monkeypatch):
    assert G.size_table_problems() == []
    monkeypatch.setattr(size_classes, "SIZE_CLASS", {k: v for k, v in size_classes.SIZE_CLASS.items() if k != ("l4", "ts100")})
    assert any("l4/ts100" in p and "no class" in p for p in G.size_table_problems())
    with pytest.raises(SystemExit) as e:
        G.subset_specs(["arcadedb"], ["l4"], sizes="small")
    assert "l4/ts100" in str(e.value) and "SIZE_CLASS" in str(e.value)
    assert G.subset_specs(["arcadedb"], ["l4"])         # all sizes places nothing, so it needs no class


# ------------------------------------------------------------------------------------------------ the proofs
def test_the_proofs_compare_against_the_filtered_list(monkeypatch):
    stages, lanes, skip, sizes = chain(monkeypatch, "jvm")
    plan = G.pass_plan(stages, 3, True)
    assert G.stage_problems(stages, ["arcadedb"], lanes, skip, sizes) == []
    assert G.plan_problems(stages, 3, plan, True, sizes) == []
    assert G.profile_problems(FINAL, stages) == []
    assert G.size_problems(stages, sizes) == []
    # the filtered list is not the whole table's: asked for every size, the large cells are in no stage
    assert any("is in no stage" in p for p in G.stage_problems(stages, ["arcadedb"], lanes, skip))
    # and a list with a large size in it fails the filtered proofs, the plan's and the profile's own
    whole = G.number(G.subset_specs(["arcadedb"], lanes, "biggest-last", skip, True), "qZ")
    assert any("scheduled 1 times, expected 0" in p for p in G.stage_problems(whole, ["arcadedb"], lanes, skip, "small"))
    assert any("a large size" in p for p in G.plan_problems(whole, 3, G.pass_plan(whole, 3, True), True, "small"))
    probs = G.profile_problems(FINAL, whole)
    assert any("l2/sf10" in p and "a large size" in p for p in probs) and any("lc10m" in p for p in probs)


def test_the_arms_that_are_not_on_the_page_are_left_out_and_the_others_stay(monkeypatch):
    for build in ("jvm", "native"):
        backends = {c.backend for c in cells_of(chain(monkeypatch, build)[0])}
        assert not backends & OUT_ARMS and IN_ARMS <= backends
        assert not [b for b in backends if re.search(r"int8|_pq\b|nocompact", b)]
    # `full` has them, so the profile is what leaves them out; the cells they take are the 8 per build that `full` adds
    full = cells_of(chain(monkeypatch, "jvm", "full", "small")[0])
    assert OUT_ARMS <= {c.backend for c in full}
    extra = [c for c in full if c.backend in OUT_ARMS]
    assert len(extra) == 8                                   # int8 dense: 2 arms x 2; nocompact: 1 arm x 2 sizes x 2 (lane cell and overlay)
    assert len(full) - len(extra) == sum(TYPED.values())
    # the profile's own proof names an arm it must not carry
    unskipped = G.number(G.subset_specs(["arcadedb"], G.parse_lanes(None, True, "full"), "biggest-last", (), True, "small"), "qZ")
    probs = G.profile_problems(FINAL, unskipped)
    assert any("int8" in p for p in probs) and any("nocompact" in p for p in probs)


def test_the_twins_of_the_served_cells_stay_in(monkeypatch):
    """The lean-client twin of every served ArcadeDB cell and the PostgreSQL-wire twin of the served SQL cells are the runner's jobs (build_jobs). The
    final profile drops no served arm but the int8 one, and the stage scripts pass no `--clients`, so both twins run beside their headline cell."""
    stages = chain(monkeypatch, "jvm")[0]
    served = [c for c in cells_of(stages) if c.kind == "lane" and c.backend in runner.ARCADEDB_HTTP_ARMS]
    assert {c.backend for c in served} == {"arcadedb_server", "arcadedb_graph_server", "arcadedb_e2_server", "arcadedb_sparse_server",
                                           "arcadedb_sparse_server_fp32", "arcadedb_dense_server", "arcadedb_ts_doc_server", "arcadedb_ts_native_server"}
    wired = set()
    for c in served:
        jobs = [j for j in runner.build_jobs([c.lane], [c.workload], c.scale) if j["backend"] == c.backend and j["workload"] == c.workload]
        wire = c.backend in runner.PGWIRE_SQL_ARMS.get(c.lane, ()) and c.scale not in runner.LARGE_SCALES
        assert sorted(j.get("http_client", "") for j in jobs) == sorted(["", runner.SENSITIVITY_CLIENT] + ([runner.PGWIRE_CLIENT] if wire else [])), c.label
        if wire:
            wired.add(c.lane)
    assert wired == {"l1tpc", "l3s", "l3d", "l4"}


# ------------------------------------------------------------------------------------------------ the profile and its arguments
def test_the_paper_profile_and_the_full_profile_are_what_they_were():
    assert G.PROFILES["paper-2611"]["drops"] == (G.DROP_SECOND_LIST, G.DROP_NEO4J_MEMGRAPH_DENSE, G.DROP_QUANTIZED_DENSE)
    assert G.PROFILES["full"]["drops"] == () and "sizes" not in G.PROFILES["full"] and "sizes" not in G.PROFILES["paper-2611"]
    assert G.profile_skip("paper-2611") == tuple(b for b in runner.LANES["l3d"][1] if G.engine_of(b) and G.drop_reason("paper-2611", "l3d", b))
    assert G.profile_skip("full") == () and G.profile_lanes("paper-2611") == G.CORE_LANES and G.profile_lanes("full") == LANE_ORDER
    assert G.profile_lanes(FINAL) == LANE_ORDER
    assert set(G.profile_skip(FINAL)) >= OUT_ARMS and not set(G.profile_skip(FINAL)) & IN_ARMS
    assert G.resolve_sizes("paper-2611", None) == "all" and G.resolve_sizes("full", "small") == "small" and G.resolve_sizes(FINAL, None) == "small"


def test_the_final_profile_cannot_run_at_all_sizes(tmp_path):
    out = tmp_path / "o"
    r = run(rerun_args() + ["--after", "none", "--id-prefix", "qWV", "--profile", FINAL, "--sizes", "all", "--out", str(out)])
    assert r.returncode != 0 and "REFUSING" in (r.stdout + r.stderr) and "--sizes all" in (r.stdout + r.stderr) and not list(out.glob("*.sh"))
    r = run(rerun_args() + ["--check", "--profile", FINAL, "--sizes", "all"])
    assert r.returncode != 0 and "small-size pass" in (r.stdout + r.stderr)
    r = run(rerun_args() + ["--check", "--sizes", "everything"])
    assert r.returncode != 0 and "--sizes" in r.stderr


def test_the_final_profile_implies_its_sizes_and_its_second_list():
    alone = run(rerun_args() + ["--check", "--profile", FINAL])
    assert alone.returncode == 0, alone.stdout[-600:] + alone.stderr[-400:]
    assert "lanes: l2, e2, l1tpc, l3d, l3s, l4, lifecycle" in alone.stdout and "sizes small:" in alone.stdout
    spelled = run(rerun_args() + ["--check", "--profile", FINAL, "--sizes", "small", "--second-list"])
    assert spelled.returncode == 0 and spelled.stdout == alone.stdout
    sparse = run(rerun_args() + ["--check", "--profile", FINAL, "--lanes", "sparse,lifecycle"])
    assert sparse.returncode == 0 and "lanes: l3s, lifecycle" in sparse.stdout, sparse.stdout[-400:]
    for line in ("kept    e2/e2, l1tpc/tpch1, l2/sf1, l2/sf1full, l3d/small, l3s/small, l3s/tiny, l4/ts100, lifecycle/lc100k, lifecycle/lc10k, lifecycle/lc1m",
                 "dropped e2/e2_500k (large), l1tpc/tpch10 (large), l2/sf10 (large), l3d/deep10m (large), l3s/medium (large), l4/ts1000 (large), lifecycle/lc10m (large)"):
        assert line in alone.stdout


def test_another_profile_can_take_the_small_sizes_and_a_default_call_prints_no_size_line():
    r = run(rerun_args() + ["--check", "--profile", "full", "--second-list", "--sizes", "small"])
    assert r.returncode == 0 and "lanes: l2, e2, l1tpc, l3d, l3s, l4, lifecycle" in r.stdout and "sizes small:" in r.stdout
    r = run(rerun_args() + ["--check", "--profile", "paper-2611", "--sizes", "small"])
    assert r.returncode == 0 and "lanes: l2, e2, l1tpc, l3d\n" in r.stdout, r.stdout[-500:]
    for extra in ([], ["--sizes", "all"], ["--profile", "full", "--second-list"]):
        r = run(rerun_args() + ["--check"] + extra)
        assert r.returncode == 0, r.stdout[-400:]
        assert not [l for l in r.stdout.splitlines() if l.startswith("sizes ")], extra


# ------------------------------------------------------------------------------------------------ the written drafts
def cell_labels(text):
    return re.findall(r'^[ \t]*run_(?:cell|overlay) "([A-Za-z0-9]+)/([A-Za-z0-9_]+)/', text, re.M)


def test_the_written_drafts_of_the_final_chain_lint_clean_and_hold_only_the_small_sizes(tmp_path):
    out = tmp_path / "o"
    r = run(rerun_args() + ["--after", "none", "--id-prefix", "qWV", "--profile", FINAL, "--out", str(out)])
    assert r.returncode == 0, r.stdout[-600:] + r.stderr[-400:]
    files = sorted(out.glob("qWV*.sh"))
    assert len(files) == 25                    # the pair install, and 8 stages x 3 passes
    seen = collections.Counter()
    for f in files:
        text = f.read_text()
        assert subprocess.run(["bash", "-n", str(f)], capture_output=True).returncode == 0, f.name
        for lane, scale in cell_labels(text):
            seen[(lane, scale)] += 1
            assert size_classes.SIZE_CLASS[(lane, scale)] in KEPT, (f.name, lane, scale)
        for arms in re.findall(r'^BACKENDS="([^"]*)"', text, re.M):          # the pair install has none
            assert not re.search(r"int8|nocompact", arms), f.name
    assert set(seen) == SMALL_PAIRS
    r = run(rerun_args() + ["--check", "--profile", FINAL, "--drafts", str(out)])
    assert r.returncode == 0, r.stdout[-600:]


def test_the_lint_refuses_drafts_of_all_sizes_for_the_final_profile(tmp_path):
    out = tmp_path / "o"
    r = run(rerun_args() + ["--after", "none", "--id-prefix", "qWV", "--profile", "full", "--second-list", "--lanes", "sparse,lifecycle", "--out", str(out)])
    assert r.returncode == 0, r.stdout[-600:] + r.stderr[-400:]
    r = run(rerun_args() + ["--check", "--profile", "full", "--second-list", "--lanes", "sparse,lifecycle", "--drafts", str(out)])
    assert r.returncode == 0, r.stdout[-600:]
    r = run(rerun_args() + ["--check", "--profile", FINAL, "--lanes", "sparse,lifecycle", "--drafts", str(out)])
    assert r.returncode == 1
    assert "runs l3s/medium, a large size" in r.stdout and "runs lifecycle/lc10m, a large size" in r.stdout
    assert "arcadedb_sparse_embedded_nocompact on lane l3s, which the final-small profile drops" in r.stdout


# ------------------------------------------------------------------------------------------------ the default is unchanged
def test_a_call_with_sizes_all_writes_the_drafts_of_a_call_without_it(tmp_path):
    """The byte-for-byte proof against the 26.11.1 pass is `test_the_drafts_are_the_ones_on_file` (stage_drafts_2611.sha256); this one pins the option's own
    default: `--sizes all` is no argument at all, for both chains."""
    for name, wheel in (("jvm", None), ("native", NATIVE_WHEEL)):
        args = rerun_args(wheel=wheel) if wheel else rerun_args()
        a, b = tmp_path / f"{name}-plain", tmp_path / f"{name}-all"
        for out, extra in ((a, []), (b, ["--sizes", "all"])):
            r = run(args + ["--after", "none", "--id-prefix", "qWV", "--lanes", "graph,dense,sparse", "--profile", "full", "--second-list", "--out", str(out)] + extra)
            assert r.returncode == 0, r.stdout[-600:] + r.stderr[-400:]
        names = sorted(p.name for p in a.glob("*.sh"))
        assert names and names == sorted(p.name for p in b.glob("*.sh"))
        match, mismatch, errors = filecmp.cmpfiles(a, b, names, shallow=False)
        assert mismatch == [] and errors == [] and match == names


def test_the_default_stage_lists_are_the_unfiltered_ones(monkeypatch):
    for profile in ("paper-2611", "full"):
        for build in ("jvm", "native"):
            monkeypatch.setattr(G, "CHAIN_BUILD", "native" if build == "native" else "")
            lanes = G.parse_lanes(None, profile == "full", profile)
            skip = tuple(G.profile_skip(profile)) + (tuple(G.build_less_served_arms()) if build == "native" else ())
            plain = G.subset_specs(["arcadedb"], lanes, "biggest-last", skip, True)
            assert plain == G.subset_specs(["arcadedb"], lanes, "biggest-last", skip, True, "all") == G.subset_specs(["arcadedb"], lanes, "biggest-last", skip, True, None)
            assert G.stage_problems(G.number(plain, "qZ"), ["arcadedb"], lanes, skip) == []
