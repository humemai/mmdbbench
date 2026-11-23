"""The overlay of the large rows is read by the release of the large rows, and a large entry keeps its metric keys (humemai/mmdbbench#146).

Until the full benchmark of the large sizes the small rows of the page move to a new release (26.12.1) while the large rows (the 9.99M dense build)
keep the numbers of 26.11.1, and their overlay sits in `dense_mp5_<old pin>`. `dense_mp_dir()` read `dense_mp5_<BENCH_ENGINE_COMMIT>`, so at the new
pin it found no overlay, the large dense entries were rebuilt from the lane rows (one fewer, no `warm p50 ms`, no `warm p99 ms`) and no gate failed.

The rule (size_classes.pin_of_size_class): the small and extra classes read the landing's pin, the large class reads BENCH_LARGE_ENGINE_COMMIT when the
landing names it and the landing's pin otherwise. The gate (large_entry_gate.refuse_lost_large_keys, called by the exporter before it writes the payload):
a large dense entry that had overlay keys in the published payload and lost them, or is gone, refuses the write.

Plain functions with `unittest.mock` and no fixture, so they run under the suite or as `python test_large_overlay_by_release.py [name-substring ...]` from
this directory. The exporter is imported, so numpy and pandas are needed, as everywhere else."""
import contextlib
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

OLD, NEW = "a3a5d1245", "0123abcde"      # the commit of 26.11.1 (the large rows), and a made-up commit for the 26.12.1 landing (the small rows)
# twelve arms of the dense overlay: the four ArcadeDB arms and eight comparators (the landing names its arms with BENCH_MP_ARMS)
ARMS = ("fp32", "int8", "arcsrv", "arcsrv_int8", "qdrant", "chroma", "duckvss", "lancedb", "milvus", "milvus_int8", "qdrant_int8", "sqlitevec")
WARM = ("warm p50 ms", "warm p99 ms")


def _passes(backend, scale):
    """One overlay file: pass 0 (cold) and four warm passes, with the fields the exporter reads."""
    base = {"backend": backend, "scale": scale, "build_s": 100.0, "ingest_s": 10.0, "index_s": 90.0, "engine_version": "26.11.1", "lib_version": "26.11.1"}
    return [dict(base, rep=i + 1, p50=10.0 + i, p99=20.0 + i, recall_at_10=0.95) for i in range(5)]


def _write_overlay(root, X, scale, builds=3):
    root.mkdir(parents=True, exist_ok=True)
    key = {arm: backend for arm, backend, _label, _ours in X.DENSE_10M_ARMS}
    for arm in ARMS:
        for b in range(1, builds + 1):
            (root / f"mp_{arm}_b{b}.json").write_text(json.dumps(_passes(key[arm], scale)))


@contextlib.contextmanager
def _landing(large=OLD, old_dir=True, build_small=True):
    """(exporter, make_paper_tables, scratch results dir) for a landing at the NEW pin whose large rows are on the OLD one: the large overlay in
    dense_mp5_<OLD> (unless `old_dir` is false), the small one in dense_mp5_small_<NEW>. Everything it moves is put back."""
    import export_web as X
    import make_paper_tables as M
    with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ), mock.patch.object(M, "RESULTS", d), \
            mock.patch.object(X, "RESULTS", Path(d)), mock.patch.object(X, "_SPLIT", False):
        os.environ.update({"BENCH_ENGINE_COMMIT": NEW, "BENCH_MP_ARMS": ",".join(ARMS), "BENCH_MP_BUILDS": "3"})
        os.environ.pop("BENCH_LARGE_ENGINE_COMMIT", None)
        if large:
            os.environ["BENCH_LARGE_ENGINE_COMMIT"] = large
        if old_dir:
            _write_overlay(Path(d) / f"dense_mp5_{OLD}", X, "deep10m")
        if build_small:
            _write_overlay(Path(d) / f"dense_mp5_small_{NEW}", X, "small")
        yield X, M, Path(d)


def _refusal(fn, *args):
    try:
        fn(*args)
    except SystemExit as e:
        return str(e.code)
    raise AssertionError(f"{getattr(fn, '__name__', fn)} did not refuse")


# ------------------------------------------------------------------------------------------------ the rule
def test_a_size_class_reads_one_pin_and_the_large_class_may_read_another():
    import size_classes as SC
    with mock.patch.dict(os.environ):
        os.environ["BENCH_ENGINE_COMMIT"] = f" {NEW} "
        os.environ.pop("BENCH_LARGE_ENGINE_COMMIT", None)
        assert {c: SC.pin_of_size_class(c) for c in SC.SIZE_CLASSES} == {"small": NEW, "large": NEW, "extra": NEW}   # one release: nothing moves
        os.environ["BENCH_LARGE_ENGINE_COMMIT"] = "   "
        assert SC.pin_of_size_class("large") == NEW                                                                  # blank is unset
        os.environ["BENCH_LARGE_ENGINE_COMMIT"] = OLD
        assert {c: SC.pin_of_size_class(c) for c in SC.SIZE_CLASSES} == {"small": NEW, "large": OLD, "extra": NEW}
        os.environ.pop("BENCH_ENGINE_COMMIT")
        assert SC.pin_of_size_class("small") == ""                                                                   # unset stays unset: the resolvers refuse it
        assert "one of small, large, extra" in _refusal_value(SC.pin_of_size_class, "medium")


