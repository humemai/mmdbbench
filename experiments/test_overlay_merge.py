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
    try:
        OM.merge([("lean-rerun", b), ("live", a)], _dir() / "o2")
    except SystemExit as e:
        assert "mp_arcsrv_b1.json" in str(e)
    else:
        raise AssertionError("a driver file must not replace a lean file")


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
