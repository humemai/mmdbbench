"""What the rehearsal of the five other lanes of the 26.12.1 landing found (2026-11-27): humemai/mmdbbench#207 to #212.

  #207  the paper's graph table and time series block took one median over the native and the JVM build, so provenance_check counted 6 repetitions
  #208  the figures stopped a two-build landing ("name the build"), a sparse tier no comparator ran, and the deployment figure at a split landing
  #209  page_check refused a native cell the exporter had declared, where a table prints an arm under another name than its key's
  #210  the payload's engine list named the wheel of the served client as an engine
  #211  the SurrealDB lifecycle stage of the final small-size pass
  #212  page_check refused six state fields the time series lane records, which no table prints

`make_paper_figures` draws with matplotlib, which is stubbed when it is not installed; nothing here draws."""

import contextlib
import importlib.util
import io
import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

NEW, OLD = "c0ffee261", "a3a5d1245"


@contextlib.contextmanager
def _env(**values):
    """The landing's environment with only what the test names; everything is put back."""
    with mock.patch.dict(os.environ):
        for k in ("BENCH_ENGINE_COMMIT", "BENCH_LARGE_ENGINE_COMMIT", "BENCH_ENGINE_BACKEND", "BENCH_ONLY_LANES", "BENCH_MP_ARMS"):
            os.environ.pop(k, None)
        os.environ.update(values)
        yield


# ---------------------------------------------------------------------------------------------------- #207, the paper tables
def _rows(lane, backend, build, scale, value=1.0, **extra):
    """Three repetitions of one arm. `build` None is a comparator, or a row from before the field."""
    base = {"lane": lane, "backend": backend, "scale": scale, "workload": "oltp", "durability_class": "relaxed", **extra}
    if build:
        base["engine_backend"] = build
    fields = ("hop1_p50_ms", "hop1_p99_ms", "hop2_p99_ms", "peak_owned_mib_sum", "ingest_pts_per_s", "q_last_ms", "q_range_ms", "q_global_ms")
    return [{**base, "rep": i, **{f: value for f in fields}} for i in (1, 2, 3)]


def _written(table, rows, *patches):
    """(the table's text, the number of rows behind every cell) of one table function of make_paper_tables over `rows`."""
    import make_paper_tables as M
    got, counted, real = {}, [], M.mmm

    def counting(rs, *a, **kw):
        counted.append(len(rs))
        return real(rs, *a, **kw)

    with _env(), mock.patch.object(M, "write", lambda name, body: got.__setitem__(name, body)), mock.patch.object(M, "mmm", counting):
        with _all(patches):
            getattr(M, table)(rows)
    (body,) = got.values()
    return body, counted


@contextlib.contextmanager
def _all(patches):
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in reversed(patches):
            p.stop()


def _labels(body, needle):
    return [line.split(" & ")[0] for line in body.splitlines() if needle in line]


def test_the_graph_table_prints_one_row_per_build_each_on_its_own_three_repetitions():
    rows = (_rows("l2", "arcadedb_graph_embedded", "native", "sf1", 1.0) + _rows("l2", "arcadedb_graph_embedded", "jvm", "sf1", 2.0)
            + _rows("l2", "arcadedb_graph_server", "native", "sf1", 3.0) + _rows("l2", "arcadedb_graph_server", "jvm", "sf1", 4.0)
            + _rows("l2", "neo4j_graph", None, "sf1", 5.0))
    body, counted = _written("graph_table", rows)
    assert set(counted) == {3}, counted
    assert _labels(body, " & SF1 & ") == ["ArcadeDB (emb, native build)", "ArcadeDB (emb, JVM build)", "ArcadeDB (srv, native build)",
                                          "ArcadeDB (srv, JVM build)", "Neo4j"], body


def test_a_freeze_of_one_old_build_renders_the_graph_table_under_the_plain_names():
    rows = _rows("l2", "arcadedb_graph_embedded", None, "sf1") + _rows("l2", "arcadedb_graph_server", None, "sf1")
    body, counted = _written("graph_table", rows)
    assert set(counted) == {3} and _labels(body, " & SF1 & ") == ["ArcadeDB (emb)", "ArcadeDB (srv)"], body


