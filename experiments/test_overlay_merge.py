"""overlay_merge and land_stage's --overlay-merge / --post-file (humemai/mmdbbench#28 and #29): the overlay of a landing that holds two engine pins,
or a live and a catch-up directory, is built into the one directory the resolver reads, and a name collision never overwrites silently.

Light: temporary files only. Run with pytest, or as plain functions from this directory."""
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("BENCH_ENGINE_COMMIT", "abc123def")
import overlay_merge as OM  # noqa: E402

LEAN_C = "lean_http (http.client, keep-alive)"
DRIVER_C = "arcadedb-driver 0.4.0 (sync, httpx)"


def _dir():
    return Path(tempfile.mkdtemp(prefix="overlay-merge-"))


def _put(d, name, mark="x", **p0):
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps([dict({"build_s": 1.0, "mark": mark}, **p0), {"p50": 1.0}]), encoding="utf-8")


def test_two_pins_merge_into_one_directory_and_the_manifest_names_each_source():
    comp, arc, out = _dir(), _dir(), _dir() / "dense_mp5_a3a5d1245"
    _put(comp, "mp_qdrant_b1.json"); _put(comp, "mp_duckvss_b1.json")
    _put(arc, "mp_fp32_b1.json"); _put(arc, "mp_fp32_native_b1.json")
    OM.merge([("comparators@e85469273", comp), ("arcadedb@a3a5d1245", arc)], out)
    assert sorted(p.name for p in out.glob("mp_*.json")) == ["mp_duckvss_b1.json", "mp_fp32_b1.json", "mp_fp32_native_b1.json", "mp_qdrant_b1.json"]
    man = (out / "MANIFEST.txt").read_text()
    assert "mp_qdrant_b1.json\tcomparators@e85469273" in man and "mp_fp32_b1.json\tarcadedb@a3a5d1245" in man


def test_a_name_collision_with_other_bytes_refuses_and_names_both_sources():
    a, b, out = _dir(), _dir(), _dir() / "o"
    _put(a, "mp_fp32_b1.json", mark="live"); _put(b, "mp_fp32_b1.json", mark="catchup")
    try:
        OM.merge([("live", a), ("catchup", b)], out)
    except SystemExit as e:
        assert "mp_fp32_b1.json" in str(e) and "live" in str(e) and "catchup" in str(e)
    else:
        raise AssertionError("expected a refusal")
    assert not out.exists() or not list(out.glob("mp_*.json"))      # nothing was written


def test_the_same_bytes_under_one_name_are_not_a_collision():
    a, b, out = _dir(), _dir(), _dir() / "o"
    _put(a, "mp_fp32_b1.json"); _put(b, "mp_fp32_b1.json")
    assert len(OM.merge([("a", a), ("b", b)], out)) == 1


def test_a_lean_file_replaces_a_driver_or_wire_file_and_never_the_reverse():
    a, b, out = _dir(), _dir(), _dir() / "o"
    _put(a, "mp_arcsrv_b1.json", arcadedb_http_client=DRIVER_C, arcadedb_http_client_role="headline")
    _put(a, "mp_arcsrv_b2.json", arcadedb_http_client="psycopg", arcadedb_client_wire="pgwire")
    _put(b, "mp_arcsrv_b1.json", arcadedb_http_client=LEAN_C); _put(b, "mp_arcsrv_b2.json", arcadedb_http_client=LEAN_C)
    OM.merge([("live", a), ("lean-rerun", b)], out)
    assert OM.client_of(out / "mp_arcsrv_b1.json") == OM.LEAN and OM.client_of(out / "mp_arcsrv_b2.json") == OM.LEAN
    assert "replaced" in (out / "MANIFEST.txt").read_text()
    out2 = _dir() / "o2"
    OM.merge([("lean-rerun", b), ("live", a)], out2)            # the order of the sources does not matter: the lean file stays
    assert OM.client_of(out2 / "mp_arcsrv_b1.json") == OM.LEAN


def test_excluding_an_arm_drops_its_jvm_and_native_files_and_no_other_arm():
    a, out = _dir(), _dir() / "o"
    for n in ("mp_arcsrv_b1.json", "mp_arcsrv_native_b1.json", "mp_arcsrv_int8_b1.json", "mp_fp32_b1.json"):
        _put(a, n)
    OM.merge([("a", a)], out, exclude_arms=("arcsrv",))
    assert sorted(p.name for p in out.glob("mp_*.json")) == ["mp_arcsrv_int8_b1.json", "mp_fp32_b1.json"]


