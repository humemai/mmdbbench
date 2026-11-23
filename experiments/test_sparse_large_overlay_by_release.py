"""The sparse overlay of the large size is read by the release of the large rows, and `land_stage.py --large-pin` carries that pin (humemai/mmdbbench#151).

The sparse second-pass overlay (`sparse_mp_<pin>/sp_<arm>_<tier>.json`) has three tiers and the `medium` one is a LARGE size (`size_classes.SIZE_CLASS`). On the
landing of 26.12.1 the small rows carry the new pin while the large rows keep 26.11.1 until the large sizes are rerun, so the medium files sit in a directory
named by the OLD pin. The exporter read the whole directory at the landing's pin: the medium files were not found, the large sparse entries were rebuilt from the
lane rows without `warm p50 ms`, `warm p99 ms` and `gain`, and no gate failed (the same loss as #146, for the dense overlay).

The rule is the one of #146 (`size_classes.pin_of_size_class`, no second one): each tier reads the directory of its size class. `e4decomp_<pin>` holds the small
e4 size, so it stays at the landing's pin. `land_stage.py --large-pin` (default: `BENCH_LARGE_ENGINE_COMMIT`, else the landing's pin) carries the large pin to the
pulls, the overlay merge and the gates.

Plain functions with `unittest.mock`, temporary directories and synthetic payloads, so they run under the suite or as
`python test_sparse_large_overlay_by_release.py [name-substring ...]` from this directory. The exporter is imported, so numpy and pandas are needed, as
everywhere else."""
import collections
import contextlib
import glob
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

OLD, NEW = "a3a5d1245", "0123abcde"      # the commit of 26.11.1 (the large rows), and a made-up commit for the 26.12.1 landing (the small rows)
TIERS = ("medium", "small", "tiny")
WARM = ("warm p50 ms", "warm p99 ms", "gain")
VAR = "BENCH_LARGE_ENGINE_COMMIT"


def _passes(backend, tier):
    """One overlay file: pass 0 (cold) and five warm passes, with the fields the exporter reads."""
    base = {"backend": backend, "scale": tier, "lane": "l3s_mp", "build_s": 100.0, "n_docs": 1000, "n_queries": 500, "query_n": 500, "engine_version": "26.11.1"}
    return [dict(base, rep=i, query_p50_ms=80.0 if i == 0 else 10.0 + i, query_p99_ms=300.0 if i == 0 else 20.0 + i) for i in range(6)]


def _write_sparse(root, X, tiers):
    root.mkdir(parents=True, exist_ok=True)
    for arm, backend, _label in X.SPARSE_MP_ARMS:
        for tier in tiers:
            (root / f"sp_{arm}_{tier}.json").write_text(json.dumps(_passes(backend, tier)))


@contextlib.contextmanager
def _landing(large=OLD, old_dir=True, new_dir=True):
    """(exporter, scratch results dir) for a landing at the NEW pin whose large rows are on the OLD one: the medium files in sparse_mp_<OLD> (unless
    `old_dir` is false), the small and tiny ones in sparse_mp_<NEW>. Everything it moves is put back."""
    import export_web as X
    import make_paper_tables as M
    with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ), mock.patch.object(M, "RESULTS", d), \
            mock.patch.object(X, "RESULTS", Path(d)), mock.patch.object(X, "_SPLIT", False):
        os.environ["BENCH_ENGINE_COMMIT"] = NEW
        os.environ.pop(VAR, None)
        if large:
            os.environ[VAR] = large
        if old_dir:
            _write_sparse(Path(d) / f"sparse_mp_{OLD}", X, ("medium",))
        if new_dir:
            _write_sparse(Path(d) / f"sparse_mp_{NEW}", X, ("small", "tiny"))
        yield X, Path(d)