def test_the_time_series_block_prints_one_row_per_build(tmp_path):
    import make_paper_tables as M
    rows = []
    for backend in ("arcadedb_ts_native", "arcadedb_ts_native_server", "arcadedb_ts_doc", "arcadedb_ts_doc_server"):
        rows += _rows("l4", backend, "native", "ts100", 1.0) + _rows("l4", backend, "jvm", "ts100", 2.0)
    rows += _rows("l4", "duckdb", None, "ts100", 3.0)
    body, counted = _written("dense_ts_table", rows,
                             mock.patch.object(M, "_dense_multipass", lambda: []),
                             mock.patch.object(M, "dense_mp_dir", lambda: str(tmp_path / "absent")),
                             mock.patch.object(M, "load_canonical", lambda: rows))
    assert set(counted) == {3}, counted
    got = [x for x in _labels(body, " & ") if x.startswith("ArcadeDB")]
    assert got == [f"ArcadeDB ({arm}, {build})" for arm in ("native TS", "srv, native TS", "document path", "srv, document path")
                   for build in ("native build", "JVM build")], body


# ---------------------------------------------------------------------------------------------------- #208, the figures
@contextlib.contextmanager
def _figures(**env):
    """make_paper_figures, with matplotlib stubbed when it is not installed, in the environment `env`."""
    import make_paper_tables  # noqa: F401  loaded before sys.modules is patched, so the patch does not drop it
    import claims_check  # noqa: F401
    if importlib.util.find_spec("matplotlib") is not None:
        stub = contextlib.nullcontext()
    else:
        stub = mock.patch.dict(sys.modules, {n: mock.MagicMock() for n in ("matplotlib", "matplotlib.pyplot", "matplotlib.ticker")})
    with stub, _env(**env):
        import make_paper_figures as F
        yield F


def _arc(build, backend="arcadedb_sparse_embedded", **extra):
    return {"lane": "l3s", "backend": backend, "engine_backend": build, **extra}


def test_the_figures_draw_the_jvm_build_when_both_have_rows_and_the_build_that_is_there_otherwise():
    comparator = {"lane": "l3s", "backend": "qdrant_sparse"}
    with _figures() as F:
        assert F.figure_build([_arc("native"), _arc("jvm"), comparator]) == "jvm"
        assert F.figure_build([_arc("native"), comparator]) == "native"
        assert F.figure_build([comparator]) is None
    with _figures(BENCH_ENGINE_BACKEND="native") as F:
        assert F.figure_build([_arc("native"), _arc("jvm")]) == "native"


def test_every_figure_row_and_the_sparse_rows_of_the_figures_come_from_one_build():
    import make_paper_tables as M
    rows = [_arc("native"), _arc("jvm"), {"lane": "l3s", "backend": "qdrant_sparse"}]
    asked = []
    with _figures() as F, mock.patch.object(M, "load_canonical", lambda: rows), mock.patch.object(
            M, "_sparse_2681_rows", lambda arm="arcadedb_sparse_embedded", build=None: asked.append(build) or {}):
        assert F.canonical() == [rows[1], rows[2]]
        F._sparse_rows_identity()
        assert F._sparse_overlay_p50("small") is None
    assert asked == ["jvm", "jvm"], asked


def test_the_figure_check_reads_the_table_row_of_the_figures_build_before_the_plain_name():
    import make_paper_tables as M
    with _figures() as F, mock.patch.object(M, "load_canonical", lambda: [_arc("native"), _arc("jvm")]):
        assert F._table_rows_of("t3_graph.tex", "ArcadeDB (emb) & SF10") == ["ArcadeDB (emb, JVM build) & SF10", "ArcadeDB (emb) & SF10"]
        assert F._table_rows_of("sparse", "ArcadeDB (emb, int8)")[0] == "ArcadeDB (emb, int8, JVM build)"
        assert F._table_rows_of("t5_dense_ts.tex", "ArcadeDB (emb, fp32)")[1] == "ArcadeDB (emb, fp32) [jvm]"


def _f4(F, comparator_rows, capsys):
    """Run f4 over one documents row with a comparator, ArcadeDB's small sparse rows, and `comparator_rows`; plotting is mocked."""
    docs = [{"lane": "l1tpc", "scale": "tpch1", "workload": "oltp", "backend": b, "neworder_p50_ms": v}
            for b, v in (("arcadedb_embedded", 1.0), ("postgres", 2.0))]
    ts = [{"lane": "l4", "scale": "ts100", "backend": "arcadedb_ts_native", "q_global_ms": 1.0, "q_last_ms": 1.0, "ingest_pts_per_s": 5.0}]
    ours = [{"lane": "l3s", "scale": "small", "workload": "search", "backend": "arcadedb_sparse_embedded", "query_p50_ms": 1.0,
             "recall_at_10": 0.99}]
    plt = mock.MagicMock()
    fig = mock.MagicMock()
    fig.get_figheight.return_value = 4.0
    plt.subplots.return_value = (fig, (mock.MagicMock(), mock.MagicMock()))
    rows = docs + comparator_rows
    with mock.patch.object(F, "plt", plt), mock.patch.object(F, "gs_crop", lambda *a, **k: None), mock.patch.object(
            F, "canonical", lambda: rows + ts), mock.patch.object(F, "_arc_sparse_rows", lambda: {"small": ours}), mock.patch.object(
            F, "_sparse_overlay_pass", lambda *a, **k: None), mock.patch.object(F, "_dense_overlay_recall", lambda *a, **k: None):
        F.f4_one_vs_n(rows)
    return capsys.readouterr().out