def test_an_existing_target_directory_is_a_source_so_a_stale_file_collides():
    a, out = _dir(), _dir() / "o"
    _put(a, "mp_fp32_b1.json", mark="new"); _put(out, "mp_fp32_b1.json", mark="stale")
    try:
        OM.merge([("existing", out), ("new", a)], out)
    except SystemExit as e:
        assert "existing" in str(e)
    else:
        raise AssertionError("expected a refusal")


def test_land_stage_builds_both_sizes_from_labelled_sources_and_refuses_a_malformed_spec():
    import land_stage as L
    res, comp, arc = _dir(), _dir(), _dir()
    _put(comp / "dense_mp5_e85469273", "mp_qdrant_b1.json"); _put(comp / "dense_mp5_small_e85469273", "mp_qdrant_b1.json")
    _put(arc / "dense_mp5_a3a5d1245_2611", "mp_fp32_b1.json"); _put(arc / "dense_mp5_a3a5d1245_2611", "mp_arcsrv_b1.json")
    L.apply_overlay_merge([f"comparators:e85469273:{comp}", f"arcadedb:a3a5d1245:{arc}"], ["arcsrv"], "a3a5d1245", results=res)
    assert sorted(p.name for p in (res / "dense_mp5_a3a5d1245").glob("mp_*.json")) == ["mp_fp32_b1.json", "mp_qdrant_b1.json"]
    assert [p.name for p in (res / "dense_mp5_small_a3a5d1245").glob("mp_*.json")] == ["mp_qdrant_b1.json"]
    try:
        L.apply_overlay_merge(["nonsense"], [], "a3a5d1245", results=res)
    except SystemExit as e:
        assert "LABEL:PIN:DIR" in str(e)
    else:
        raise AssertionError("expected a refusal")


def test_post_rows_come_from_the_named_file_and_a_missing_file_never_falls_back_to_the_host():
    import land_stage as L
    d = _dir()
    src = d / "merged.jsonl"; src.write_text('{"run_id": "x"}\n')
    dest = d / "out.jsonl"
    calls = []
    L.pull_post_rows(str(src), "a3a5d1245", "post2", dest, scp=lambda *a, **k: calls.append(a))
    assert dest.read_text() == src.read_text() and calls == []
    try:
        L.pull_post_rows(str(d / "nope.jsonl"), "a3a5d1245", "post2", dest, scp=lambda *a, **k: calls.append(a))
    except SystemExit as e:
        assert "nope.jsonl" in str(e) and calls == []
    else:
        raise AssertionError("expected a refusal")
    L.pull_post_rows("", "a3a5d1245", "post2", dest, scp=lambda *a, **k: calls.append(a))
    assert len(calls) == 1


# humemai/mmdbbench#87: the decision is made once per file name, over all candidates, so it does not depend on the order of the sources
def test_a_lean_file_decides_over_a_driver_file_and_a_wire_file_whatever_the_order():
    live, catchup, lean = _dir(), _dir(), _dir()
    _put(live, "mp_arcsrv_b1.json", mark="live", arcadedb_http_client=DRIVER_C, arcadedb_http_client_role="headline")
    _put(catchup, "mp_arcsrv_b1.json", mark="wire", arcadedb_http_client="psycopg", arcadedb_client_wire="pgwire")
    _put(lean, "mp_arcsrv_b1.json", mark="lean", arcadedb_http_client=LEAN_C)
    for order in (("live", "catchup", "lean"), ("lean", "live", "catchup"), ("catchup", "lean", "live")):
        srcs = {"live": live, "catchup": catchup, "lean": lean}
        out = _dir() / "o"
        OM.merge([(n, srcs[n]) for n in order], out)
        assert OM.client_of(out / "mp_arcsrv_b1.json") == OM.LEAN, order
        assert "replaced" in (out / "MANIFEST.txt").read_text()