def _page(X):
    """The `l3s` table as the page prints it: the lane entries (cold only, one per arm and tier, whatever the overlay holds) with the second pass folded in
    by the exporter's own `_restructure_tables`, as a payload."""
    lane = [{"backend": label, "backend_key": backend, "build": None, "precision": X.SPARSE_PRECISION.get(backend), "scale": tier,
             "is_arcadedb": "arcade" in backend, "metrics": {"p50 ms": {"median": 80.0}, "p99 ms": {"median": 300.0}}}
            for tier in TIERS for _arm, backend, label in X.SPARSE_MP_ARMS]
    tables = [{"id": "l3s", "entries": lane, "columns": ["p50 ms", "p99 ms"], "conditions": [], "source_paths": [], "source_urls": []}]
    mp = X._sparse_multipass_table()
    if mp:
        tables.append(mp)
    X._restructure_tables(tables, [])
    return {"tables": [t for t in tables if t["id"] == "l3s"]}


def _refusal(fn, *args):
    try:
        fn(*args)
    except SystemExit as e:
        return str(e.code)
    raise AssertionError(f"{getattr(fn, '__name__', fn)} did not refuse")


def _large(payload):
    return [e for e in payload["tables"][0]["entries"] if e["scale"] == "medium"]


# ------------------------------------------------------------------------------------------------ the sparse overlay, by size class
def test_the_medium_sparse_overlay_is_found_in_the_old_pins_directory_while_the_small_rows_carry_the_new_pin():
    import size_classes as SC
    with _landing() as (X, d):
        assert [SC.SIZE_CLASS[("l3s", t)] for t in TIERS] == ["large", "small", "extra"]
        assert X._pinned_dir("sparse_mp", size_class="large") == d / f"sparse_mp_{OLD}"
        assert X._pinned_dir("sparse_mp", size_class="small") == d / f"sparse_mp_{NEW}"
        assert X._pinned_dir("sparse_mp", size_class="extra") == d / f"sparse_mp_{NEW}"
        assert X._pinned_dir("sparse_mp") == d / f"sparse_mp_{NEW}"                  # the default stays the landing's pin
        by_tier = collections.defaultdict(list)
        for e in X._sparse_multipass_table()["entries"]:
            by_tier[e["scale"]].append(e)
        assert {t: len(by_tier[t]) for t in TIERS} == {"medium": 6, "small": 6, "tiny": 6}, {t: len(v) for t, v in by_tier.items()}
        ours = lambda t: [e["version_name"] for e in by_tier[t] if e["is_arcadedb"]]    # noqa: E731
        assert len(ours("medium")) == 3 and all(OLD in v and NEW not in v for v in ours("medium")), ours("medium")
        for t in ("small", "tiny"):
            assert len(ours(t)) == 3 and all(NEW in v and OLD not in v for v in ours(t)), ours(t)


def test_a_partial_medium_overlay_refuses_and_names_the_old_directory():
    with _landing() as (X, d):
        (d / f"sparse_mp_{OLD}" / "sp_qdrant_medium.json").unlink()
        msg = _refusal(X._sparse_multipass_table)
        assert f"sparse_mp_{OLD}" in msg and "sp_qdrant_medium.json" in msg and NEW not in msg


def test_the_sparse_medium_entries_keep_their_keys_when_the_large_pin_is_named():
    import large_entry_gate as G
    with _landing() as (X, _d):
        page = _page(X)
        large = _large(page)
        assert len(large) == 6 and len(page["tables"][0]["entries"]) == 18
        for e in large:
            assert all(k in e["metrics"] for k in WARM), (e["backend"], sorted(e["metrics"]))
        assert G.lost_large_keys(page, _page(X), table="l3s", keys=G.SPARSE_KEYS) == []
        assert G.refuse_lost_large_keys(page, _page(X)) is None                       # both tables, nothing lost


