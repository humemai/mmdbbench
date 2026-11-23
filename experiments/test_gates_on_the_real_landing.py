"""Three gates stopped the real landing of 26.12.1 for reasons that had nothing to do with the landing (humemai/mmdbbench#156).

A rehearsal of the landing (a scratch copy of the store, the small rows relabelled to a made-up release, the large rows left on 26.11.1) got past the pin split
(#148, #149, #153, #155) and then stopped at three gates, one after the other, because `refresh_web_page.py` stops at the first:

1. `large_entry_gate._identity` had the precision in the key of a large entry. The published payload carries no precision on the served native entry of the
   dense table (`None`) where the exporter writes `fp32`, so the gate read "the entry is gone" and refused every landing, the unmodified store at its own pin
   included, and its sentence pointed at the large pin, which was set. The identity is now (backend key, build, size id), the precision is pooled, a removed
   entry still refuses, and the sentence names the first identity field that differs (or says the entry is gone when nothing of that backend key is left).
2. `provenance_check` read the sparse rows with `_pinned_sparse_rows()`, which has no default build: with the rows of both builds at the pin it returned
   `None` and the script stopped with "pinned sparse rows incomplete". `make_paper_tables.sparse_table` reads them with `build="all"`; so does the check now.
3. `page_check._check_raw_backend_keys` read the host name of a URL (`www.mongodb.com`) and the lowercase `arcadedb` of the e4 sentence ("One engine build
   (arcadedb 26.12.1 ...)") as raw backend keys. A URL is no longer read and the sentence prints `ArcadeDB`; a real raw key still fires.

Plain functions with `unittest.mock`, temporary directories and synthetic payloads and rows. The exporter is imported, so numpy and pandas are needed, as
everywhere else."""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("BENCH_RESULTS_DIR", tempfile.mkdtemp(prefix="landing-gates-"))
os.environ.setdefault("BENCH_ONLY_LANES", "l1tpc")

OLD, NEW = "a3a5d1245", "0123abcde"      # the commit of 26.11.1 (the large rows), and a made-up commit for the 26.12.1 landing (the small rows)
KEYS = {"cold p50 ms": {}, "warm p50 ms": {}, "warm p99 ms": {}, "recall@10": {}}


def _refusal(fn, *args):
    try:
        fn(*args)
    except SystemExit as e:
        return str(e.code)
    raise AssertionError(f"{getattr(fn, '__name__', fn)} did not refuse")


# ------------------------------------------------------------------------------------------------ 1. the identity of a large entry
def _entry(key="arcadedb_dense_server", build="native", precision="fp32", label="ArcadeDB (server, fp32, native build)", scale="deep10m"):
    return {"backend": label, "backend_key": key, "build": build, "precision": precision, "scale": scale, "metrics": dict(KEYS)}


def _page(*entries, table="l3d"):
    return {"tables": [{"id": table, "entries": list(entries)}]}


def test_the_identity_is_the_backend_key_the_build_and_the_size_and_not_the_precision():
    import large_entry_gate as G
    assert G.IDENTITY_FIELDS == ("backend key", "build", "size id")
    assert G._identity(_entry(precision="fp32"), "deep10m") == ("arcadedb_dense_server", "native", "deep10m")
    assert G._identity(_entry(precision=None), "deep10m") == G._identity(_entry(precision="int8"), "deep10m")
    assert len(G._identity(_entry(), "deep10m")) == len(G.IDENTITY_FIELDS)


def test_a_precision_that_drifted_between_the_published_payload_and_the_rebuilt_one_is_not_a_lost_entry():
    import large_entry_gate as G
    for was in (None, ""):
        for table, scale in (("l3d", "deep10m"), ("l3s", "medium")):                 # the dense table and the sparse one, each at its large size
            published = _page(_entry(precision=was, scale=scale), table=table)
            rebuilt = _page(_entry(precision="fp32", scale=scale), table=table)
            assert len(G._large_entries(published, table)) == 1
            assert G.lost_large_keys(published, rebuilt, table, G.TABLE_KEYS[table]) == [], (was, table)
    assert G.refuse_lost_large_keys(_page(_entry(precision=None)), _page(_entry(precision="fp32"))) is None