def test_a_driver_file_and_a_wire_file_with_no_lean_file_still_refuse_and_name_both():
    live, catchup, out = _dir(), _dir(), _dir() / "o"
    _put(live, "mp_arcsrv_b1.json", mark="live", arcadedb_http_client=DRIVER_C, arcadedb_http_client_role="headline")
    _put(catchup, "mp_arcsrv_b1.json", mark="wire", arcadedb_http_client="psycopg", arcadedb_client_wire="pgwire")
    try:
        OM.merge([("live", live), ("catchup", catchup)], out)
    except SystemExit as e:
        assert "live" in str(e) and "catchup" in str(e) and "mp_arcsrv_b1.json" in str(e)
    else:
        raise AssertionError("expected a refusal")


def test_two_different_lean_files_refuse():
    a, b, out = _dir(), _dir(), _dir() / "o"
    _put(a, "mp_arcsrv_b1.json", mark="one", arcadedb_http_client=LEAN_C); _put(b, "mp_arcsrv_b1.json", mark="two", arcadedb_http_client=LEAN_C)
    try:
        OM.merge([("a", a), ("b", b)], out)
    except SystemExit as e:
        assert "mp_arcsrv_b1.json" in str(e)
    else:
        raise AssertionError("expected a refusal")


# humemai/mmdbbench#62: the three jobs of a served ArcadeDB cell (vendor driver, lean twin, PostgreSQL-wire twin) wrote ONE overlay file name, so the
# last job to finish kept the file. The name now carries the client, and a reader that asks for the plain name gets the lean client's file.
_STAMPS = {"official": dict(arcadedb_http_client=DRIVER_C, arcadedb_http_client_role="headline"),
           "lean": dict(arcadedb_http_client=LEAN_C, arcadedb_http_client_role="sensitivity"),
           "pgwire": dict(arcadedb_http_client="psycopg", arcadedb_http_client_role="sensitivity", arcadedb_client_wire="pgwire")}


def _served_jobs(backend, lane, scale, out_dir):
    import runner
    jobs = [dict(j, driver="x_driver.py", driver_out_dir=out_dir) for j in runner.build_jobs([lane], [], scale=scale) if j["backend"] == backend]
    return runner, {(j.get("http_client") or "official"): j for j in jobs}


def _with_results(runner, root, fn, **env):
    saved, old = runner.RESULTS, {k: os.environ.get(k) for k in env}
    runner.RESULTS = str(root)
    os.environ.update(env)
    try:
        return fn()
    finally:
        runner.RESULTS = saved
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_the_three_clients_of_one_arm_size_and_rep_write_three_files_and_the_lean_one_survives():
    root = _dir()
    runner, jobs = _served_jobs("arcadedb_dense_server", "l3d", "small", "dense_mp5_small_x")
    assert sorted(jobs) == ["lean", "official", "pgwire"]                    # the small tier runs all three
    paths = _with_results(runner, root, lambda: {c: Path(runner._driver_out(j, 1)) for c, j in jobs.items()})
    assert len(set(paths.values())) == 3, paths                               # FAILS on the old runner: one name, mp_arcsrv_b1.json
    assert {c: p.name for c, p in paths.items()} == {"official": "mp_arcsrv_clientofficial_b1.json", "lean": "mp_arcsrv_clientlean_b1.json",
                                                     "pgwire": "mp_arcsrv_clientpgwire_b1.json"}
    assert {p.parent for p in paths.values()} == {root / "dense_mp5_small_x"}
    # the order of the deep10m pass that lost the files: the lean twin first, then the others
    for c in ("lean", "official", "pgwire"):
        _put(paths[c].parent, paths[c].name, mark=c, **_STAMPS[c])
    assert OM.client_of(paths["lean"]) == OM.LEAN and json.loads(paths["lean"].read_text())[0]["mark"] == "lean"
    assert OM.files(paths["lean"].parent, "mp_arcsrv_b*.json") == [str(paths["lean"])]
    assert OM.pick(paths["lean"].parent, "mp_arcsrv_b1.json") == str(paths["lean"])
    # the container path names the same file
    inside = _with_results(runner, root, lambda: runner._driver_out(jobs["lean"], 1, container=True))
    assert inside == "/work/results/dense_mp5_small_x/mp_arcsrv_clientlean_b1.json"