def test_without_the_large_pin_and_no_directory_at_the_new_pin_the_large_entries_lose_their_keys_and_the_gate_fires():
    """What main did at a landing with a new pin and no variable: the medium overlay is looked for in sparse_mp_<NEW>, and when that is not there (the sparse
    files are not pulled yet, or the pull found none) the whole second pass is gone and nothing fails in the exporter."""
    import large_entry_gate as G
    with _landing() as (X, d):
        published = _page(X)
        os.environ.pop(VAR)
        shutil.rmtree(d / f"sparse_mp_{NEW}")
        assert X._pinned_dir("sparse_mp", size_class="large").name == f"sparse_mp_{NEW}"
        now = _page(X)                                                                # the silent part: no error here, a table with no warm columns
        assert [e["scale"] for e in now["tables"][0]["entries"]].count("medium") == 6
        assert not any(k in e["metrics"] for e in _large(now) for k in WARM)
        msg = _refusal(G.refuse_lost_large_keys, published, now)
    assert msg.startswith("REFUSING to write the payload: 6 large entries of the page lost metric keys")      # the 12 small entries are not held here
    assert msg.count("table 'l3s', entry ") == 6 and msg.count("at size 'medium': it lost warm p50 ms, warm p99 ms, gain") == 6, msg
    assert "ArcadeDB (embedded, int8)" in msg
    assert "BENCH_LARGE_ENGINE_COMMIT" in msg and "--large-pin" in msg and "sparse_mp_<that pin>" in msg and "dense_mp5" not in msg


def test_without_the_large_pin_a_landing_directory_that_holds_the_small_files_only_refuses_and_points_at_the_flag():
    with _landing() as (X, d):
        os.environ.pop(VAR)
        msg = _refusal(X._sparse_multipass_table)
        assert f"sparse_mp_{NEW} has 6 of 6 files missing" in msg and "sp_arc_int8_medium.json" in msg and OLD not in msg
        assert "BENCH_LARGE_ENGINE_COMMIT" in msg and "land_stage.py --large-pin" in msg
        os.environ[VAR] = OLD
        (d / f"sparse_mp_{NEW}" / "sp_qdrant_small.json").unlink()
        small = _refusal(X._sparse_multipass_table)
        assert "sp_qdrant_small.json" in small and "--large-pin" not in small       # a missing small file is not a large-pin problem


def test_with_the_old_directory_missing_the_gate_fires_even_with_the_large_pin_named():
    import large_entry_gate as G
    with _landing() as (X, d):
        published = _page(X)
        shutil.rmtree(d / f"sparse_mp_{OLD}")
        assert X._pinned_dir("sparse_mp", size_class="large") == d / f"sparse_mp_{OLD}"       # named, and absent: a tier not run at its pin, not an error here
        now = _page(X)
        assert not any(k in e["metrics"] for e in _large(now) for k in WARM)
        msg = _refusal(G.refuse_lost_large_keys, published, now)
    assert "6 large entries" in msg and msg.count("it lost warm p50 ms, warm p99 ms, gain") == 6


def test_one_release_for_both_classes_is_one_directory_and_nothing_moves():
    with _landing(large=None, old_dir=False, new_dir=False) as (X, d):
        _write_sparse(d / f"sparse_mp_{NEW}", X, TIERS)
        assert {X._pinned_dir("sparse_mp", size_class=c) for c in ("small", "large", "extra")} == {d / f"sparse_mp_{NEW}"}
        page = _page(X)
        assert len(page["tables"][0]["entries"]) == 18 and all(all(k in e["metrics"] for k in WARM) for e in page["tables"][0]["entries"])
        assert all(NEW in e["version_name"] for e in X._sparse_multipass_table()["entries"] if e["is_arcadedb"])