def test_a_figure_row_no_comparator_ran_is_left_out_out_loud(capsys):
    with _figures() as F:
        out = _f4(F, [], capsys)
    for label in ("Sparse 1M p50", "TS 12h agg p50", "TS ingest"):
        assert f"f4 {label}: SKIPPED, no comparator has a value for it at this release" in out, out
    assert "TPC-C new-order p50=postgres" in out, out


def test_a_figure_row_whose_comparators_ran_and_miss_the_recall_bar_is_still_refused(capsys):
    worse = [{"lane": "l3s", "scale": "small", "workload": "search", "backend": "qdrant_sparse", "query_p50_ms": 0.5, "recall_at_10": 0.5}]
    with _figures() as F, pytest.raises(SystemExit, match="f4 Sparse 1M p50: no first-pass value or no eligible comparator"):
        _f4(F, worse, capsys)


def _deployment_rows():
    """Embedded and served pairs: TPC-H at the small size on NEW, the large graph on OLD."""
    out = []
    for lane, scale, wl, field, backends, commit in (
            ("l1tpc", "tpch1", "olap", "q1_ms", ("arcadedb_embedded", "arcadedb_server"), NEW),
            ("l2", "sf10", "oltp", "hop1_p50_ms", ("arcadedb_graph_embedded", "arcadedb_graph_server"), OLD)):
        out += [{"lane": lane, "scale": scale, "workload": wl, "backend": b, field: 1.0, "engine_commit": commit} for b in backends]
    return out


def test_the_deployment_figure_is_left_out_when_the_two_sizes_are_on_two_releases(capsys):
    with _figures(BENCH_ENGINE_COMMIT=NEW, BENCH_LARGE_ENGINE_COMMIT=OLD) as F, mock.patch.object(
            F, "_arc_sparse_rows", lambda: {}), mock.patch.object(F, "_dense_overlay_p50", lambda *a, **k: None):
        assert F.f8_deployment(_deployment_rows()) is None
    assert "figure omitted: f8_deployment" in capsys.readouterr().out


def test_the_deployment_figure_still_refuses_two_releases_no_large_pin_explains():
    with _figures(BENCH_ENGINE_COMMIT=NEW) as F, mock.patch.object(F, "_arc_sparse_rows", lambda: {}), mock.patch.object(
            F, "_dense_overlay_p50", lambda *a, **k: None), pytest.raises(SystemExit, match="f8 bars span more than one release"):
        F.f8_deployment(_deployment_rows())


# ---------------------------------------------------------------------------------------------------- #209, page_check's roster
TS_ARMS = {"arcadedb_ts_doc": "ArcadeDB (embedded, document path)", "arcadedb_ts_doc_server": "ArcadeDB (server, document path)",
           "arcadedb_ts_native": "ArcadeDB (embedded, native time series)",
           "arcadedb_ts_native_server": "ArcadeDB (server, native time series)"}
SIZE = "2.59M points"                        # as a finished payload holds it: the corpus, and the label with its size class in front


def _ts_table(declared):
    entries = [{"backend": label.replace(")", ", JVM build)"), "backend_key": key, "build": "jvm", "scale": SIZE, "size_corpus": SIZE,
                "scale_label": f"Small: {SIZE}", "is_arcadedb": True} for key, label in TS_ARMS.items()]
    absences = [{"backend": label.replace(")", ", native build)"), "column": None, "kind": "not measured",
                 "why": f"{label.replace(')', ', native build)')} was not measured at {size}."} for label, size in declared]
    return {"id": "l4", "entries": entries, "declared_absences": absences}


def _roster_output(table):
    import page_check as PC
    out = io.StringIO()
    with mock.patch.object(PC, "_lane_has_rows", lambda *a, **k: False), contextlib.redirect_stdout(out):
        PC._check_lane_roster({"tables": [table]})
    return [line for line in out.getvalue().splitlines() if "native build)" in line]


def test_a_missing_native_row_declared_under_the_printed_label_is_accepted():
    lines = _roster_output(_ts_table([(label, SIZE) for label in TS_ARMS.values()]))
    assert not [x for x in lines if "MISSING" in x], lines
    assert len([x for x in lines if "absence declared" in x]) == 4, lines