def test_the_large_tier_writes_two_files_and_the_native_and_sparse_names_carry_the_client_too():
    root = _dir()
    runner, jobs = _served_jobs("arcadedb_dense_server", "l3d", "deep10m", "dense_mp5_x")
    assert sorted(jobs) == ["lean", "official"]
    native = _with_results(runner, root, lambda: {c: os.path.basename(runner._driver_out(j, 2)) for c, j in jobs.items()},
                           BENCH_DRIVER_OUT_FMT="mp_{label}_native_b{rep}.json")
    assert native == {"official": "mp_arcsrv_clientofficial_native_b2.json", "lean": "mp_arcsrv_clientlean_native_b2.json"}
    assert OM.plain_name(native["lean"]) == "mp_arcsrv_native_b2.json" and OM.arm_of(native["lean"]) == "arcsrv"
    runner, sp = _served_jobs("arcadedb_sparse_server", "l3s", "small", "sparse_mp_x")
    names = _with_results(runner, root, lambda: {c: os.path.basename(runner._driver_out(j, 1, scale="small")) for c, j in sp.items()},
                          BENCH_DRIVER_OUT_FMT="sp_{label}_{scale}.json")
    assert names == {"official": "sp_arc_srv_clientofficial_small.json", "lean": "sp_arc_srv_clientlean_small.json",
                     "pgwire": "sp_arc_srv_clientpgwire_small.json"}
    assert OM.plain_name(names["lean"]) == "sp_arc_srv_small.json"


def test_an_arm_with_no_client_axis_keeps_its_file_name():
    import runner
    root = _dir()
    for backend, name in (("arcadedb_dense_embedded", "mp_fp32_b1.json"), ("qdrant_dense", "mp_qdrant_b1.json")):
        jobs = [dict(j, driver="x_driver.py", driver_out_dir="d") for j in runner.build_jobs(["l3d"], [], scale="small") if j["backend"] == backend]
        assert len(jobs) == 1
        assert _with_results(runner, root, lambda: os.path.basename(runner._driver_out(jobs[0], 1))) == name
    assert OM.label_for("fp32", "") == "fp32" and OM.client_in_name("mp_fp32_b1.json") == "" and OM.plain_name("mp_fp32_b1.json") == "mp_fp32_b1.json"
    try:
        OM.label_for("arcsrv", "requests")
    except ValueError:
        pass
    else:
        raise AssertionError("expected a refusal of an unknown client")


def test_a_reader_takes_the_lean_named_file_then_the_plain_file_of_the_old_campaign_and_never_another_clients():
    d = _dir()
    _put(d, "mp_qdrant_b1.json"); _put(d, "mp_fp32_native_b1.json")
    _put(d, "mp_arcsrv_b1.json", mark="old", **_STAMPS["lean"])               # a 26.11.1 file: plain name, lean stamp
    assert [os.path.basename(p) for p in OM.files(d, "mp_arcsrv_b*.json")] == ["mp_arcsrv_b1.json"]
    assert [os.path.basename(p) for p in OM.files(d, "mp_*_b*.json")] == ["mp_arcsrv_b1.json", "mp_fp32_native_b1.json", "mp_qdrant_b1.json"]
    assert OM.pick(d, "mp_arcsrv_b2.json") == os.path.join(str(d), "mp_arcsrv_b2.json")      # absent: the plain path, the caller tests it
    assert OM.files(d / "nowhere", "*.json") == []
    only_others = _dir()
    _put(only_others, "mp_arcsrv_clientofficial_b1.json", **_STAMPS["official"]); _put(only_others, "mp_arcsrv_clientpgwire_b1.json", **_STAMPS["pgwire"])
    assert OM.files(only_others, "mp_*_b*.json") == [] and not os.path.isfile(OM.pick(only_others, "mp_arcsrv_b1.json"))


def test_a_plain_file_beside_a_lean_named_one_follows_the_rule_of_the_merge():
    d = _dir()
    _put(d, "mp_arcsrv_clientlean_b1.json", mark="new", **_STAMPS["lean"])
    _put(d, "mp_arcsrv_b1.json", mark="old", **_STAMPS["official"])           # the overwritten file of the old campaign: it loses
    assert [os.path.basename(p) for p in OM.files(d, "mp_arcsrv_b*.json")] == ["mp_arcsrv_clientlean_b1.json"]
    _put(d, "mp_arcsrv_b1.json", mark="new", **_STAMPS["lean"])               # the same bytes: fine
    assert [os.path.basename(p) for p in OM.files(d, "mp_arcsrv_b*.json")] == ["mp_arcsrv_clientlean_b1.json"]
    _put(d, "mp_arcsrv_b1.json", mark="other", **_STAMPS["lean"])             # two lean files that differ: refused, as in the merge
    try:
        OM.files(d, "mp_arcsrv_b*.json")
    except SystemExit as e:
        assert "mp_arcsrv_b1.json" in str(e) and "mp_arcsrv_clientlean_b1.json" in str(e)
    else:
        raise AssertionError("expected a refusal")