def test_the_refusal_names_the_overlay_directory_of_each_table_that_lost_keys():
    import large_entry_gate as G

    def entry(label, key, scale, metrics):
        return {"backend": label, "backend_key": key, "build": None, "precision": "fp32", "scale": scale, "metrics": {m: {} for m in metrics}}
    dense_keys, sparse_keys = ("cold p50 ms", "warm p50 ms"), ("cold p50 ms", "warm p50 ms", "gain")
    was = {"tables": [{"id": "l3d", "entries": [entry("Qdrant (fp32)", "qdrant_dense", "deep10m", dense_keys)]},
                      {"id": "l3s", "entries": [entry("Qdrant", "qdrant_sparse", "medium", sparse_keys), entry("Qdrant", "qdrant_sparse", "small", sparse_keys)]}]}
    now = {"tables": [{"id": "l3d", "entries": [entry("Qdrant (fp32)", "qdrant_dense", "deep10m", ("cold p50 ms",))]},
                      {"id": "l3s", "entries": [entry("Qdrant", "qdrant_sparse", "medium", ("cold p50 ms",)), entry("Qdrant", "qdrant_sparse", "small", ())]}]}
    msg = _refusal(G.refuse_lost_large_keys, was, now)
    assert msg.startswith("REFUSING to write the payload: 2 large entries")                # the small sparse entry is not held here
    assert "table 'l3d', entry 'Qdrant (fp32)' at size 'deep10m': it lost warm p50 ms" in msg
    assert "table 'l3s', entry 'Qdrant' at size 'medium': it lost warm p50 ms, gain" in msg
    assert "results/dense_mp5_<that pin> and results/sparse_mp_<that pin> (its medium files) are there" in msg
    only_dense = {"tables": [now["tables"][0], was["tables"][1]]}
    assert "results/dense_mp5_<that pin> is there" in _refusal(G.refuse_lost_large_keys, was, only_dense)


def test_the_sparse_keys_are_the_ones_the_exporter_folds_in_from_the_overlay():
    import large_entry_gate as G
    src = (HERE / "export_web.py").read_text(encoding="utf-8")
    assert 'for k in ("warm p50 ms", "warm p99 ms", "gain"):' in src and G.SPARSE_KEYS == ("warm p50 ms", "warm p99 ms", "gain")
    assert G.TABLE_KEYS == {"l3d": G.OVERLAY_KEYS, "l3s": G.SPARSE_KEYS}


# ------------------------------------------------------------------------------------------------ e4decomp: small, so the new pin is right
def test_the_e4_decomposition_is_a_small_size_and_stays_at_the_landings_pin():
    import size_classes as SC
    assert SC.SIZE_CLASS[("e4", "e2")] == "small"                                    # the one e4 size (200,000 documents), the corpus of e2
    with mock.patch.dict(os.environ):
        os.environ["BENCH_ENGINE_COMMIT"] = NEW
        os.environ[VAR] = OLD
        assert SC.pin_of_size_class(SC.row_size_class({"lane": "e4", "scale": "e2"})) == NEW
    exporter = (HERE / "export_web.py").read_text(encoding="utf-8").splitlines()
    e4_dir = [ln for ln in exporter if ln.startswith("E4_DIR = ")]
    assert len(e4_dir) == 1 and "BENCH_ENGINE_COMMIT" in e4_dir[0] and "LARGE" not in e4_dir[0] and "pin_of_size_class" not in e4_dir[0]
    lander = (HERE / "land_stage.py").read_text(encoding="utf-8").splitlines()
    pulls = [ln for ln in lander if "e4decomp_{args.pin}" in ln]
    assert len(pulls) >= 3 and not any("large_pin" in ln for ln in pulls), pulls


# ------------------------------------------------------------------------------------------------ land_stage.py --large-pin
def _run_main(argv, env_value=None):
    """land_stage.main() with `argv`, stopped by the refusal that comes right after the options are applied (--apply without --branch, before anything is
    pulled). Returns (BENCH_LARGE_ENGINE_COMMIT afterwards, the refusal, what --pin and the variable make the large pin by the rule)."""
    import land_stage as L
    import size_classes as SC
    with mock.patch.dict(os.environ), mock.patch.object(sys, "argv", ["land_stage.py", *argv]), mock.patch.object(L, "PY", sys.executable), \
            mock.patch.object(L.os, "execv", lambda *a, **k: None):
        os.environ.pop(VAR, None)
        if env_value:
            os.environ[VAR] = env_value
        try:
            L.main()
        except SystemExit as e:
            refusal = str(e.code)
        else:
            raise AssertionError("main() did not stop")
        return os.environ.get(VAR), refusal, SC.pin_of_size_class("large", landing=NEW)


