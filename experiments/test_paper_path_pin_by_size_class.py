"""The readers of the paper path take the pin of each size class, so a landing whose small rows are on a new release and whose large rows are on the old one
does not stop (humemai/mmdbbench#154).

On the landing of 26.12.1 the small rows carry the new pin and the large rows stay on 26.11.1 until the large sizes are rerun (PAGE-SPEC rule 3: one release per
size class). #146 and #151 fixed the overlays of the page (`size_classes.pin_of_size_class`). The landing also runs `make_paper_tables.py` and
`make_paper_figures.py` (`refresh_web_page.py` step 1), and three readers of that path still took `BENCH_ENGINE_COMMIT` for all sizes of the lane:

- `make_paper_tables._pinned_sparse_rows`, reached by `main()` through `sparse_table` and `_sparse_2681_rows`: it collected the `l3s` rows at one pin, so
  `medium` (large) had no rows, and refused with `pinned sparse rows incomplete at ['medium']` (and, once the pin is read per tier, it would still have refused
  on the one engine identity it demanded across the three tiers);
- `make_paper_figures._sparse_overlay_pass`: it read `sparse_mp_<pin>/sp_<arm>_<tier>.json` at one pin, so the medium figure found no file;
- `export_web._censored_cells`: it read the run log at the landing's pin and the comparator pins, so the timeouts of the large ArcadeDB cells at the old pin
  were dropped and the cell read as one nobody ran.

The rule is the one of #146 (`size_classes.pin_of_size_class`, no second one), through the tier's size class (`SIZE_CLASS[("l3s", tier)]`) and, for a row of
the run log, the row's (`size_classes.row_size_class`). A landing whose two classes are on one release sets nothing and nothing moves.

Plain functions with `unittest.mock`, temporary directories and synthetic rows, so they run under the suite or as
`python test_paper_path_pin_by_size_class.py [name-substring ...]` from this directory. `make_paper_figures` draws with matplotlib, which the suite's
environment does not have, so it is imported with a stub in its place for the one function under test (it draws nothing)."""
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

OLD, NEW = "a3a5d1245", "0123abcde"      # the commit of 26.11.1 (the large rows), and a made-up commit for the 26.12.1 landing (the small rows)
VER = {OLD: "26.11.1", NEW: "26.12.1"}
ARM = "arcadedb_sparse_embedded"
TIERS = ("tiny", "small", "medium")      # extra, small, large
VAR = "BENCH_LARGE_ENGINE_COMMIT"
FLAG = "land_stage.py --large-pin"


def _rows(builds=("jvm",), n=3, tiers=TIERS, large_pin=OLD, new_version=None):
    """Synthetic l3s rows of the arm: `n` reps per tier and build, `tiny` and `small` at the NEW pin and `medium` at `large_pin`, one engine identity per pin."""
    out = []
    for b in builds:
        for t in tiers:
            pin = large_pin if t == "medium" else NEW
            for rep in range(1, n + 1):
                out.append({"lane": "l3s", "backend": ARM, "scale": t, "rep": rep, "engine_commit": pin,
                            "engine_version": (new_version or VER[NEW]) if pin == NEW else VER.get(pin, VER[OLD]),
                            "engine_backend": b, "query_p50_ms": 10.0 + rep, "query_p99_ms": 30.0, "recall_at_10": 0.95})
    return out


@contextlib.contextmanager
def _env(large=OLD, landing=NEW):
    """The landing's environment: the pin of the run being landed, and the large pin when `large` is given. Everything it moves is put back."""
    with mock.patch.dict(os.environ):
        for k in ("BENCH_MP_BUILDS", "BENCH_ENGINE_BACKEND", VAR):
            os.environ.pop(k, None)
        if landing is None:
            os.environ.pop("BENCH_ENGINE_COMMIT", None)
        else:
            os.environ["BENCH_ENGINE_COMMIT"] = landing
        if large is not None:
            os.environ[VAR] = large
        yield


def _freeze(rows, large=OLD, build=None):
    """(result of _pinned_sparse_rows, stderr text) with load_canonical replaced by `rows`."""
    import make_paper_tables as M
    err = io.StringIO()
    with _env(large), mock.patch.object(M, "load_canonical", lambda: rows), contextlib.redirect_stderr(err):
        res = M._pinned_sparse_rows(ARM, build)
    return res, err.getvalue()


def _sparse_table(rows, large=OLD):
    """(the files `sparse_table` wrote, the text of its SystemExit or None): the table as `main()` builds it, with the freeze replaced by `rows`."""
    import make_paper_tables as M
    written, stop = {}, None
    with _env(large), mock.patch.object(M, "load_canonical", lambda: rows), mock.patch.object(M, "write", lambda name, body: written.update({name: body})), \
            contextlib.redirect_stderr(io.StringIO()):
        try:
            M.sparse_table([])
        except SystemExit as e:
            stop = str(e.code)
    return written, stop