def test_a_missing_native_row_with_no_declaration_or_one_for_another_size_still_fails():
    labels = list(TS_ARMS.values())
    lines = _roster_output(_ts_table([(label, SIZE) for label in labels[1:]]))
    assert [x for x in lines if "MISSING" in x and "arcadedb_ts_doc]" in x], lines
    lines = _roster_output(_ts_table([(labels[0], "documents, TPC-H SF1")] + [(label, SIZE) for label in labels[1:]]))
    assert [x for x in lines if "MISSING" in x and "arcadedb_ts_doc]" in x], lines


# ---------------------------------------------------------------------------------------------------- #212, the time series lane's own fields
def test_every_field_the_time_series_lane_records_about_its_state_is_declared_not_printed():
    import page_check as PC
    for field in ("ingest_body_mb", "ingest_post_s", "ingest_serialize_s", "ts_compaction_wait_s", "ts_mutable_at_query",
                  "ts_shard_count_effective"):
        assert PC._not_printed_reason(field), field
    assert not PC._not_printed_reason("q_global_ms")


# ---------------------------------------------------------------------------------------------------- #210, one served engine
BANNER = f"server:26.12.1 (build {NEW}{'0' * 31}/1793826579842/main)"


def test_the_exporter_reads_the_server_of_a_served_row_before_the_wheel_of_its_client():
    import export_web as EW
    served = {"backend": "arcadedb_ts_doc_server", "engine_version": "26.10.2", "backend_version": BANNER}
    assert EW._row_engine_string(served) == BANNER
    embedded = {"backend": "arcadedb_ts_doc", "engine_version": "26.12.1", "backend_version": "arcadedb 26.12.1"}
    assert EW._row_engine_string(embedded) == "26.12.1"
    other = {"backend": "surrealdb_ts_server", "engine_version": "surrealdb-server:3.2.6", "backend_version": "server:9.9"}
    assert EW._row_engine_string(other) == "surrealdb-server:3.2.6"
    unknown = {"backend": "arcadedb_ts_doc_server", "engine_version": "26.12.1", "backend_version": "server:unknown"}
    assert EW._row_engine_string(unknown) == "26.12.1"


def test_a_new_served_time_series_row_records_the_server_and_files_the_wheel():
    import l4_tsbs
    out = {"engine_version": "26.10.2", "backend_version": BANNER}
    l4_tsbs.stamp_served_engine(out, "arcadedb_ts_native_server")
    assert out["engine_version"] == BANNER and out["wheel_version"] == "26.10.2"
    for backend, banner in (("arcadedb_ts_native", "arcadedb 26.12.1"), ("arcadedb_ts_doc_server", "server:unknown"), ("duckdb", "server:1.0")):
        row = {"engine_version": "26.12.1", "backend_version": banner}
        l4_tsbs.stamp_served_engine(row, backend)
        assert row == {"engine_version": "26.12.1", "backend_version": banner}, backend


@pytest.mark.parametrize("listed,found", [(["arcadedb 26.12.1 · c0ffee261"], 0),
                                          (["arcadedb 26.10.2 · c0ffee261", "arcadedb 26.12.1 · c0ffee261"], 1)])
def test_the_version_gate_fails_an_engine_list_that_names_a_release_no_table_prints(tmp_path, listed, found):
    import version_consistency_check as V
    entry = {"backend": "ArcadeDB (server)", "version_name": "arcadedb 26.12.1 · c0ffee261", "metrics": {"x": 1}, "size_class": "small"}
    payload = tmp_path / "payload.json"
    payload.write_text(json.dumps({"arcadedb_engines": listed, "tables": [{"id": "l4", "entries": [entry]}]}))
    failures = V.check(str(payload))
    assert len([f for f in failures if "engine list" in f]) == found, failures


# ---------------------------------------------------------------------------------------------------- #211, the SurrealDB lifecycle stage
def test_the_surrealdb_lifecycle_cells_of_the_final_pass_are_one_stage_at_the_small_sizes():
    import make_2611_stages as G
    (spec,) = G.subset_specs(["surrealdb"], ["lifecycle"], tiers=True, sizes="small")
    assert spec[2] == "lifecycle" and spec[8] == ["surrealdb_lifecycle"], spec
    assert spec[4] == ["lc10k", "lc100k", "lc1m"] and len(spec[3]) == 8, spec


def test_the_generator_accepts_the_documented_surrealdb_lifecycle_call():
    from test_stage_generator_2611 import run
    r = run(["--profile", "final-small", "--engines", "surrealdb", "--lanes", "lifecycle", "--sizes", "small", "--after", "none",
             "--status-file", "none", "--id-prefix", "qSL", "--check"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "lifecycle lc10k,lc100k,lc1m" in r.stdout and "1 stages x passes = 3 runs" in r.stdout, r.stdout
