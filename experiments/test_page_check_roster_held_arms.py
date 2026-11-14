"""page_check._roster_arms for the dense lane owes the arms the landing holds, not the constant list of the n=5 plan (humemai/mmdbbench#70).

Light: no files but an empty pinned results directory. Run with pytest, or as plain functions from this directory."""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_RES = tempfile.mkdtemp(prefix="pc-roster-")
Path(_RES, "runs.jsonl").write_text("")
Path(_RES, "e4decomp_abc123def").mkdir()
os.environ.setdefault("BENCH_RESULTS_DIR", _RES)
os.environ.setdefault("BENCH_ENGINE_COMMIT", "abc123def")
import make_paper_tables as M  # noqa: E402
import page_check as PC  # noqa: E402
import runner as RN  # noqa: E402


def _owed(arms=None):
    saved = (M.RESULTS, os.environ.get("BENCH_MP_ARMS"), os.environ.get("BENCH_ENGINE_COMMIT"))
    try:
        M.RESULTS = _RES
        os.environ["BENCH_ENGINE_COMMIT"] = "abc123def"
        os.environ.pop("BENCH_MP_ARMS", None)
        if arms:
            os.environ["BENCH_MP_ARMS"] = arms
        return PC._roster_arms("l3d", RN, {"entries": []})[1]
    finally:
        M.RESULTS = saved[0]
        for k, v in zip(("BENCH_MP_ARMS", "BENCH_ENGINE_COMMIT"), saved[1:]):
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def test_a_landing_that_holds_three_arms_owes_those_and_not_the_int8_siblings():
    owed = _owed("fp32,qdrant,duckvss")
    assert {"arcadedb_dense_embedded", "qdrant_dense", "duckdb_vss_dense"} <= owed
    assert not owed & {"qdrant_dense_int8", "arcadedb_dense_server_int8", "sqlite_vec_dense_int8", "arcadedb_dense_server"}, sorted(owed)


def test_the_default_landing_owes_the_int8_siblings_as_before():
    owed = _owed()
    assert {"qdrant_dense_int8", "arcadedb_dense_server_int8", "sqlite_vec_dense_int8", "arcadedb_dense_server"} <= owed, sorted(owed)
