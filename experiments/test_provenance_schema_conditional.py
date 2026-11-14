"""provenance_check.check_schema_homogeneity on the three kinds of field a rep may lack without having measured something else
(humemai/mmdbbench#57, the n=3 landing of the dense lane).

1. Per-phase probes (`io_idle_*`, `io_queries_*`, `proc_*`, `jvm_*` of the idle and queries phases) that a cell's first rep predates. No table
   reads them; the check already ignores diagnostics and `io_stat_dedup` as instrumentation history.
2. `matched_rNNN_*`, the operating point where the sweep's recall first reaches NNN/100: absent by definition when the row's own
   `beam_max_recall_at_10` stays below it. A row that reached the threshold and lacks the field is still a split.
3. `nprobeN_*`: the name carries the nprobe the calibration chose, which differs between reps; the stem is the field.

Light: pure Python, no files. Run with pytest, or as plain functions from this directory."""
import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_RES = tempfile.mkdtemp(prefix="schema-conditional-")
Path(_RES, "runs.jsonl").write_text("")
os.environ.setdefault("BENCH_RESULTS_DIR", _RES)
os.environ.setdefault("BENCH_ENGINE_COMMIT", "abc123def")
import provenance_check as PC  # noqa: E402


def _row(rep, **kw):
    r = {"lane": "l3d", "scale": "deep10m", "workload": "search", "backend": "pgvector_dense", "rep": rep, "rc": 0,
         "ts_utc": f"2026-11-0{rep}T00:00:00Z", "build_s": 1000.0 + rep, "recall_at_10": 0.95, "beam_max_recall_at_10": 0.985}
    r.update(kw)
    return r


def _check(rows):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        bad = PC.check_schema_homogeneity(rows)
    return bad, out.getvalue()


def test_a_first_rep_that_predates_the_phase_probes_is_not_a_split():
    rows = [_row(1), _row(2, io_idle_read_mib=1.0, io_queries_write_mib=2.0, proc_idle_rss_mib=3.0, jvm_idle_committed_mib=4.0),
            _row(3, io_idle_read_mib=1.5, io_queries_write_mib=2.5, proc_idle_rss_mib=3.5, jvm_idle_committed_mib=4.5)]
    assert _check(rows)[0] == 0


def test_a_matched_point_the_sweep_could_not_reach_is_not_a_split():
    rows = [_row(1, beam_max_recall_at_10=0.9889),
            _row(2, beam_max_recall_at_10=0.9931, matched_r099_beam=400, matched_r099_p50_ms=3.1, matched_r099_recall_at_10=0.9931),
            _row(3, beam_max_recall_at_10=0.9893)]
    assert _check(rows)[0] == 0


def test_a_matched_point_that_was_reached_and_not_recorded_is_still_a_split():
    rows = [_row(1, beam_max_recall_at_10=0.9931),
            _row(2, beam_max_recall_at_10=0.9931, matched_r099_beam=400, matched_r099_p50_ms=3.1, matched_r099_recall_at_10=0.9931),
            _row(3, beam_max_recall_at_10=0.9893)]
    bad, text = _check(rows)
    assert bad == 1 and "matched_r099" in text


def test_a_row_with_no_sweep_figure_cannot_explain_a_missing_matched_point():
    rows = [_row(1, beam_max_recall_at_10=None),
            _row(2, matched_r099_beam=400, matched_r099_p50_ms=3.1, matched_r099_recall_at_10=0.9931), _row(3)]
    assert _check(rows)[0] == 1


def test_the_nprobe_a_calibration_chose_is_compared_by_its_stem():
    rows = [_row(1, nprobe152_query_p50_ms=2.0, nprobe152_recall_at_10=0.95),
            _row(2, nprobe188_query_p50_ms=2.1, nprobe188_recall_at_10=0.96),
            _row(3, nprobe188_query_p50_ms=2.2, nprobe188_recall_at_10=0.96)]
    assert _check(rows)[0] == 0


def test_a_field_one_rep_lacks_without_any_of_these_reasons_is_still_a_split():
    rows = [_row(1), _row(2, query_p50_ms=3.0), _row(3, query_p50_ms=3.1)]
    bad, text = _check(rows)
    assert bad == 1 and "query_p50_ms" in text