# ------------------------------------------------------------------------------------------------ the freeze of the sparse table
def test_the_landing_state_freezes_each_tier_at_the_pin_of_its_class():
    res, err = _freeze(_rows())
    assert res is not None and err == "", err
    assert {t: len(res[t]) for t in TIERS} == {"tiny": 3, "small": 3, "medium": 3}
    assert {r["engine_commit"] for t in ("tiny", "small") for r in res[t]} == {NEW}
    assert {r["engine_commit"] for r in res["medium"]} == {OLD}


def test_the_landing_state_of_both_builds_freezes_with_one_identity_per_pin_and_build():
    both = _rows(builds=("jvm", "native"))
    res, err = _freeze(both, build="all")
    assert res is not None and err == "", err
    assert {t: len(res[t]) for t in TIERS} == {"tiny": 6, "small": 6, "medium": 6}
    only, err = _freeze(both, build="native")
    assert only is not None and {t: len(only[t]) for t in TIERS} == {"tiny": 3, "small": 3, "medium": 3}, err


def test_sparse_table_does_not_stop_at_the_landing_state_and_prints_all_three_tiers_of_the_arm():
    written, stop = _sparse_table(_rows(builds=("jvm", "native")))
    assert stop is None and list(written) == ["t4_sparse.tex"], (stop, list(written))
    body = written["t4_sparse.tex"]
    arc = [ln for ln in body.splitlines() if " & 100k & " in ln or " & 1M & " in ln or " & 8.84M & " in ln][:6]
    assert len(arc) == 6 and not any("-- & --" in ln for ln in arc), arc                       # two builds, three tiers, every one with numbers


def test_without_the_large_pin_the_freeze_refuses_and_the_refusal_names_the_variable_and_the_flag():
    res, err = _freeze(_rows(), large=None)
    assert res is None and "incomplete at ['medium']" in err, err                              # the existing refusal, its first words unchanged
    _written, stop = _sparse_table(_rows(), large=None)
    for text in (err, stop):
        assert VAR in text and FLAG in text and "medium has 0 of 3 rows at " + NEW in text, text


def test_a_large_class_with_no_rows_at_all_is_absent_and_rows_at_a_third_commit_refuse():
    """CHANGED by humemai/mmdbbench#157; the first half of the #155 test asserted a refusal that is wrong for the real landing. The rerun of 26.12.1 is the small
    sizes only and the store has no `l3s` row at the 26.11.1 commit, so `medium` has no row at either pin: a tier that was not run is a dash on the table, and
    refusing it stopped the landing for a tier nobody owes. A tier with SOME rows still refuses (the partial test below), and so does a tier whose rows are at
    another commit (the second half here), which is what a forgotten or wrong large pin looks like."""
    rows = _rows(tiers=("tiny", "small"))                                                      # the old pin's medium rows are not in the store
    res, err = _freeze(rows)
    assert res is not None and {t: len(res[t]) for t in res} == {"tiny": 3, "small": 3} and f"medium has no rows at {OLD}: absent" in err, (res, err)
    written, stop = _sparse_table(rows)
    assert stop is None and "t4_sparse.tex" in written, stop
    elsewhere = _rows(large_pin="ffffffff1")                                                   # medium rows at a third commit: not the large pin either
    res, err = _freeze(elsewhere)
    assert res is None and VAR in err, err


def test_a_partial_class_refuses_per_class_and_only_the_large_one_names_the_variable():
    res, err = _freeze([r for r in _rows() if not (r["scale"] == "medium" and r["rep"] == 3)])
    assert res is None and "incomplete at ['medium']: medium has 2 of 3 rows at " + OLD in err and VAR in err, err
    res, err = _freeze([r for r in _rows() if not (r["scale"] == "small" and r["rep"] == 3)])
    assert res is None and "incomplete at ['small']: small has 2 of 3 rows at " + NEW in err, err
    assert VAR not in err and FLAG not in err, err                                             # a small class is the landing's own: no large pin to name


def test_an_absent_arm_is_empty_and_so_is_a_staged_landing_that_holds_only_the_carried_large_rows():
    assert _freeze([])[0] == {}
    carried = [r for r in _rows() if r["scale"] == "medium"]                                   # the 26.11.1 rows are in the store, the new sparse stage has not run
    res, err = _freeze(carried)
    assert res == {} and err == "", (res, err)
    written, stop = _sparse_table(carried)
    assert stop is None and "t4_sparse.tex" in written, stop                                   # the page of an early stage is not refused for it