def test_the_flag_and_the_environment_variable_agree_and_the_flag_wins():
    base = ["--pin", NEW, "--message", "m", "--apply"]            # --apply with no --branch refuses before anything is pulled
    for argv, env_value, want in (
            (base + ["--large-pin", OLD], None, OLD),             # the flag alone
            (base, OLD, OLD),                                     # the variable alone is the default
            (base + ["--large-pin", OLD], OLD, OLD),              # both, agreeing
            (base + ["--large-pin", OLD], "ffffffff0", OLD),      # both, disagreeing: the flag wins
            (base + ["--large-pin", f"  {OLD} "], None, OLD)):    # blanks around it are not part of it
        got, refusal, large = _run_main(argv, env_value)
        assert got == want and large == want and "--apply needs --branch" in refusal, (argv, env_value, got, large, refusal)


def test_with_neither_the_flag_nor_the_variable_nothing_moves():
    got, refusal, large = _run_main(["--pin", NEW, "--message", "m", "--apply"])
    assert got is None and large == NEW and "--apply needs --branch" in refusal      # the variable is not written, the large pin is the landing's
    got, _refusal_text, large = _run_main(["--pin", NEW, "--message", "m", "--apply", "--large-pin", "  "])
    assert got is None and large == NEW                                              # a blank flag is no flag


def test_the_flag_is_in_the_help_text_and_names_both_directories():
    import land_stage as L
    out = io.StringIO()
    with mock.patch.dict(os.environ), mock.patch.object(sys, "argv", ["land_stage.py", "--help"]), mock.patch.object(L, "PY", sys.executable), \
            mock.patch.object(L.os, "execv", lambda *a, **k: None), contextlib.redirect_stdout(out):
        try:
            L.main()
        except SystemExit as e:
            assert e.code == 0
    text = " ".join(out.getvalue().split())
    assert "--large-pin COMMIT" in text and "BENCH_LARGE_ENGINE_COMMIT" in text and "dense_mp5_<COMMIT>" in text and "sparse_mp_<COMMIT>" in text


class _Host:
    """A fake bench host: `scp host:path dest` copies from a local directory, globs included, and records the commands."""

    def __init__(self, root):
        self.root, self.calls = Path(root), []

    def put(self, directory, *names):
        (self.root / directory).mkdir(parents=True, exist_ok=True)
        for n in names:
            (self.root / directory / n).write_text(f"{directory}/{n}")

    def scp(self, cmd, check=True):
        self.calls.append(cmd[-2].split(":", 1)[1].replace(str(self.root), "<host>"))
        got = glob.glob(cmd[-2].split(":", 1)[1])
        for g in got:
            shutil.copy(g, cmd[-1])


def test_the_pulls_read_the_large_overlays_at_the_large_pin_and_the_rest_at_the_landings():
    import land_stage as L
    with tempfile.TemporaryDirectory() as t, mock.patch.object(L, "HOST", "mini"):
        host, res = _Host(Path(t) / "host"), Path(t) / "results"
        res.mkdir()
        with mock.patch.object(L, "REMOTE", str(host.root)):
            # the host holds the old release's directories (all tiers, as the 26.11.1 chain wrote them) and the new release's (the small size)
            host.put(L.host_name("sparse_mp", OLD), "sp_qdrant_medium.json", "sp_qdrant_small.json", "sp_qdrant_tiny.json")
            host.put(L.host_name("sparse_mp", NEW), "sp_qdrant_small.json", "sp_qdrant_tiny.json", "sp_arc_int8_native_small.json")
            host.put(L.host_name("dense_mp5", OLD), "mp_fp32_b1.json")
            host.put(L.host_name("dense_mp5_small", NEW), "mp_fp32_b1.json")
            host.put(L.host_name("dense_mp5", NEW), "mp_fp32_b1.json")                        # what the landing used to pull for the large size
            L.pull_sparse_overlays(NEW, OLD, results=res, scp=host.scp)
            L.pull_overlay_arm("fp32", NEW, OLD, results=res, scp=host.scp)
        names = lambda d: sorted(p.name for p in (res / d).glob("*.json"))     # noqa: E731
        assert names(f"sparse_mp_{OLD}") == ["sp_qdrant_medium.json"]                         # only the medium file: the old small and tiny files stay on the host
        assert names(f"sparse_mp_{NEW}") == ["sp_arc_int8_native_small.json", "sp_qdrant_small.json", "sp_qdrant_tiny.json"]
        assert names(f"dense_mp5_{OLD}") == ["mp_fp32_b1.json"] and names(f"dense_mp5_small_{NEW}") == ["mp_fp32_b1.json"]
        assert (res / f"dense_mp5_{OLD}" / "mp_fp32_b1.json").read_text() == f"{L.host_name('dense_mp5', OLD)}/mp_fp32_b1.json"
        assert not (res / f"dense_mp5_{NEW}").exists()                                        # no empty dense_mp5_<new pin>
        assert any(c.startswith(f"<host>/{L.host_name('sparse_mp', OLD)}/sp_*_medium.json") for c in host.calls), host.calls


