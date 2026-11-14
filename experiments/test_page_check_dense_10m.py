"""page_check._check_dense_10m: the cross-check of the page's deep10m dense cells against the paper table (humemai/mmdbbench#68).

It owes the arms the landing holds (BENCH_MP_ARMS; the default landing still owes all eight labels) and reads a page of two builds, where the
in-process ArcadeDB entries carry their build and the paper table prints `[jvm]` and `[native]` rows. Light: synthetic payloads, the paper table
is a dict. Run with pytest, or as plain functions from this directory."""
import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_RES = tempfile.mkdtemp(prefix="pc-dense-")
Path(_RES, "runs.jsonl").write_text("")
Path(_RES, "e4decomp_abc123def").mkdir()      # export_web is pinned-only about the e4 directory when it is imported without the suite's fixture results
os.environ.setdefault("BENCH_RESULTS_DIR", _RES)
os.environ.setdefault("BENCH_ENGINE_COMMIT", "abc123def")
import claims_check as C  # noqa: E402
import make_paper_tables as M  # noqa: E402
import page_check as PC  # noqa: E402


def _isolated(fn):
    def run():
        saved = (M.RESULTS, C.cell, C.cell_text, PC._dense_cache_set_by_campaign, {k: os.environ.get(k) for k in ("BENCH_MP_ARMS", "BENCH_ENGINE_COMMIT")})
        try:
            fn()
        finally:
            M.RESULTS, C.cell, C.cell_text, PC._dense_cache_set_by_campaign = saved[:4]
            for k, v in saved[4].items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    run.__name__ = fn.__name__
    return run


METRIC = {"cold p50 ms": 4.25, "warm p50 ms": 1.55, "recall@10": 0.948}


def _entry(label, build=None, **m):
    metrics = {k: {"median": v, "n": 3} for k, v in dict(METRIC, **m).items()}
    return {"backend": label, "build": build, "scale": "deep10m", "metrics": metrics}


def _paper(*rows):
    t = {}
    for row in rows:
        for col, v in zip((1, 2, 4), (4.25, 1.55, 0.948)):
            t[(row, col)] = v
    C.cell = lambda table, row, col: t.get((row, col))
    C.cell_text = lambda table, row, col: {1: "4.25", 2: "1.55", 4: "0.948"}[col] if (row, col) in t else None
    PC._dense_cache_set_by_campaign = lambda: set()


def _run(entries, arms=None):
    M.RESULTS = _RES
    os.environ["BENCH_ENGINE_COMMIT"] = "abc123def"
    os.environ.pop("BENCH_MP_ARMS", None)
    if arms:
        os.environ["BENCH_MP_ARMS"] = arms
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        checked, bad = PC._check_dense_10m({"tables": [{"id": "l3d", "entries": entries, "conditions": []}]})
    return checked, bad, out.getvalue()


@_isolated
def test_a_landing_owes_only_the_arms_it_holds_and_reads_a_page_of_two_builds():
    _paper("ArcadeDB (emb, fp32) [jvm]", "ArcadeDB (emb, fp32) [native]", "Qdrant (fp32)")
    entries = [_entry("ArcadeDB (embedded, fp32, JVM build)", "jvm"), _entry("ArcadeDB (embedded, fp32, native build)", "native"), _entry("Qdrant (fp32)")]
    checked, bad, text = _run(entries, arms="fp32,qdrant")
    assert bad == 0 and checked >= 9, text            # three arms x three columns


@_isolated
def test_an_arm_the_landing_holds_and_the_page_lacks_is_still_absent():
    _paper("ArcadeDB (emb, fp32) [jvm]", "ArcadeDB (emb, fp32) [native]")
    entries = [_entry("ArcadeDB (embedded, fp32, JVM build)", "jvm"), _entry("ArcadeDB (embedded, fp32, native build)", "native")]
    checked, bad, text = _run(entries, arms="fp32,qdrant")
    assert bad == 1 and "ABSENT Qdrant (fp32)" in text, text


@_isolated
def test_a_value_that_differs_from_the_paper_table_is_still_a_difference():
    _paper("ArcadeDB (emb, fp32) [jvm]", "ArcadeDB (emb, fp32) [native]")
    entries = [_entry("ArcadeDB (embedded, fp32, JVM build)", "jvm", **{"cold p50 ms": 9.9}), _entry("ArcadeDB (embedded, fp32, native build)", "native")]
    checked, bad, text = _run(entries, arms="fp32")
    assert bad == 1 and "DIFFER ArcadeDB (embedded, fp32) [jvm]" in text, text


@_isolated
def test_the_default_landing_still_owes_all_eight_labels():
    _paper("Qdrant (fp32)")
    checked, bad, text = _run([_entry("Qdrant (fp32)")])
    assert bad == 7 and text.count("ABSENT") == 7, text