def test_the_unmodified_store_at_its_own_pin_passes_with_the_one_drifted_precision_among_twelve_large_entries():
    import large_entry_gate as G
    keys = ["arcadedb_dense_embedded", "arcadedb_dense_server", "arangodb_dense", "duckdb_vss_dense", "ladybug_dense", "mongodb_dense",
            "pgvector_dense", "qdrant_dense", "redis_dense", "sqlite_vec_dense", "chroma_dense", "lancedb_dense"]
    builds = {"arcadedb_dense_embedded": "native", "arcadedb_dense_server": "native"}
    published = _page(*[_entry(key=k, build=builds.get(k), precision=None if k == "arcadedb_dense_server" else "fp32", label=k) for k in keys])
    rebuilt = _page(*[_entry(key=k, build=builds.get(k), precision="fp32", label=k) for k in keys])
    assert len(G._large_entries(published)) == 12
    assert G.refuse_lost_large_keys(published, rebuilt) is None


def test_a_removed_entry_still_refuses_and_says_it_is_gone_when_nothing_of_its_backend_key_is_left():
    import large_entry_gate as G
    published = _page(_entry(precision=None), _entry(key="qdrant_dense", build=None, label="Qdrant (fp32)"))
    rebuilt = _page(_entry(key="qdrant_dense", build=None, label="Qdrant (fp32)"))
    problems = G.lost_large_keys(published, rebuilt)
    assert problems == ["table 'l3d', entry 'ArcadeDB (server, fp32, native build)' at size 'deep10m': the entry is gone, it had "
                        "cold p50 ms, warm p50 ms, warm p99 ms, recall@10"], problems
    msg = _refusal(G.refuse_lost_large_keys, published, rebuilt)
    assert msg.startswith("REFUSING to write the payload: 1 large entry of the page lost metric keys") and "differs" not in msg
    assert msg.count("the entry is gone") == 1


def test_an_entry_that_lost_its_keys_under_a_drifted_precision_still_refuses_as_a_lost_key():
    import large_entry_gate as G
    published = _page(_entry(precision=None))
    rebuilt = _page(dict(_entry(precision="fp32"), metrics={"cold p50 ms": {}, "recall@10": {}}))
    assert G.lost_large_keys(published, rebuilt) == ["table 'l3d', entry 'ArcadeDB (server, fp32, native build)' at size 'deep10m': it lost warm p50 ms, warm p99 ms"]


def test_the_sentence_names_the_first_identity_field_that_differs():
    import large_entry_gate as G
    published = _page(_entry(build="native", precision=None))
    rebuilt = _page(_entry(build="jvm", precision="fp32"))
    problems = G.lost_large_keys(published, rebuilt)
    assert len(problems) == 1
    assert "its build differs (published 'native', rebuilt 'jvm')" in problems[0] and "precision" not in problems[0] and "the entry is gone" not in problems[0], problems
    assert problems[0].endswith(", it had cold p50 ms, warm p50 ms, warm p99 ms, recall@10")
    assert "its build differs" in _refusal(G.refuse_lost_large_keys, published, rebuilt)


def test_first_difference_reads_the_closest_identity_by_its_leading_fields():
    import large_entry_gate as G
    ident = ("arcadedb_dense_server", "native", "deep10m")
    assert G._first_difference(ident, {("qdrant_dense", "native", "deep10m")}) is None                       # no entry of that backend key: truly absent
    assert G._first_difference(ident, set()) is None
    assert G._first_difference(ident, {("arcadedb_dense_server", "jvm", "deep10m")}) == ("build", "native", "jvm")
    # two candidates of the same key: the one that agrees on the build is closer, so the field named is the size
    assert G._first_difference(ident, {("arcadedb_dense_server", "jvm", "deep10m"), ("arcadedb_dense_server", "native", "other")}) == ("size id", "deep10m", "other")


