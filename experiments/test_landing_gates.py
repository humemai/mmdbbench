"""Landing gates G1 to G3 (humemai/mmdbbench#78, refs #52): a staged cell without rows, a dropped row and an unexplained collision stop the landing.

Round 2 lost the 18 GAV-on rows of l2 olap (#77) and nothing said so. Light: synthetic rows and a synthetic roster, no files except a temporary directory.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))
os.environ.setdefault("BENCH_ONLY_LANES", "l2")
import landing_gates as G  # noqa: E402
import merge_fourarm_rows as MF  # noqa: E402

BASE = {"lane": "l2", "backend": "arcadedb_graph_embedded", "workload": "olap", "scale": "sf1full", "engine_backend": "jvm", "instrument": "2026-11", "rc": 0}


def row(rep, gav=True, **kw):
    r = dict(BASE, rep=rep, run_id=f"l2_arcadedb_graph_embedded_olap_sf1full_r{rep}", gav=gav, ts_utc=f"2026-11-07T22:4{rep}:00+00:00", **kw)
    if gav is False:
        r["backend_arm"] = "nogav"
    return r


ROSTER = {"cells": [dict(lane="l2", scale="sf1full", workload="olap", backend="arcadedb_graph_embedded", cls="relaxed", arm=""),
                    dict(lane="l2", scale="sf1full", workload="olap", backend="arcadedb_graph_embedded", cls="relaxed", arm="nogav")]}


def test_the_roster_gate_names_a_staged_arm_that_has_no_rows():
    """The round 2 store: three clean reps of the no-GAV arm, none of the GAV arm."""
    rows = [row(i, gav=False) for i in (1, 2, 3)]
    probs, summ = G.roster_problems(rows, ROSTER)
    assert probs == ["MISSING l2/sf1full/olap/arcadedb_graph_embedded/relaxed/jvm: staged, no row"], probs
    assert summ["complete"] == 1 and summ["unexplained"] == 1


def test_the_roster_gate_passes_both_arms_and_names_short_cells_and_orphans():
    rows = [row(i, gav=g) for i in (1, 2, 3) for g in (True, False)]
    assert G.roster_problems(rows, ROSTER)[0] == []
    short = [r for r in rows if not (r["rep"] == 3 and r["gav"] is False)]
    probs, _ = G.roster_problems(short, ROSTER)
    assert probs == ["SHORT l2/sf1full/olap/arcadedb_graph_embedded/relaxed/nogav/jvm: 2 clean repetition(s) of 3, no row says why"], probs
    explained = short + [dict(row(3, gav=False), error="killed", rc=137)]
    assert G.roster_problems(explained, ROSTER)[0] == []                        # a row that says why explains the short cell
    probs, summ = G.roster_problems(rows + [dict(row(1), scale="sf99", run_id="x")], ROSTER)
    assert probs == [] and summ["orphan_cells"] == 1


def test_the_committed_roster_is_the_stage_generators_and_names_both_gav_arms():
    doc = G.load_roster()
    assert (doc["cells"], doc["outside_cells"]) == G.roster_cells() and doc["cells_sha256"]
    arms = {(c["backend"], c["arm"]) for c in doc["cells"] if c["lane"] == "l2" and c["workload"] == "olap"}
    assert ("arcadedb_graph_embedded", "") in arms and ("arcadedb_graph_embedded", "nogav") in arms and ("arcadedb_graph_server", "nogav") in arms


def test_a_drop_of_a_row_of_another_arm_class_or_client_is_refused_and_a_retry_may_be_superseded():
    on, off = row(1), row(1, gav=False)
    assert G.drop_problems([(on, off, "superseded")]) and "gav" in G.drop_problems([(on, off, "superseded")])[0]
    assert G.drop_problems([(dict(on, durability_class="strict"), on, "superseded")])
    assert G.drop_problems([(dict(on, arcadedb_http_client="lean"), on, "superseded")])
    assert G.drop_problems([(dict(on, error="killed"), on, "retry")]) == []
    rec = G.drop_record(off, on, "superseded")
    assert rec["differs_from_kept_in"] == ["gav", "backend_arm"] and rec["reason"] == "superseded"


def test_the_four_arm_merge_reports_what_it_drops_and_refuses_an_identity_drop(tmp_path):
    pairs = []
    rows, _ = MF.merge([_w(tmp_path, "a", [row(1), dict(row(1), error="killed")])], dropped=pairs)
    assert len(rows) == 1 and [p[2] for p in pairs] == ["an error row dropped: a clean row of the same key exists"], pairs
    assert G.drop_problems(pairs) == []
    pairs = []
    MF.merge([_w(tmp_path, "b", [row(1), dict(row(1), durability_class="strict")])], dropped=pairs)       # same key, another class: not a retry
    assert G.drop_problems(pairs), pairs


def test_the_collision_gate_counts_arm_pairs_and_reruns_and_refuses_the_rest():
    ok = [row(1), row(1, gav=False), dict(row(2), wheel_label="26.11.1.post2"), row(2)]
    probs, kinds = G.collision_problems(ok)
    assert probs == [] and kinds == {"arms": 1, "rerun": 1}, (probs, kinds)
    assert G.collision_problems([row(1), dict(row(1), ts_utc="2026-11-08T00:00:00+00:00")])[0]                # a duplicate
    assert G.collision_problems([row(1), dict(row(1), durability_class="strict")])[0]                         # a class the key does not include


def test_the_page_gate_finds_a_staged_arm_the_freeze_holds_and_the_page_does_not_print():
    rows = [row(i, gav=g) for i in (1, 2, 3) for g in (True, False)]
    entry = lambda label: {"backend": label, "backend_key": "arcadedb_graph_embedded", "scale": "sf1full"}
    both = {"tables": [{"id": "l2olap", "entries": [entry("ArcadeDB (embedded, GAV, JVM build)"), entry("ArcadeDB (embedded, JVM build)")]}]}
    assert G.page_problems(both, rows, ROSTER) == []
    one = {"tables": [{"id": "l2olap", "entries": [entry("ArcadeDB (embedded, JVM build)")]}]}
    assert len(G.page_problems(one, rows, ROSTER)) == 1


def test_an_arm_that_export_web_keeps_off_the_page_is_not_owed_by_the_page_gate():
    assert "postgres_tuned" in G.off_page_arms()
    rows = [dict(row(i), lane="l1tpc", backend="postgres_tuned", workload="oltp", scale="tpch1", run_id=f"x{i}") for i in (1, 2, 3)]
    roster = {"cells": [dict(lane="l1tpc", scale="tpch1", workload="oltp", backend="postgres_tuned", cls="relaxed", arm="")]}
    assert G.page_problems({"tables": [{"id": "docs_oltp", "entries": []}]}, rows, roster) == []


def test_the_roster_carries_the_arms_outside_the_profile_with_their_source_line():
    """neo4j_e2, falkordb and the other arms of make_2611_stages.OUTSIDE are registered but not in the paper pass: no stage mentions them. They are not staged cells (the gate does not
    fail on them) and are printed in their own section with the source line."""
    doc = G.load_roster()
    assert {c["backend"] for c in doc["outside_cells"]} >= {"neo4j_e2", "falkordb_graph"}
    assert not [c for c in doc["cells"] if c["backend"].startswith(("neo4j_e2", "falkordb"))]
    assert doc["outside"]["prefixes"] == ["neo4j_e2", "falkordb", "milvus", "elasticsearch", "chroma", "lancedb", "questdb"]
    assert doc["outside"]["source"].startswith("experiments/make_2611_stages.py:") and doc["outside"]["source"].split(":")[1].isdigit()
    text = "\n".join(G.outside_section(doc))
    assert "outside the profile (by design, source: experiments/make_2611_stages.py:" in text and "neo4j_e2" in text


PEND = {"cell": "l2/sf10/oltp/pgage_graph/relaxed", "reason": "not run: censored at sf1, so censored here too (cap rule); the sf1 failure was the harness's fault and was rerun clean",
        "ref": "DECISIONS #188", "since": "pending rerun after the PG+AGE sf1 fix, 2026-11-14"}


def _pend_roster():
    return {"cells": [dict(lane="l2", scale="sf10", workload="oltp", backend="pgage_graph", cls="relaxed", arm="")]}


def test_a_pending_cell_is_printed_not_failed_and_a_stale_entry_is_refused():
    roster = _pend_roster()
    assert G.roster_problems([], roster)[0] == ["MISSING l2/sf10/oltp/pgage_graph/relaxed: staged, no row"]
    probs, summ = G.roster_problems([], roster, pending=[PEND])
    assert probs == [] and summ["pending"] == [PEND["cell"]] and summ["unexplained"] == 0
    rows = [dict(row(i), lane="l2", backend="pgage_graph", workload="oltp", scale="sf10", engine_backend=None, run_id=f"pg{i}") for i in (1, 2, 3)]
    probs, summ = G.roster_problems(rows, roster, pending=[PEND])
    assert len(probs) == 1 and probs[0].startswith("STALE PENDING l2/sf10/oltp/pgage_graph/relaxed") and "remove it" in probs[0], probs     # the cell has rows now
    probs, _ = G.roster_problems([], roster, pending=[dict(PEND, cell="l2/sf10/oltp/nosuch/relaxed")])
    assert any(p.startswith("UNKNOWN PENDING") for p in probs), probs                                    # an entry that names no staged cell


def test_the_committed_pending_list_names_staged_cells_and_carries_a_reason_a_reference_and_a_date():
    pending = G.load_pending()
    cells = {f"{c['lane']}/{c['scale']}/{c['workload']}/{c['backend']}/{c['cls']}" + (f"/{c['arm']}" if c["arm"] else "") for c in G.load_roster()["cells"]}
    # Not pinned to which cells are owed today: that is data, and it changes with every landing (the list is empty once the owed cells have rows, as after the n=3 landing of
    # 2026-11-15; the planted-entry test above proves a stale or unknown entry is refused). What must hold for whatever is listed:
    assert all(p["cell"] in cells and p["reason"] and p["ref"] and p["since"] for p in pending), pending


def _merge(store, incoming):
    import subprocess
    d = Path(tempfile.mkdtemp(prefix="gate-merge-"))
    (d / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in store))
    (d / "in.jsonl").write_text("".join(json.dumps(r) + "\n" for r in incoming))
    env = dict(os.environ, BENCH_RESULTS_DIR=str(d))
    done = subprocess.run([sys.executable, str(HERE / "merge_campaign.py"), "--from-file", str(d / "in.jsonl"), "--apply"], cwd=HERE, env=env, capture_output=True, text=True, timeout=300)
    return done, d


def test_the_store_merge_skips_an_exact_duplicate_keeps_a_client_twin_and_refuses_an_identity_drop():
    """merge_campaign skipped a row as 'already present' on (canonical key, ts_utc). The twin rows of one cell on the two HTTP clients share the key and, in a generated fixture, the
    time (the CI failure of the first version of this gate: 93 rows). Now a row is already here only with the same run_id, and a skip that differs in an identity field is refused."""
    a = row(1, gav=False)
    done, d = _merge([a], [a, dict(a, run_id=a["run_id"] + "_clientlean", arcadedb_http_client="lean")])
    assert done.returncode == 0, done.stdout[-400:] + done.stderr[-400:]
    assert "already present : 1 of 2 incoming rows, skipped" in done.stdout, done.stdout
    assert len((d / "runs.jsonl").read_text().splitlines()) == 2                            # the exact duplicate was skipped, the client twin was appended
    assert len((d / "dropped_rows.jsonl").read_text().splitlines()) == 1
    done, _ = _merge([a], [dict(a, durability_class="strict")])                              # same key, time and run_id, another class: not a retry
    assert done.returncode != 0 and "REFUSING" in (done.stdout + done.stderr), done.stdout[-300:] + done.stderr[-300:]


def _w(d, name, rows):
    p = Path(d) / name
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return str(p)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn) and not fn.__code__.co_varnames[:1] == ("tmp_path",):
            fn()
            print("ok", name)