def _refusal_value(fn, *args):
    try:
        fn(*args)
    except ValueError as e:
        return str(e)
    raise AssertionError("expected a ValueError")


def test_the_large_overlay_is_found_in_the_old_pins_directory_and_the_small_one_in_the_new_pins():
    with _landing() as (_X, M, d):
        assert M.dense_mp_dir() == str(d / f"dense_mp5_{OLD}")
        assert M.dense_mp_small_dir() == str(d / f"dense_mp5_small_{NEW}")
        assert M.mp_arms_present(small=False) == ARMS


def test_without_the_variable_both_sizes_read_the_landings_pin_as_before():
    with _landing(large=None, old_dir=False) as (_X, M, d):
        assert M.dense_mp_dir() == str(d / f"dense_mp5_{NEW}")                       # absent: the dense arm has not run at this pin
        assert not os.path.isdir(M.dense_mp_dir())
        assert M.dense_mp_small_dir() == str(d / f"dense_mp5_small_{NEW}")


def test_a_partial_overlay_at_the_old_pin_refuses_and_names_that_directory():
    with _landing() as (_X, M, d):
        (d / f"dense_mp5_{OLD}" / "mp_qdrant_b3.json").unlink()
        msg = _refusal(M.dense_mp_dir)
        assert f"dense_mp5_{OLD}" in msg and "mp_qdrant_b3.json" in msg and NEW not in msg


# ------------------------------------------------------------------------------------------------ the exporter
def test_the_twelve_large_entries_keep_their_keys_and_the_old_commit_while_the_small_rows_carry_the_new_one():
    with _landing() as (X, _M, _d):
        large = X._dense_overlay_entries("deep10m")
        small = X._dense_overlay_entries("small")
        assert len(large) == 12 and len(small) == 12, (len(large), len(small))
        for e in large:
            assert all(k in e["metrics"] for k in WARM), (e["backend"], sorted(e["metrics"]))
        ours = [e for e in large if e["is_arcadedb"]]
        assert len(ours) == 4 and all(OLD in e["version_name"] and NEW not in e["version_name"] for e in ours), [e["version_name"] for e in ours]
        assert all(NEW in e["version_name"] and OLD not in e["version_name"] for e in small if e["is_arcadedb"])


def test_the_gate_holds_the_keys_the_overlay_supplies():
    """large_entry_gate.OVERLAY_KEYS is what _dense_overlay_entries builds from the overlay files, the campaign-supplied columns apart."""
    import large_entry_gate as G
    with _landing() as (X, _M, _d):
        e = next(e for e in X._dense_overlay_entries("deep10m") if e["is_arcadedb"])
    assert set(e["metrics"]) - {"peak memory GiB", "disk GiB"} == set(G.OVERLAY_KEYS), sorted(e["metrics"])


def test_the_overlay_of_the_large_rows_is_checked_for_another_clients_stamp():
    with _landing() as (X, _M, d):
        X._refuse_other_client_overlays()                                            # clean: no refusal
        fp = d / f"dense_mp5_{OLD}" / "mp_arcsrv_b1.json"
        fp.write_text(json.dumps([dict(p, arcadedb_http_client="arcadedb-driver 0.2.0 (sync, httpx)") for p in json.loads(fp.read_text())]))
        assert f"dense_mp5_{OLD}/mp_arcsrv_b1.json" in _refusal(X._refuse_other_client_overlays)


def test_with_the_old_directory_missing_the_large_entries_are_rebuilt_without_keys_and_the_gate_fires():
    import large_entry_gate as G
    with _landing() as (X, _M, d):
        published = {"tables": [{"id": "l3d", "entries": X._dense_overlay_entries("deep10m") + X._dense_overlay_entries("small")}]}
        assert len(published["tables"][0]["entries"]) == 24
        for fp in (d / f"dense_mp5_{OLD}").iterdir():
            fp.unlink()
        (d / f"dense_mp5_{OLD}").rmdir()
        assert X._dense_overlay_entries("deep10m") == []                             # the silent part: no overlay, no error here
        small = X._dense_overlay_entries("small")
        # what the table builder then keeps of the large rows: the lane rows, cold only, and one arm fewer
        lane = [dict(e, metrics={k: v for k, v in e["metrics"].items() if k not in WARM}) for e in published["tables"][0]["entries"][:11]]
        msg = _refusal(G.refuse_lost_large_keys, published, {"tables": [{"id": "l3d", "entries": lane + small}]})
    assert "table 'l3d'" in msg and "warm p50 ms" in msg and "warm p99 ms" in msg
    assert "12 large entries" in msg and msg.count("it lost") == 11 and msg.count("the entry is gone") == 1
    gone = published["tables"][0]["entries"][11]
    assert f"entry {gone['backend']!r} at size 'deep10m': the entry is gone, it had" in msg
    assert "BENCH_LARGE_ENGINE_COMMIT" in msg