def test_with_one_pin_the_pulls_are_the_ones_of_before():
    import land_stage as L
    assert L.sparse_pulls(NEW, NEW) == [(NEW, "sp_*.json")]
    assert L.sparse_pulls(NEW, OLD) == [(NEW, "sp_*_tiny.json"), (NEW, "sp_*_small.json"), (OLD, "sp_*_medium.json")]
    with tempfile.TemporaryDirectory() as t, mock.patch.object(L, "HOST", "mini"):
        host, res = _Host(Path(t) / "host"), Path(t) / "results"
        res.mkdir()
        with mock.patch.object(L, "REMOTE", str(host.root)):
            host.put(L.host_name("sparse_mp", NEW), *(f"sp_qdrant_{tier}.json" for tier in TIERS))
            host.put(L.host_name("dense_mp5", NEW), "mp_fp32_b1.json")
            host.put(L.host_name("dense_mp5_small", NEW), "mp_fp32_b1.json")
            L.pull_sparse_overlays(NEW, NEW, results=res, scp=host.scp)
            L.pull_overlay_arm("fp32", NEW, NEW, results=res, scp=host.scp)
            L.pull_sparse_overlays("deadbeef0", "deadbeef0", results=res, scp=host.scp)    # nothing on the host: the directory is not left empty
        assert host.calls[0] == f"<host>/{L.host_name('sparse_mp', NEW)}/sp_*.json"
        assert sorted(p.name for p in res.iterdir()) == sorted([f"sparse_mp_{NEW}", f"dense_mp5_{NEW}", f"dense_mp5_small_{NEW}"])
        assert len(list((res / f"sparse_mp_{NEW}").glob("sp_*.json"))) == 3


def test_the_overlay_merge_targets_the_large_pins_directory_for_the_large_size():
    import land_stage as L
    with tempfile.TemporaryDirectory() as t:
        res, comp, arc = Path(t) / "res", Path(t) / "comp", Path(t) / "arc"
        for p in (res, comp, arc):
            p.mkdir()
        for stem, pin in (("dense_mp5", OLD), ("dense_mp5_small", NEW)):
            (comp / f"{stem}_{pin}").mkdir()
            (comp / f"{stem}_{pin}" / "mp_qdrant_b1.json").write_text("[]")
        specs = [f"old:{OLD}:{comp}", f"new:{NEW}:{comp}"]
        L.apply_overlay_merge(specs, [], NEW, results=res, large_pin=OLD)
        assert sorted(p.name for p in res.iterdir()) == sorted([f"dense_mp5_{OLD}", f"dense_mp5_small_{NEW}"])
        assert (res / f"dense_mp5_{OLD}" / "mp_qdrant_b1.json").is_file() and (res / f"dense_mp5_small_{NEW}" / "mp_qdrant_b1.json").is_file()
        res2 = Path(t) / "res2"
        res2.mkdir()
        L.apply_overlay_merge([f"old:{OLD}:{comp}"], [], NEW, results=res2)              # no large pin: both targets at the landing's pin, as before
        assert sorted(p.name for p in res2.iterdir()) == [f"dense_mp5_{NEW}"]


if __name__ == "__main__":
    names = [n for n in sorted(globals()) if n.startswith("test_") and (len(sys.argv) < 2 or any(a in n for a in sys.argv[1:]))]
    for n in names:
        globals()[n]()
        print("ok", n)
    print(len(names), "passed")