def test_the_merge_puts_a_lean_named_file_in_the_place_of_a_plain_driver_file_and_leaves_the_other_clients_files_out():
    old, new, out = _dir(), _dir(), _dir() / "o"
    _put(old, "mp_arcsrv_b1.json", mark="old", **_STAMPS["official"]); _put(old, "mp_qdrant_b1.json")
    for c in ("lean", "official", "pgwire"):
        _put(new, f"mp_arcsrv_client{c}_b1.json", mark=c, **_STAMPS[c])
    for order in ((("old", old), ("new", new)), (("new", new), ("old", old))):
        out = _dir() / "o"
        OM.merge(list(order), out)
        assert sorted(p.name for p in out.glob("mp_*.json")) == ["mp_arcsrv_clientlean_b1.json", "mp_qdrant_b1.json"]
        man = (out / "MANIFEST.txt").read_text()
        assert "mp_arcsrv_clientlean_b1.json\tnew\tlean" in man and "replaced by new (lean)" in man
        assert "# not merged, named for another client: new/mp_arcsrv_clientofficial_b1.json" in man
        assert "# not merged, named for another client: new/mp_arcsrv_clientpgwire_b1.json" in man
    out = _dir() / "o"
    OM.merge([("new", new), ("old", old)], out, exclude_arms=("arcsrv",))     # the exclusion reads the arm, not the client
    assert sorted(p.name for p in out.glob("mp_*.json")) == ["mp_qdrant_b1.json"]


def test_the_exporter_reads_the_lean_file_and_checks_only_the_files_a_table_reads():
    import export_web as EW
    pin = "c0ffee62a"
    root = _dir()
    d = root / f"dense_mp5_small_{pin}"
    for c in ("lean", "official", "pgwire"):                                  # a new run: three files, one per client
        _put(d, f"mp_arcsrv_client{c}_b1.json", mark=c, **_STAMPS[c])
    got = [fp.name for _b, fps in EW._overlay_files_by_build(d, "mp_arcsrv", "_b*.json", "arcadedb_dense_server") for fp in fps]
    assert got == ["mp_arcsrv_clientlean_b1.json"]
    old = root / f"dense_mp5_{pin}"                                            # a 26.11.1 directory: the plain name, read as before
    _put(old, "mp_arcsrv_b1.json", mark="old", **_STAMPS["lean"])
    got = [fp.name for _b, fps in EW._overlay_files_by_build(old, "mp_arcsrv", "_b*.json", "arcadedb_dense_server") for fp in fps]
    assert got == ["mp_arcsrv_b1.json"]
    saved, saved_pin = EW.RESULTS, os.environ.get("BENCH_ENGINE_COMMIT")
    EW.RESULTS, os.environ["BENCH_ENGINE_COMMIT"] = root, pin
    try:
        EW._refuse_other_client_overlays()                                    # the driver-named file is read by no table: no refusal
        _put(old, "mp_arcsrv_b2.json", mark="lost", **_STAMPS["official"])    # the old campaign's overwritten file still refuses
        for bad in ("mp_arcsrv_b2.json", "mp_arcsrv_clientlean_b2.json"):     # and so does a lean-named file whose rows name the driver
            (old / "mp_arcsrv_b2.json").rename(old / bad)
            try:
                EW._refuse_other_client_overlays()
            except SystemExit as e:
                assert bad in str(e) and "1 overlay file(s)" in str(e)
            else:
                raise AssertionError(f"expected a refusal of {bad}")
            (old / bad).rename(old / "mp_arcsrv_b2.json")
    finally:
        EW.RESULTS = saved
        if saved_pin is None:
            os.environ.pop("BENCH_ENGINE_COMMIT", None)
        else:
            os.environ["BENCH_ENGINE_COMMIT"] = saved_pin