# ------------------------------------------------------------------------------------------------ 2. provenance_check reads both builds
ARM = "arcadedb_sparse_embedded"
TIERS = ("tiny", "small", "medium")      # extra, small, large


def _sparse_rows(builds=("jvm", "native"), reps=None):
    """Synthetic l3s rows of the arm: three reps per tier and build, `tiny` and `small` at the NEW pin and `medium` at the OLD one."""
    out = []
    for b in builds:
        for t in TIERS:
            pin = OLD if t == "medium" else NEW
            for rep in range(1, (reps or {}).get((b, t), 3) + 1):
                out.append({"lane": "l3s", "backend": ARM, "scale": t, "rep": rep, "engine_commit": pin, "engine_version": "26.11.1" if pin == OLD else "26.12.1",
                            "engine_backend": b, "query_p50_ms": 10.0 + rep, "query_p99_ms": 30.0, "recall_at_10": 0.95})
    return out


def _import_provenance_check(rows):
    """provenance_check imported afresh (it reads the sparse rows when it is imported) in the landing's environment, `rows` standing for the store.
    Returns the module, or the text of its SystemExit."""
    import make_paper_tables as M
    spec = importlib.util.spec_from_file_location("provenance_check_of_this_test", HERE / "provenance_check.py")
    mod = importlib.util.module_from_spec(spec)
    with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ), mock.patch.object(M, "RESULTS", d), mock.patch.object(M, "load_canonical", lambda: rows), \
            contextlib.redirect_stderr(io.StringIO()):
        for k in ("BENCH_MP_BUILDS", "BENCH_ENGINE_BACKEND"):
            os.environ.pop(k, None)
        os.environ.update({"BENCH_ENGINE_COMMIT": NEW, "BENCH_LARGE_ENGINE_COMMIT": OLD, "BENCH_RESULTS_DIR": d})
        try:
            spec.loader.exec_module(mod)
        except SystemExit as e:
            return str(e.code)
    return mod


def test_provenance_check_reads_the_rows_of_both_builds_of_the_sparse_arm_at_the_pin():
    import make_paper_tables as M
    rows = _sparse_rows()
    with mock.patch.dict(os.environ), mock.patch.object(M, "load_canonical", lambda: rows), contextlib.redirect_stderr(io.StringIO()):
        os.environ.update({"BENCH_ENGINE_COMMIT": NEW, "BENCH_LARGE_ENGINE_COMMIT": OLD})
        for k in ("BENCH_MP_BUILDS", "BENCH_ENGINE_BACKEND"):
            os.environ.pop(k, None)
        assert M._pinned_sparse_rows() is None                                       # the reader has no default build: the caller names one (the old call)
    mod = _import_provenance_check(rows)
    assert not isinstance(mod, str), mod
    assert {t: len(rs) for t, rs in mod._sparse.items()} == {"tiny": 6, "small": 6, "medium": 6}


def test_provenance_check_reads_one_build_and_no_rows_as_before():
    one = _import_provenance_check(_sparse_rows(builds=("native",)))
    assert not isinstance(one, str) and {t: len(rs) for t, rs in one._sparse.items()} == {"tiny": 3, "small": 3, "medium": 3}
    absent = _import_provenance_check([])
    assert not isinstance(absent, str) and absent._sparse == {}                      # the arm has not run at this pin: absent is not partial


def test_provenance_check_still_stops_on_a_build_that_is_short_of_its_reps():
    stop = _import_provenance_check(_sparse_rows(reps={("native", "small"): 2}))
    assert isinstance(stop, str) and "pinned sparse rows incomplete; T4 has no fallback" in stop