def test_the_exporter_runs_the_gate_on_the_published_payload_before_it_writes():
    src = (HERE / "export_web.py").read_text(encoding="utf-8")
    at_gate, at_write = src.index("_LG.refuse_lost_large_keys(_published, payload)"), src.index("OUT.write_text(json.dumps(payload")
    assert 0 < src.index("_published = json.loads(OUT.read_text(encoding=\"utf-8\"))") < at_gate < at_write


# ------------------------------------------------------------------------------------------------ the gate, on plain dictionaries
def _entry(label, key="qdrant_dense", scale="deep10m", metrics=None, build=None, precision="fp32"):
    return {"backend": label, "backend_key": key, "build": build, "precision": precision, "scale": scale,
            "metrics": dict(metrics if metrics is not None else {"cold p50 ms": {}, "warm p50 ms": {}, "warm p99 ms": {}, "recall@10": {}})}


def _page(*entries, table="l3d"):
    return {"tables": [{"id": table, "entries": list(entries)}]}


def test_a_large_entry_that_lost_a_key_is_named_with_the_table_the_entry_and_the_key():
    import large_entry_gate as G
    was = _page(_entry("Qdrant (fp32)"))
    now = _page(_entry("Qdrant (fp32)", metrics={"cold p50 ms": {}, "warm p50 ms": {}, "recall@10": {}}))
    assert G.lost_large_keys(was, now) == ["table 'l3d', entry 'Qdrant (fp32)' at size 'deep10m': it lost warm p99 ms"]
    msg = _refusal(G.refuse_lost_large_keys, was, now)
    assert msg.startswith("REFUSING to write the payload: 1 large entry of the page lost metric keys")


def test_a_gone_entry_is_refused_and_a_renamed_one_is_not():
    import large_entry_gate as G
    was = _page(_entry("Qdrant (fp32)"), _entry("Chroma (fp32)", key="chroma_dense"))
    assert G.lost_large_keys(was, _page(_entry("Qdrant (fp32)"))) == [
        "table 'l3d', entry 'Chroma (fp32)' at size 'deep10m': the entry is gone, it had cold p50 ms, warm p50 ms, warm p99 ms, recall@10"]
    renamed = _page(_entry("Qdrant", key="qdrant_dense"), _entry("Chroma", key="chroma_dense"))
    assert G.lost_large_keys(was, renamed) == []                                     # a label is not the entry: the backend key, build and precision are


def test_the_gate_reads_only_large_entries_of_a_table_both_payloads_carry_and_never_a_gain():
    import large_entry_gate as G
    small = _entry("Qdrant (fp32)", scale="small")
    bare = _entry("Qdrant (fp32)", metrics={"cold p50 ms": {}})
    assert G.lost_large_keys(_page(small), _page(dict(small, metrics={}))) == []                     # a small entry is not held here
    assert G.lost_large_keys(_page(bare), _page(_entry("Qdrant (fp32)", metrics={"cold p50 ms": {}, "warm p50 ms": {}}))) == []   # more keys than before
    assert G.lost_large_keys(None, _page(bare)) == [] and G.lost_large_keys({}, _page(bare)) == []   # no published payload: nothing to keep
    assert G.lost_large_keys(_page(bare), _page(bare, table="l2")) == []                              # a scoped landing without the dense table
    other = _page(_entry("Postgres", key="pg", metrics={"p50 ms": {}}))
    assert G.lost_large_keys(other, _page(_entry("Postgres", key="pg", metrics={}))) == []            # keys the overlay does not supply are not held


def test_two_entries_of_one_identity_are_read_together():
    import large_entry_gate as G
    was = _page(_entry("Qdrant (fp32)", metrics={"warm p50 ms": {}}))
    now = _page(_entry("Qdrant (fp32)", metrics={"cold p50 ms": {}}), _entry("Qdrant (fp32)", metrics={"warm p50 ms": {}}))
    assert G.lost_large_keys(was, now) == []


if __name__ == "__main__":
    names = [n for n in sorted(globals()) if n.startswith("test_") and (len(sys.argv) < 2 or any(a in n for a in sys.argv[1:]))]
    for n in names:
        globals()[n]()
        print("ok", n)
    print(len(names), "passed")
