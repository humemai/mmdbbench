"""The 2026-11 instrument runs exactly three repetitions per cell, and the checks and the publish fixture say exactly three (the owner,
2026-11-14: n=3 is the only plan, n=4 and n=5 are dropped; the last place that still allowed 3 to 5 is closed).

  * `provenance_check.caption_n` reports a published cell whose table rows rest on two, four or five repetitions as BAD, not only the short ones.
    It used to take 3 to 5 because the publish fixture held cells at N=4 and N=5.
  * The publish fixture (fixtures/publish_2611) holds no repetition above three: no row with `rep` 4 or 5, no `mp_*_b4/b5.json` build file of the dense
    overlays and no `rep4/rep5` file of the e4 decomposition. Its builder drops them, on a fresh build and on `--patch` of the committed rows alike.
  * PUBLISHING.md does not state a 3 to 5 range for the 2026-11 instrument.

Plain functions, no pytest fixture: run under pytest or as `python test_reps_exactly_three.py`.
"""
import contextlib
import gzip
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
import types
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
FIXTURE_DIR = HERE / "fixtures" / "publish_2611"
FIXTURE = FIXTURE_DIR / "results"

# provenance_check reads the pinned overlay rows when it is imported: point it at an empty results directory and a pin, for tests only
_RES = tempfile.mkdtemp(prefix="reps-exactly-three-")
Path(_RES, "runs.jsonl").write_text("")
os.environ.setdefault("BENCH_RESULTS_DIR", _RES)
os.environ.setdefault("BENCH_ENGINE_COMMIT", "abc123def")
import provenance_check as PC  # noqa: E402


def _fixture_rows():
    with gzip.open(FIXTURE / "runs.jsonl.gz", "rt") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    assert rows, "the publish fixture holds no rows"
    return rows


# ---- provenance_check.caption_n: the bound is exactly three

def _caption_n(ns_by_label):
    """(findings, printed text) of caption_n over a stand-in make_paper_tables whose first table prints one row per label, each rendered
    from an array of that many dicts (what the real tables hand mmm), so the audit sees exactly those counts."""
    M = types.ModuleType("make_paper_tables")
    M.mmm = lambda rs, *a, **kw: "1.0"
    M.mmm_rec = lambda rs, *a, **kw: "1.0"
    M.write = lambda name, body: None
    M.load_canonical = lambda: []

    def tabular_table(rows):
        M.write("t2.tex", "\n".join(f"{label} & " + M.mmm([{}] * n) for label, n in ns_by_label.items()))

    M.tabular_table = tabular_table
    for name in ("graph_table", "sparse_table", "dense_ts_table"):
        setattr(M, name, lambda rows=None: None)
    out = io.StringIO()
    with mock.patch.dict(sys.modules, {"make_paper_tables": M}), mock.patch.dict(os.environ), contextlib.redirect_stdout(out):
        os.environ.pop("BENCH_ONLY_LANES", None)
        bad = PC.caption_n()
    return bad, out.getvalue()


def test_a_cell_on_exactly_three_repetitions_is_clean():
    bad, out = _caption_n({"ArcadeDB embedded": 3})
    assert bad == 0 and "BAD" not in out, out


def test_a_cell_on_two_repetitions_is_a_shortfall():
    bad, out = _caption_n({"ArcadeDB embedded": 2})
    assert bad == 1 and "N=[2] BAD" in out, out


def test_a_cell_on_four_or_five_repetitions_is_bad_because_the_instrument_runs_three():
    for n in (4, 5):
        bad, out = _caption_n({"ArcadeDB embedded": n})
        assert bad == 1 and f"N=[{n}] BAD" in out, (n, out)


def test_one_row_beyond_three_among_clean_rows_is_the_only_finding():
    bad, out = _caption_n({"A": 3, "B": 4, "C": 3})
    assert bad == 1 and out.count("BAD") == 1 and "B" in out, out


# ---- the publish fixture holds three repetitions and no more

def test_the_fixture_rows_hold_no_repetition_above_three():
    reps = {int(r.get("rep") or 0) for r in _fixture_rows()}
    assert reps and max(reps) == 3, sorted(reps)


def test_the_fixture_overlays_hold_no_build_or_repetition_file_above_three():
    seen = [f for d in FIXTURE.iterdir() if d.is_dir() for f in d.iterdir()]
    assert seen, "the fixture holds no overlay file"
    above = [f.name for f in seen if (m := re.search(r"_b(\d+)\.json$|_rep(\d+)\.json$", f.name)) and int(m.group(1) or m.group(2)) > 3]
    assert not above, above
    # the builds the overlays do hold are all there: the three of every dense arm, the three reps of the decomposition
    assert any(f.name.endswith("_b3.json") for f in seen) and any(f.name.endswith("_rep3.json") for f in seen)


def _builder():
    """build_fixture.py as a module (it is a script in the fixture directory, not on the import path)."""
    spec = importlib.util.spec_from_file_location("build_fixture_n3", FIXTURE_DIR / "build_fixture.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_fixture_builder_patch_drops_what_is_above_three_and_reproduces_the_committed_fixture():
    B = _builder()
    assert B.MAX_REP == 3 and not getattr(B, "FULL_REP_LANES", None), "a lane takes more than the instrument's three repetitions"
    root = Path(tempfile.mkdtemp(prefix="fixture-n3-"))
    try:
        dest = root / "results"
        shutil.copytree(FIXTURE, dest)
        committed = _fixture_rows()
        # what an older fixture held: a rep 4 and a rep 5 row of the sparse lane, and the build and rep files above three
        extra = []
        for rep in (4, 5):
            src = next(r for r in committed if r["lane"] == "l3s" and r["rep"] == 3)
            extra.append(dict(src, rep=rep, run_id=f"{src.get('run_id', 'x')}_rep{rep}"))
        with gzip.GzipFile(dest / "runs.jsonl.gz", "wb", mtime=0) as fh:
            for r in committed + extra:
                fh.write((json.dumps(r, separators=(",", ":")) + "\n").encode())
        stray = []
        for d, name in ((dest / next(p.name for p in FIXTURE.glob("dense_mp5_2*")), "mp_fp32_b{}.json"),
                        (dest / next(p.name for p in FIXTURE.glob("e4decomp_*")), "decomp3m_x_rep{}.json")):
            for n in (4, 5):
                (d / name.format(n)).write_text("[]\n")
                stray.append(d / name.format(n))
        with mock.patch.object(B, "OUT", dest), contextlib.redirect_stdout(io.StringIO()):
            B.patch_existing()
        assert not [p for p in stray if p.exists()], [p.name for p in stray if p.exists()]
        with gzip.open(dest / "runs.jsonl.gz", "rt") as fh:
            patched = [json.loads(line) for line in fh if line.strip()]
        assert patched == committed, "--patch on the committed rows must be a no-op (the builder and the fixture agree)"
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---- the docs

def test_publishing_md_does_not_state_a_three_to_five_range_for_the_instrument():
    text = (HERE / "PUBLISHING.md").read_text(encoding="utf-8")
    assert "provenance_check" in text, "PUBLISHING.md lost its provenance_check row"
    stale = [l[:160] for l in text.splitlines() if re.search(r"\b3 to 5 repetitions|\b3-5 repetitions|three to five repetitions", l)]
    assert not stale, stale


if __name__ == "__main__":
    bad = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception as e:  # noqa: BLE001
                bad += 1
                print("FAIL", name, repr(e)[:400])
    raise SystemExit(1 if bad else 0)