# ------------------------------------------------------------------------------------------------ 3. page_check and a URL, and the e4 sentence
def _check(payload):
    import page_check as PC
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        bad = PC._check_raw_backend_keys(payload)
    return bad, out.getvalue()


def _prose(text=None, why=None, label="MongoDB"):
    return {"conditions": [], "tables": [{"id": "l3s", "title": "Sparse", "conditions": [text] if text else [],
                                          "declared_absences": [{"backend": label, "column": None, "kind": "cannot express", "why": why or "fine."}],
                                          "entries": []}], "pending_tables": {}}


URL = "https://www.mongodb.com/docs/atlas/atlas-search/"


def test_a_url_is_not_read_as_a_raw_backend_key():
    assert _check(_prose(why=f"MongoDB has no sparse index type ({URL})."))[0] == 0                   # the declared absence of l3s
    assert _check(_prose(text=f"The documentation says so: {URL}"))[0] == 0                          # the same in a condition
    assert _check(_prose(text="See http://www.mongodb.com/docs and https://docs.example.org/arcadedb_graph_embedded/page for it."))[0] == 0
    assert _check(_prose(text=f"MongoDB ({URL}) and `mongodb` in code."))[0] == 0


def test_a_raw_key_beside_a_url_or_without_one_still_fires():
    bad, out = _check(_prose(why=f"mongodb has no sparse index type ({URL})."))
    assert bad == 1 and "RAW-KEY l3s.declared_absences" in out and "[mongodb]" in out, out
    bad, out = _check(_prose(text=f"See {URL} : the arm arcadedb_graph_embedded did not finish"))
    assert bad == 1 and "[arcadedb_graph_embedded]" in out, out
    assert _check(_prose(text="the arm arcadedb_graph_embedded did not finish"))[0] == 1
    assert _check(_prose(text="One engine build (arcadedb 26.12.1 · 0123abcde) in all three deployments."))[0] == 1      # the lowercase name is a key


def _e4_artifact(rep):
    meta = {"rows": 3000000, "engine_version": "26.12.1", "engine_commit": NEW, "reps": 15, "warmup": 3, "cpuset": "0-11", "mem_cap": "8g", "heap": "6g",
            "ts_utc": "2026-12-02T00:00:00+00:00", "host": "h", "row_count_agreement": "ok"}
    ms = {"embedded": 1.0, "inproc_http": 2.5, "docker_http": 3.0}
    return {"meta": meta, "results": {a: {s: {"p50_ms": m * (1 + 0.01 * rep)} for s in ("1", "100")} for a, m in ms.items()}}


def test_the_e4_sentence_names_the_engine_as_the_page_does_and_page_check_passes_it():
    import export_web as EW
    with tempfile.TemporaryDirectory() as d, mock.patch.object(EW, "E4_DIR", Path(d)), mock.patch.dict(os.environ):
        os.environ["BENCH_ENGINE_COMMIT"] = NEW
        for rep in (1, 2, 3):
            (Path(d) / f"decomp3m_stub_rep{rep}.json").write_text(json.dumps(_e4_artifact(rep)))
        table = EW._e4_table()
    sentence = next(c for c in table["conditions"] if "One engine build" in c)
    assert f"One engine build (ArcadeDB 26.12.1 · {NEW}) in all three deployments, 15 repetitions after 3 warmup" in sentence, sentence
    values = {v for rec in EW._GENERATED if rec["text"] == sentence for v in rec["values"]}
    assert f"ArcadeDB 26.12.1 · {NEW}" in values and all(v in sentence for v in values), values                 # the registered values are in the text
    assert table["entries"][0]["version_name"] == f"arcadedb 26.12.1 · {NEW}"                                   # the entry's own identity string is unchanged
    bad, out = _check({"conditions": [], "tables": [dict(table, declared_absences=[])], "pending_tables": {}})
    assert bad == 0, out