def test_one_release_for_both_classes_changes_nothing():
    one = [dict(r, engine_commit=NEW, engine_version=VER[NEW]) for r in _rows()]
    for large in (None, "", "   ", NEW, NEW + "0" * 31):            # the 40-character form of the same commit is the same pin
        res, err = _freeze(one, large=large)
        assert res is not None and err == "" and {t: len(res[t]) for t in TIERS} == {"tiny": 3, "small": 3, "medium": 3}, (large, err)
    res, _err = _freeze(one, large=None, build="all")
    assert res is not None
    written, stop = _sparse_table(one, large=None)
    assert stop is None and "t4_sparse.tex" in written
    short = [r for r in one if not (r["scale"] == "medium" and r["rep"] == 3)]
    res, err = _freeze(short, large=None)
    assert res is None and "incomplete at ['medium']" in err, err                              # an incomplete tier refuses at one pin too


def test_two_engine_identities_inside_one_pin_still_refuse():
    rows = [dict(r, engine_version="26.12.1.dev0") if (r["scale"] == "small" and r["rep"] == 1) else r for r in _rows()]
    res, err = _freeze(rows)
    assert res is None and "span" in err and "26.12.1.dev0" in err, err                         # tiny and small share the landing's pin: one identity
    one = [dict(r, engine_commit=NEW, engine_version=VER[NEW]) for r in _rows()]
    one[-1]["engine_version"] = "26.12.1.dev0"                                                  # one release for both classes: all three tiers are one group
    res, err = _freeze(one, large=None)
    assert res is None and "span" in err, err
    both = _rows(builds=("jvm", "native"))
    both = [dict(r, engine_version="26.12.1.dev0") if (r["engine_backend"] == "native" and r["scale"] == "tiny" and r["rep"] == 1) else r for r in both]
    res, err = _freeze(both, build="all")
    assert res is None and "native build are incomplete or span two identities" in err, err


def test_the_sparse_tier_pin_is_the_one_of_the_size_class_for_the_table_and_the_figure():
    import make_paper_tables as M
    import size_classes as SC
    with _env():
        assert [SC.SIZE_CLASS[("l3s", t)] for t in TIERS] == ["extra", "small", "large"]
        assert {t: M.sparse_tier_pin(t) for t in TIERS} == {"tiny": NEW, "small": NEW, "medium": OLD}
        assert {t: M.sparse_tier_pin(t) for t in TIERS} == {t: SC.pin_of_size_class(SC.SIZE_CLASS[("l3s", t)]) for t in TIERS}   # no second rule
        assert M.sparse_tier_pin("not-a-tier") == NEW
    with _env(large=None):
        assert {t: M.sparse_tier_pin(t) for t in TIERS} == {"tiny": NEW, "small": NEW, "medium": NEW}
    with _env(large="   "):
        assert M.sparse_tier_pin("medium") == NEW                                              # blank is unset


# ------------------------------------------------------------------------------------------------ the overlay files of the figure
def _passes(base):
    """One overlay file: pass 0 (cold) and five warm passes whose median is base + 3."""
    return [{"rep": i, "query_p50_ms": 99.0 if i == 0 else base + i} for i in range(6)]


@contextlib.contextmanager
def _overlays(old_dir=True, new_dir=True):
    """(make_paper_figures, scratch results dir) with the medium files in sparse_mp_<OLD> (values 40 to 45) and the small and tiny ones in sparse_mp_<NEW>
    (values 10 to 15). The figures are imported with matplotlib stubbed when it is not installed."""
    import make_paper_tables as M     # imported before sys.modules is patched, with the modules it loads (overlay_merge, publish_instrument), so the patch does not drop them
    if importlib.util.find_spec("matplotlib") is not None:
        stub = contextlib.nullcontext()                    # installed: the real one, and nothing of sys.modules is touched
    else:
        stub = mock.patch.dict(sys.modules, {n: mock.MagicMock() for n in ("matplotlib", "matplotlib.pyplot", "matplotlib.ticker")})
    with tempfile.TemporaryDirectory() as d, stub, mock.patch.object(M, "RESULTS", d):
        for pin, tiers, base, on in ((OLD, ("medium",), 40.0, old_dir), (NEW, ("small", "tiny"), 10.0, new_dir)):
            if not on:
                continue
            root = Path(d) / f"sparse_mp_{pin}"
            root.mkdir()
            for arm in ("arc_int8", "qdrant", "milvus", "elastic"):
                for t in tiers:
                    (root / f"sp_{arm}_{t}.json").write_text(json.dumps(_passes(base)))
        import make_paper_figures as F
        yield F, Path(d)


