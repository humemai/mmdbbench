"""Landing gate G1 for the dense lane: an error row at the key, and the cap rule's skip of a larger scale, are stated reasons; the cells the paper-2611 PROFILE drops
(quantized arms, Neo4j and Memgraph dense) are derived from the generator and carried by the roster with their rule and source line; a cell with none of these
still fails (the l3d landing of 2026-11-14: 31 l3d cells were reported unexplained although the mini's STATUS says why).

Light: synthetic rows and a synthetic roster, plus the generator's own lists. Run with pytest, or as plain functions from this directory."""
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("BENCH_ENGINE_COMMIT", "abc123def")
import landing_gates as G  # noqa: E402

CELL = dict(lane="l3d", scale="small", workload="search", backend="cratedb_dense", cls="relaxed", arm="")
BIG = dict(CELL, scale="deep10m")


def _err(scale="small", error="timeout_after_1800s", backend="cratedb_dense", **kw):
    r = {"lane": "l3d", "scale": scale, "workload": "search", "backend": backend, "durability_class": "relaxed", "instrument": "2026-11", "rep": 1, "rc": -1,
         "error": error}
    r.update(kw)
    return r


def test_an_error_row_at_the_key_is_a_stated_reason():
    roster = {"cells": [CELL]}
    assert G.roster_problems([], roster)[0] == ["MISSING l3d/small/search/cratedb_dense/relaxed: staged, no row"]      # no row, no error row: still fails
    probs, summ = G.roster_problems([], roster, errors=[_err()])
    assert probs == [] and summ["explained_short"] == 1 and summ["unexplained"] == 0


def test_an_error_row_of_another_cell_explains_nothing():
    roster = {"cells": [CELL]}
    for other in (_err(backend="surrealdb_dense"), _err(scale="deep10m"), _err(workload="insert")):
        probs, _ = G.roster_problems([], roster, errors=[other])
        assert len(probs) == 1, other


def test_a_timeout_at_a_smaller_scale_is_the_cap_rules_skip_of_the_larger_one_and_nothing_else_is():
    roster = {"cells": [BIG]}
    probs, summ = G.roster_problems([], roster, errors=[_err("small")])
    assert probs == [] and summ["explained_short"] == 1
    assert len(G.roster_problems([], roster, errors=[_err("small", error="out of memory: the heap")])[0]) == 1      # only a timeout is the cap rule
    assert len(G.roster_problems([], roster, errors=[])[0]) == 1                                                       # no error row at all
    assert len(G.roster_problems([], {"cells": [CELL]}, errors=[_err("deep10m")])[0]) == 1                           # a larger scale never explains a smaller one


def test_the_error_rows_of_the_store_are_read_for_the_instrument_only():
    d = Path(tempfile.mkdtemp())
    rows = [_err(), _err(instrument="2026-10"), dict(_err(), error=None, rc=0), _err(lane="l2")]
    (d / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    got = G.load_error_rows(d, {"l3d"})
    assert len(got) == 1 and got[0]["lane"] == "l3d" and got[0]["error"].startswith("timeout")
    assert G.load_error_rows(d / "nope", {"l3d"}) == []


def test_the_profile_drops_are_derived_from_the_generator_and_carry_their_rule_and_source_line():
    import make_2611_stages as M
    dropped = G.roster_dropped()
    assert dropped["profile"] == M.DEFAULT_PROFILE and dropped["cells"]
    for c in dropped["cells"]:
        assert M.drop_reason(M.DEFAULT_PROFILE, c["lane"], c["backend"]) == c["reason"], c          # derived, not typed
        assert c["reason"] in dropped["rules"] and dropped["rules"][c["reason"]]["why"] == M.DROP_WHY[c["reason"]]
        assert dropped["rules"][c["reason"]]["source"].startswith("experiments/make_2611_stages.py:")
    names = {(c["lane"], c["backend"]) for c in dropped["cells"]}
    assert ("l3d", "neo4j_dense") in names and ("l3d", "memgraph_dense") in names and ("l3d", "arcadedb_dense_embedded_int8") in names
    assert ("l3d", "qdrant_dense_int8") in names and ("l3d", "arcadedb_dense_server") not in names                    # the fp32 arms stay staged
    inside = {(c["lane"], c["backend"]) for c in G.roster_cells()[0]}
    assert not inside & names, "a cell the profile drops is still a staged cell"


def test_the_committed_roster_carries_the_profile_drops_and_still_names_every_fp32_dense_cell():
    doc = G.load_roster()
    assert doc["profile_dropped"] == G.roster_dropped()
    staged = {(c["backend"], c["scale"]) for c in doc["cells"] if c["lane"] == "l3d"}
    for b in ("arcadedb_dense_embedded", "arcadedb_dense_server", "qdrant_dense", "redis_dense", "cratedb_dense", "surrealdb_dense"):
        assert (b, "small") in staged and (b, "deep10m") in staged, b


def test_a_staged_cell_with_no_row_no_error_row_and_no_profile_drop_still_fails_on_the_real_roster():
    doc = G.load_roster()
    cells = [c for c in doc["cells"] if c["lane"] == "l3d" and c["backend"] == "pgvector_dense"]
    assert cells
    probs, _ = G.roster_problems([], {"cells": cells})
    assert len(probs) == len(cells) and all(p.startswith("MISSING ") for p in probs)
