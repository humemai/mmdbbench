"""The arms a dense overlay must hold are a landing parameter too (humemai/mmdbbench#27, second part).

#27 made the build count a parameter. The n=3 campaign did not run every one of the 13 required arms (no int8 or chroma, lancedb,
milvus at all) and it ran two the lists do not know (ladybug, redis), so a complete n=3 overlay was still refused with "33 of 39
files missing". `BENCH_MP_ARMS` (land_stage `--mp-arms`) names the arms this landing holds; unset keeps the 13 and every refusal."""
import os
import tempfile

import make_paper_tables as M

PIN = "abc123456"
_VARS = ("BENCH_MP_ARMS", "BENCH_MP_BUILDS", "BENCH_ENGINE_COMMIT")


def _isolated(fn):
    """The module-level state these tests move (the resolver's results directory, the pin and the arm and build variables) is put back after
    each test: pytest runs the whole suite in one process, and test_vendor_memory reaches dense_mp_dir() through fairness_check."""
    def run():
        saved = (M.RESULTS, {k: os.environ.get(k) for k in _VARS})
        try:
            fn()
        finally:
            M.RESULTS = saved[0]
            for k, v in saved[1].items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    run.__name__ = fn.__name__
    run.__doc__ = fn.__doc__
    return run


def _tree(arms, builds=3, missing=()):
    d = tempfile.mkdtemp(prefix="mp_arms_")
    ov = os.path.join(d, f"dense_mp5_{PIN}")
    os.makedirs(ov)
    for a in arms:
        for b in range(1, builds + 1):
            if (a, b) not in missing:
                open(os.path.join(ov, f"mp_{a}_b{b}.json"), "w").write("{}")
    return d, ov


def _env(**kw):
    for k in ("BENCH_MP_ARMS", "BENCH_MP_BUILDS"):
        os.environ.pop(k, None)
    os.environ["BENCH_ENGINE_COMMIT"] = PIN
    os.environ.update({k: v for k, v in kw.items()})


def _refuses(fn, *needles):
    try:
        fn()
    except SystemExit as e:
        msg = str(e)
        assert all(n in msg for n in needles), msg
        return
    raise AssertionError("expected a refusal")


@_isolated
def test_a_landing_that_names_its_arms_passes_with_exactly_those_arms():
    d, ov = _tree(("fp32", "arcsrv", "duckvss", "qdrant", "ladybug", "redis"))
    M.RESULTS = d
    _env()
    _refuses(M.dense_mp_dir, "files missing")                       # the default 13 arms: refused, as before
    _env(BENCH_MP_ARMS="fp32,arcsrv,duckvss,qdrant,ladybug,redis")
    assert M.dense_mp_dir() == ov
    assert M.mp_arms_present(small=False) == ("fp32", "arcsrv", "duckvss", "qdrant", "ladybug", "redis")


@_isolated
def test_a_named_arm_with_fewer_builds_than_the_landing_holds_still_refuses():
    d, _ = _tree(("fp32", "arcsrv"), missing={("arcsrv", 3)})
    M.RESULTS = d
    _env(BENCH_MP_ARMS="fp32,arcsrv")
    _refuses(M.dense_mp_dir, "mp_arcsrv_b3.json", "1 of 6 files missing")


@_isolated
def test_the_one_megabyte_overlay_reads_the_same_list():
    d, _ = _tree(("fp32", "arcsrv"))
    os.rename(os.path.join(d, f"dense_mp5_{PIN}"), os.path.join(d, f"dense_mp5_small_{PIN}"))
    M.RESULTS = d
    _env()
    _refuses(M.dense_mp_small_dir, "files missing")
    _env(BENCH_MP_ARMS="fp32,arcsrv")
    assert M.dense_mp_small_dir().endswith(f"dense_mp5_small_{PIN}")


@_isolated
def test_the_native_twin_check_follows_the_named_arms():
    d, ov = _tree(("fp32", "arcsrv"))
    for b in (1, 2, 3):
        open(os.path.join(ov, f"mp_fp32_native_b{b}.json"), "w").write("{}")
    M.RESULTS = d
    _env()
    _refuses(lambda: M._refuse_partial_native(ov, "x"), "partial", "int8")    # default list: int8 has a JVM twin to be complete
    _env(BENCH_MP_ARMS="fp32,arcsrv")
    M._refuse_partial_native(ov, "x")                                         # int8 is not part of this landing
    os.remove(os.path.join(ov, "mp_fp32_native_b3.json"))
    _refuses(lambda: M._refuse_partial_native(ov, "x"), "partial", "fp32")    # a half-built native arm of the landing still refuses


@_isolated
def test_a_malformed_list_refuses_and_names_the_variable():
    _env(BENCH_MP_ARMS="fp32,arcsrv,fp32")
    _refuses(lambda: M.mp_required(M.MP_ARMS), "BENCH_MP_ARMS", "fp32 named twice")
    _env(BENCH_MP_ARMS="fp32,,arcsrv")
    _refuses(lambda: M.mp_required(M.MP_ARMS), "BENCH_MP_ARMS", "no blanks")
    _env(BENCH_MP_ARMS="fp32 arcsrv")
    _refuses(lambda: M.mp_required(M.MP_ARMS), "BENCH_MP_ARMS")
    _env()
    assert M.mp_required(M.MP_ARMS) is M.MP_ARMS


@_isolated
def test_land_stage_carries_the_flag_to_the_variable():
    import land_stage as L
    _env()
    L.apply_mp_arms("")
    assert "BENCH_MP_ARMS" not in os.environ
    L.apply_mp_arms("fp32, arcsrv")
    assert os.environ["BENCH_MP_ARMS"] == "fp32,arcsrv"
    _env()