def test_the_figure_finds_the_medium_file_in_the_old_pins_directory_and_the_small_files_in_the_new_pins():
    with _overlays() as (F, _d), _env():
        got = {t: F._sparse_overlay_pass(t, "arc_int8", warm=True) for t in TIERS}
        assert got == {"tiny": 13.0, "small": 13.0, "medium": 43.0}, got                        # medium is the old directory's (40 + 3), the others the new one's
        assert F._sparse_overlay_pass("medium", "qdrant", warm=False) == 99.0                    # the cold pass of the same file
        for tok in ("qdrant", "milvus", "elastic"):
            assert F._sparse_overlay_pass("medium", tok, warm=True) == 43.0, tok


def test_the_figure_without_the_large_pin_reads_the_landings_directory_as_before():
    with _overlays(old_dir=False) as (F, _d), _env(large=None):
        got = {t: F._sparse_overlay_pass(t, "arc_int8", warm=True) for t in TIERS}
        assert got == {"tiny": 13.0, "small": 13.0, "medium": None}, got                         # no medium file at the landing's pin: absent, as for any missing file
    with _overlays(old_dir=False) as (F, d), _env(large=None):
        for t in ("medium",):
            for arm in ("arc_int8", "qdrant"):
                (d / f"sparse_mp_{NEW}" / f"sp_{arm}_{t}.json").write_text(json.dumps(_passes(70.0)))     # one release for both classes: one directory
        assert F._sparse_overlay_pass("medium", "arc_int8", warm=True) == 73.0


def test_the_figure_with_the_large_pin_but_no_old_directory_finds_nothing_and_never_falls_back_to_the_new_one():
    with _overlays(old_dir=False) as (F, _d), _env():
        assert F._sparse_overlay_pass("medium", "arc_int8", warm=True) is None
        assert F._sparse_overlay_pass("small", "arc_int8", warm=True) == 13.0


def test_the_figure_refuses_an_unset_landing_pin():
    with _overlays() as (F, _d), _env(landing=None, large=OLD):
        try:
            F._sparse_overlay_pass("small", "arc_int8", warm=True)
        except SystemExit as e:
            assert "BENCH_ENGINE_COMMIT is unset" in str(e.code)
            return
    raise AssertionError("an unset landing pin did not refuse")


# ------------------------------------------------------------------------------------------------ the censored cells of the exporter
def _log(tmp):
    """A run log: ArcadeDB timeouts at three cells. tpch10 is a large size and tpch1 a small one (size_classes.SIZE_CLASS)."""
    base = {"lane": "l1tpc", "backend": "arcadedb_embedded", "rep": 1, "error": "timeout_after_3600s", "rc": -1, "instrument": "2026-11"}
    rows = [dict(base, scale="tpch10", workload="olap", engine_commit=OLD),                  # a large cell of the carried 26.11.1 rows
            dict(base, scale="tpch1", workload="oltp", engine_commit=OLD),                   # a small cell of the old release: not the page's small cell
            dict(base, scale="tpch1", workload="olap", engine_commit=NEW),                   # a small cell of the landing
            dict(base, scale="tpch10", workload="oltp", engine_commit=NEW)]                  # a large cell at the landing's pin
    (tmp / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def _cells(large):
    """{(scale, workload)} of the censored cells the exporter reads at the landing NEW, with the large pin `large` (None: not named)."""
    import export_web as EW
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        _log(tmp)
        with _env(large), mock.patch.dict(os.environ, {"BENCH_RUNS_JSONL": "runs.jsonl"}), mock.patch.object(EW, "RESULTS", tmp), \
                mock.patch.object(EW, "_CENSORED_CACHE", None):
            os.environ.pop("BENCH_COMPARATOR_PIN", None)
            try:
                return {(k[1], k[3]) for k in EW._censored_cells()}
            finally:
                EW._CENSORED_CACHE = None


def test_the_censored_cells_of_a_large_size_are_read_at_the_pin_of_the_large_rows():
    got = _cells(OLD)
    assert ("tpch10", "olap") in got, got                                                      # the carried large cell keeps its note
    assert ("tpch1", "olap") in got, got                                                       # the small cell of the landing too
    assert ("tpch1", "oltp") not in got, got                                                   # an old-release timeout on a small size is not the page's cell
    assert ("tpch10", "oltp") not in got, got                                                  # a large cell has the pin of the large rows


def test_the_censored_cells_without_the_large_pin_are_the_landings_as_before():
    assert _cells(None) == {("tpch1", "olap"), ("tpch10", "oltp")}
    assert _cells(NEW) == {("tpch1", "olap"), ("tpch10", "oltp")}                              # the large pin named as the landing's own: one release


if __name__ == "__main__":
    names = [n for n in sorted(globals()) if n.startswith("test_") and (len(sys.argv) < 2 or any(a in n for a in sys.argv[1:]))]
    for n in names:
        globals()[n]()
        print("ok", n)
    print(len(names), "passed")
