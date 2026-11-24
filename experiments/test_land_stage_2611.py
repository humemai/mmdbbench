"""land_stage.py lands a 2026-11 stage's rows: screen, merge, freeze, export, gate, and nothing of another instrument.

Run with `python -m pytest test_land_stage_2611.py -q` from this directory (needs numpy and pandas, as the exporter does; the
full-chain tests also need matplotlib, pdftotext and Ghostscript, and are skipped with that reason when they are absent).

CAMPAIGN section 9 said "land_stage.py reads only 2026-10 rows today, so landing the new rows is a change of its own". The pull,
the instrument selector and the gates were already 2026-11 (#432, #434); what was left is the part between the pull and the
freeze, which is what these tests hold:

  * a pulled file is screened BEFORE the merge: a retired 2026-10 file, a file that mixes instruments, an unstamped row and a row
    of another engine commit are refused and nothing reaches the store;
  * the first landing meets no store (the October one is retired) and creates it;
  * landing is idempotent: the same pulled file twice leaves the store and the frozen rows as they were;
  * failed and censored cells land as what they are: the failed row is in the store as a failure and is not frozen, the censored
    flag reaches the frozen row, and no number is published for either;
  * the whole chain, on `fixtures/publish_2611` pulled from a fake bench host into a fake site, produces a payload with rows, and
    a rehearsal removes the payload it created from the site and restores the PAGE-SPEC block it rewrote.
"""
import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import test_publish_2611_e2e as E2E
from test_publish_2611_e2e import HERE, PIN, _fixture_rows, _run, _stage

sys.path.insert(0, str(HERE))

import land_stage as L  # noqa: E402
import merge_campaign as M  # noqa: E402

HOST_FILE = f"runs_page_{PIN}_2611.jsonl"


def _write(path, rows):
    Path(path).write_text("".join(json.dumps(r) + "\n" for r in rows))
    return Path(path)


def _restamp(rows, stamp):
    return [dict(r, instrument=stamp) for r in rows]


# ---------------------------------------------------------------------------------------------------- the screen
def test_a_retired_2026_10_file_is_refused():
    rows = _restamp(_fixture_rows()[:5], "2026-10")
    with pytest.raises(SystemExit) as exc:
        L.screen_pulled_rows(rows, PIN, HOST_FILE)
    msg = str(exc.value)
    assert "REFUSING" in msg and "2026-10: 5" in msg and "2026-11 rows only" in msg and HOST_FILE in msg


def test_a_file_mixing_instruments_is_refused_and_counts_each_stamp():
    rows = _fixture_rows()[:6]
    rows[0]["instrument"] = "2026-10"
    rows[1]["instrument"] = "2026-10"
    rows[2].pop("instrument")
    with pytest.raises(SystemExit) as exc:
        L.screen_pulled_rows(rows, PIN, HOST_FILE)
    assert "(no stamp): 1" in str(exc.value) and "2026-10: 2" in str(exc.value)


def test_a_row_of_another_engine_commit_is_refused():
    rows = _fixture_rows()[:4]
    rows[3]["engine_commit"] = "d36b4ca3a"
    with pytest.raises(SystemExit) as exc:
        L.screen_pulled_rows(rows, PIN, HOST_FILE)
    assert "another engine commit" in str(exc.value) and "d36b4ca3a: 1" in str(exc.value)


def test_a_truncated_commit_and_a_row_with_no_commit_pass():
    rows = _fixture_rows()[:4]
    rows[0]["engine_commit"] = PIN[:6]             # the stamp may be shorter than the pin
    rows[1]["engine_commit"] = PIN + "abcdef012"   # or longer
    rows[2]["engine_commit"] = None                # overlay and host-side rows carry none
    L.screen_pulled_rows(rows, PIN, HOST_FILE)


def test_the_real_2026_11_row_shape_passes():
    """Rows as qC01 wrote them on the bench host on 2026-10-25: pin e85469273, instrument 2026-11."""
    rows = [{"instrument": "2026-11", "engine_commit": "e85469273", "lane": "l2", "backend": b, "rc": 0, "error": None}
            for b in ("surrealdb_graph", "arangodb_graph")]
    L.screen_pulled_rows(rows, "e85469273", "runs_page_e85469273_2611.jsonl on mini")


# ---------------------------------------------------------------------------------------------------- the main() harness
class Host:
    """A fake bench host: `scp host:path dest` copies from a local directory, the way the pulls expect (globs included)."""

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put_rows(self, rows):
        return _write(self.root / HOST_FILE, rows)


@pytest.fixture
def landing(tmp_path, monkeypatch):
    """land_stage.main() pointed at a scratch results tree, a scratch site, a scratch pull directory and a fake host."""
    import glob

    for k in [k for k in os.environ if k.startswith("BENCH_")]:
        monkeypatch.delenv(k)
    results = _stage(tmp_path / "results")
    (results / "runs.jsonl").unlink()                       # the first 2026-11 landing meets no store
    host = Host(tmp_path / "host")
    site = tmp_path / "site"
    (site / "src" / "lib" / "dbbench").mkdir(parents=True)
    monkeypatch.setenv("BENCH_RESULTS_DIR", str(results))
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    monkeypatch.setattr(L, "RESULTS", results)
    monkeypatch.setattr(L, "SITE", site)
    monkeypatch.setattr(L, "SITE_PAYLOAD", site / "src" / "data" / "dbbench-benchmarks.json")
    monkeypatch.setattr(L, "SCRATCH", tmp_path / "scratch")
    monkeypatch.setattr(L, "REMOTE", str(host.root))
    monkeypatch.setattr(L, "PY", sys.executable)
    monkeypatch.setattr(L.os, "execv", lambda *a, **k: None)   # already running under the interpreter the steps use
    real_sh = L.sh

    def fake_sh(cmd, cwd=None, check=True, capture=False, env=None, quiet=False):
        if cmd[0] == "scp":
            src = str(cmd[-2]).split(":", 1)[1]
            got = glob.glob(src)
            for g in got:
                shutil.copy(g, cmd[-1])
            rc = 0 if got else 1
            if rc and check:
                raise subprocess.CalledProcessError(rc, cmd)
            return subprocess.CompletedProcess(cmd, rc)
        return real_sh(cmd, cwd=cwd, check=check, capture=capture, env=env, quiet=quiet)

    monkeypatch.setattr(L, "sh", fake_sh)
    return {"results": results, "host": host, "site": site, "tmp": tmp_path, "mp": monkeypatch}


def _land(landing, *extra, pin=PIN):
    landing["mp"].setattr(sys, "argv", ["land_stage.py", "--pin", pin, "--message", "test", *extra])
    return L.main()


def _fake_lanes_ts(site, ids):
    body = "\n".join(f'      {{\n        tableId: "{t}",\n        caption: "x",\n      }},' for t in ids)
    (site / "src" / "lib" / "dbbench" / "lanes.ts").write_text(
        f"export const dbbenchLanes = [\n  {{\n    tables: [\n{body}\n    ],\n  }},\n];\n")


def test_a_2026_10_file_never_reaches_the_store(landing, capsys):
    landing["host"].put_rows(_restamp(_fixture_rows()[:20], "2026-10"))
    with pytest.raises(SystemExit) as exc:
        _land(landing, "--dry-run")
    assert "2026-10: 20" in str(exc.value) and "2026-11 rows only" in str(exc.value)
    assert not (landing["results"] / "runs.jsonl").exists()


def test_a_mixed_file_never_reaches_the_store_and_a_dry_run_says_so(landing):
    rows = _fixture_rows()[:20]
    rows[7]["instrument"] = "2026-10"
    landing["host"].put_rows(rows)
    with pytest.raises(SystemExit) as exc:
        _land(landing, "--dry-run")
    assert "2026-10: 1" in str(exc.value)
    assert not (landing["results"] / "runs.jsonl").exists()


def test_a_clean_file_passes_the_screen_and_the_dry_run_writes_nothing(landing, capsys):
    landing["host"].put_rows(_fixture_rows()[:20])
    assert _land(landing, "--dry-run") == 0
    out = capsys.readouterr().out
    assert "20 rows pulled" in out and "DRY RUN: 20 row(s) would be merged" in out
    assert not (landing["results"] / "runs.jsonl").exists()


def test_a_pulled_file_replaces_the_scp_and_is_screened_like_a_pulled_one(landing, capsys):
    """BENCH_LAND_PULLED_FILE: the four-arm rows come from several results directories, merged into one file outside the script."""
    rows = _fixture_rows()[:20]
    pulled = _write(landing["tmp"] / "merged_fourarm.jsonl", rows)
    assert not (landing["host"].root / HOST_FILE).exists()      # the host has nothing: the old code's scp fails here
    landing["mp"].setenv("BENCH_LAND_PULLED_FILE", str(pulled))
    assert _land(landing, "--dry-run") == 0
    assert "20 rows pulled" in capsys.readouterr().out
    assert not (landing["results"] / "runs.jsonl").exists()
    bad = _write(landing["tmp"] / "mixed_fourarm.jsonl", _restamp(rows, "2026-10"))
    landing["mp"].setenv("BENCH_LAND_PULLED_FILE", str(bad))
    with pytest.raises(SystemExit) as exc:
        _land(landing, "--dry-run")
    assert "2026-11 rows only" in str(exc.value)


def test_a_missing_pulled_file_stops_and_never_falls_back_to_the_host(landing):
    landing["host"].put_rows(_fixture_rows()[:20])               # the host has rows; they must not be used
    landing["mp"].setenv("BENCH_LAND_PULLED_FILE", str(landing["tmp"] / "no_such_file.jsonl"))
    with pytest.raises(SystemExit) as exc:
        _land(landing, "--dry-run")
    assert "BENCH_LAND_PULLED_FILE" in str(exc.value) and "no_such_file.jsonl" in str(exc.value)
    assert not (landing["results"] / "runs.jsonl").exists()


# ---------------------------------------------------------------------------------------------------- the merge
def _merge(store_dir, incoming, monkeypatch):
    """merge_campaign.main() into `store_dir`, the way land_stage step 3 calls it."""
    monkeypatch.setattr(M, "CANON", str(Path(store_dir) / "runs.jsonl"))
    monkeypatch.setattr(sys, "argv", ["merge_campaign.py", "--from-file", str(incoming), "--apply"])
    M.main()


def test_the_first_landing_creates_the_store_and_the_second_changes_nothing(tmp_path, monkeypatch, capsys):
    store = tmp_path / "results"
    store.mkdir()
    incoming = _write(tmp_path / "in.jsonl", _fixture_rows())
    _merge(store, incoming, monkeypatch)
    first = (store / "runs.jsonl").read_bytes()
    assert len(first.splitlines()) == len(_fixture_rows())
    assert "creating it" in capsys.readouterr().out
    assert not list(store.glob("runs.jsonl.before-merge-*"))
    _merge(store, incoming, monkeypatch)                   # the same pull again
    assert (store / "runs.jsonl").read_bytes() == first
    assert "nothing new to merge" in capsys.readouterr().out


def test_failed_and_censored_cells_land_as_such_and_publish_no_number(tmp_path, monkeypatch):
    rows = _fixture_rows()
    cell_rows = [r for r in rows if r["lane"] == "l2" and r["backend"] == "arcadedb_graph_embedded"
                 and r["workload"] == "oltp" and r["scale"] == "sf1" and r.get("durability_class") in (None, "relaxed")]
    arc = max(cell_rows, key=lambda r: r["rep"])
    # a later attempt at the same rep that was killed: if the freeze took it, the rep's frozen numbers would be empty
    failed = dict(arc, rc=1, error="cell cap hit: killed at 3600 s", ts_utc="2026-11-06T13:00:00+00:00")
    for k in list(failed):                                  # a killed cell measured nothing
        if k.endswith("_ms") or k.endswith("_iters"):
            failed[k] = None
    censored = next(r for r in rows if r["lane"] == "l2" and r["backend"] == "arangodb_graph" and r.get("hop3f_censored") is True)
    landed = rows + [failed]

    store = tmp_path / "results"
    shutil.copytree(E2E.FIXTURE, store)
    (store / "runs.jsonl.gz").unlink()
    _merge(store, _write(tmp_path / "in.jsonl", landed), monkeypatch)

    # the rows are merged exactly as the host wrote them
    stored = [json.loads(l) for l in (store / "runs.jsonl").read_text().splitlines()]
    assert failed in stored and censored in stored

    # the freeze keeps the cell's good rep, skips the failed one, and carries the censored flag instead of a number
    proc = _run("make_paper_tables.py", store)
    assert proc.returncode == 0, proc.stderr[-1500:]
    frozen = list(csv.DictReader((store / "runs_paper.csv").open()))
    cell = [r for r in frozen if r["lane"] == "l2" and r["backend"] == "arcadedb_graph_embedded" and r["workload"] == "oltp"
            and r["scale"] == "sf1" and str(int(float(r["rep"]))) == str(arc["rep"])
            and r["durability_class"] == arc["durability_class"]]
    assert cell, "the good attempt of the failed cell's key must still be frozen"
    assert all(r["hop1_p50_ms"] != "" and float(r["hop1_p50_ms"]) == arc["hop1_p50_ms"] for r in cell), \
        "the failed attempt superseded the good one in the freeze"
    ar = next(r for r in frozen if r["lane"] == "l2" and r["backend"] == "arangodb_graph" and r["workload"] == "oltp"
              and r["scale"] == "sf1" and r["hop3f_censored"] in ("True", "true", "1", "1.0"))
    assert ar["warm_hop3f_p50_ms"] == "", "a censored warm query publishes no number"


# ---------------------------------------------------------------------------------------------------- e4 is not a prerequisite of l2
def _without_e4(tmp_path):
    results = _stage(tmp_path / "results")
    shutil.rmtree(results / f"e4decomp_{PIN}")
    return results


def test_a_landing_scoped_to_l2_exports_without_the_e4_artifacts(tmp_path):
    """The 2026-11 chain has no e4decomp stage; qC01 (l2) must be landable before e4 has run at the pin."""
    results = _without_e4(tmp_path)
    for script in ("make_paper_tables.py", "export_web.py"):
        done = _run(script, results, BENCH_ONLY_LANES="l2")
        assert done.returncode == 0, done.stderr[-1500:]
    ids = [t["id"] for t in json.loads((results / "web_benchmarks.json").read_text())["tables"]]
    assert ids and "e4" not in ids


def test_an_unscoped_landing_and_one_scoped_with_e4_still_need_the_e4_artifacts(tmp_path):
    results = _without_e4(tmp_path)
    assert _run("make_paper_tables.py", results).returncode == 0
    for scope in ({}, {"BENCH_ONLY_LANES": "l2,e4"}):
        done = _run("export_web.py", results, **scope)
        assert done.returncode != 0 and f"e4decomp_{PIN} missing" in done.stderr


# ---------------------------------------------------------------------------------------------------- the first scoped landing at a new pin (#147)
@pytest.fixture
def fresh_exporter():
    """The in-process read of the published lanes imports export_web, whose module scope reads BENCH_ONLY_LANES and the pin once: a
    cached import would hide the failure. The cached module is put back afterwards."""
    saved = sys.modules.pop("export_web", None)
    yield
    sys.modules.pop("export_web", None)
    if saved is not None:
        sys.modules["export_web"] = saved


def _payload_of(tmp_path, ids):
    p = tmp_path / "payload.json"
    p.write_text(json.dumps({"tables": [{"id": t} for t in ids]}))
    return p


def _results_without_e4(tmp_path, monkeypatch):
    """A results tree with no e4decomp directory, and none of the BENCH_ variables of the environment this suite runs in."""
    for k in [k for k in os.environ if k.startswith("BENCH_")]:
        monkeypatch.delenv(k)
    results = tmp_path / "results"
    results.mkdir()
    monkeypatch.setenv("BENCH_RESULTS_DIR", str(results))
    return results


def test_the_first_scoped_landing_at_a_new_pin_reads_the_published_lanes_before_any_pull(landing, fresh_exporter, capsys):
    """Before #147 `land_stage --only-lanes l2` at a pin with no e4decomp directory ended with the one line `e4decomp_<pin> missing` and rc 1,
    before the pull, though a landing scoped away from e4 needs no such directory."""
    shutil.rmtree(landing["results"] / f"e4decomp_{PIN}")
    landing["host"].put_rows([r for r in _fixture_rows() if r["lane"] == "l2"][:20])
    L.SITE_PAYLOAD.parent.mkdir(parents=True)
    L.SITE_PAYLOAD.write_text(json.dumps({"tables": [{"id": "l2"}, {"id": "e2"}]}))
    assert _land(landing, "--only-lanes", "l2", "--dry-run") == 0
    out = capsys.readouterr().out
    assert "cumulative: landing l2 and keeping e2 already on the page" in out and "DRY RUN" in out
    assert "BENCH_ONLY_LANES" not in os.environ                                # lent for the import, not left behind


def test_the_published_lanes_import_sees_the_landings_scope_and_the_environment_is_put_back(tmp_path, monkeypatch, fresh_exporter):
    _results_without_e4(tmp_path, monkeypatch)
    payload = _payload_of(tmp_path, ["l2", "e2", "l3d", "e4"])                 # e4 names no lane
    assert L._published_lanes(payload, pin=PIN, scope={"l2"}) == {"l2", "e2", "l3d"}
    assert "BENCH_ONLY_LANES" not in os.environ and "BENCH_ENGINE_COMMIT" not in os.environ
    monkeypatch.setenv("BENCH_ONLY_LANES", "l4")                               # a value that was there is restored, not dropped
    sys.modules.pop("export_web")
    assert L._published_lanes(payload, pin=PIN, scope={"l2", "e2"}) == {"l2", "e2", "l3d"}
    assert os.environ["BENCH_ONLY_LANES"] == "l4"


@pytest.mark.parametrize("scope, shown", [((), "none: the whole store"), (("l2", "e4"), "e4,l2")])
def test_a_refusal_of_the_exporter_at_that_import_is_reported_with_its_cause(tmp_path, monkeypatch, fresh_exporter, scope, shown):
    """No scope, or a scope that names e4, still needs the directory: the exporter refuses with a SystemExit, which `except Exception` did not catch."""
    _results_without_e4(tmp_path, monkeypatch)
    with pytest.raises(SystemExit) as exc:
        L._published_lanes(_payload_of(tmp_path, ["l2"]), pin=PIN, scope=scope)
    msg = str(exc.value)
    assert msg.startswith("REFUSING: cannot read which lanes") and "export_web refused to import" in msg
    assert f"scope [{shown}]" in msg and f"pin {PIN}" in msg and f"e4decomp_{PIN} missing; E4 is pinned only" in msg
    assert "BENCH_ONLY_LANES" not in os.environ and "BENCH_ENGINE_COMMIT" not in os.environ


# ---------------------------------------------------------------------------------------------------- two chains, one pin, one landing (#147)
def test_two_worktrees_land_from_a_pre_created_union_of_the_sparse_and_e4_files(landing, capsys):
    """PUBLISHING.md, "Two chains, one pin, one landing": the scp calls for the sparse and e4 files are check=False and a directory that
    holds files is kept, so a landing reads the union of the two worktrees that was copied in before the run."""
    results = landing["results"]
    for d in (f"sparse_mp_{PIN}", f"e4decomp_{PIN}"):
        shutil.rmtree(results / d, ignore_errors=True)
    sp, e4 = results / f"sparse_mp_{PIN}", results / f"e4decomp_{PIN}"
    sp.mkdir()
    e4.mkdir()
    for name in ("sp_arcadedb_sparse_small.json", "sp_arcadedb_sparse_native_small.json"):     # the JVM worktree's file, the native one's
        (sp / name).write_text(json.dumps([{"from": name}]))
    for rep in (1, 2, 3):                                                                      # the e4 artifacts exist in the JVM worktree only
        (e4 / f"decomp3m_{PIN}_rep{rep}.json").write_text(json.dumps({"rep": rep}))
    landing["host"].put_rows(_fixture_rows()[:20])                    # the host has the rows file and neither directory
    before = {p.name: p.read_bytes() for d in (sp, e4) for p in d.iterdir()}
    rc = _land(landing, "--dry-run")
    out = capsys.readouterr().out
    assert rc == (1 if "WOULD REFUSE" in out else 0), (rc, out[-300:])      # the exit status says what the text says (#163); this test is about the union, not about the owed files
    assert f"sparse_mp_{PIN}: 2 file(s)" in out and f"e4decomp_{PIN}: 3 rep file(s)" in out
    assert {p.name: p.read_bytes() for d in (sp, e4) for p in d.iterdir()} == before


def test_the_e4_pull_name_is_the_one_e4_decomp_writes_and_export_web_reads():
    """The e4 directory has no `_2611` suffix, unlike the sparse and dense ones, and that is right: it is written and read under this name."""
    assert "/e4decomp_{args.pin}/decomp3m_*.json" in (HERE / "land_stage.py").read_text()
    assert 'f"e4decomp_{pin}"' in (HERE / "e4_decomp.py").read_text()
    assert 'f"e4decomp_{os.environ.get(' in (HERE / "export_web.py").read_text()


# ---------------------------------------------------------------------------------------------------- a failed or missing small cell is named (#147)
def test_a_failed_and_a_missing_small_cell_are_named_before_the_merge_and_the_landing_goes_on(landing, capsys):
    """The pair gate names the tables of the size class, not the cell; the landing names the cells first and does not stop."""
    fixture = [r for r in _fixture_rows() if r["backend"] in ("arcadedb_embedded", "arcadedb_server", "arcadedb_graph_embedded")]
    old = [dict(r, engine_commit="a3a5d1245", engine_version="26.11.1", ts_utc="2026-11-10T10:00:00+00:00") for r in fixture]
    _write(landing["results"] / "runs.jsonl", old)                                        # the store: the 26.11.1 rows of every cell
    new = [dict(r, rc=1) if (r["backend"] == "arcadedb_server" and r["rep"] == 3) else r
           for r in fixture if r["backend"] != "arcadedb_graph_embedded"]                 # server rep 3 failed; the graph arm never ran
    landing["host"].put_rows(new)
    assert _land(landing, "--dry-run") == 0
    out = capsys.readouterr().out
    assert "WARNING: " in out and f"no rc=0 row at the pin {PIN}" in out
    lines = [l.strip() for l in out.splitlines() if l.startswith("    ") and "arcadedb_" in l]
    assert lines and all(l.startswith(("l1tpc tpch1", "l2 sf1")) for l in lines), lines
    assert any(l.startswith("l1tpc tpch1 oltp arcadedb_server [jvm]") and "rep 3 failed at the pin (rc=1)" in l
               and "the freeze keeps 26.11.1 at a3a5d1245" in l for l in lines), lines
    assert any(l.startswith("l2 sf1 oltp arcadedb_graph_embedded [jvm]") and "rep 1 no row at the pin" in l for l in lines), lines
    assert not any("arcadedb_embedded [jvm]" in l for l in lines), lines                  # every repetition of the embedded cells landed
    assert "DRY RUN: " in out                                                             # a warning, not a refusal
    # with every cell present at the pin there is no block
    landing["host"].put_rows([dict(r, rc=0) for r in fixture])
    assert _land(landing, "--dry-run") == 0
    assert "WARNING: " not in capsys.readouterr().out


# ---------------------------------------------------------------------------------------------------- the whole chain
def _chain_available():
    if shutil.which("pdftotext") is None or shutil.which("gs") is None:
        return "make_paper_figures needs pdftotext and Ghostscript"
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        return "make_paper_figures draws with matplotlib"
    return None


needs_chain = pytest.mark.skipif(_chain_available() is not None, reason=_chain_available() or "")


@pytest.fixture
def landed_twice(landing, capfd):
    """The fixture pulled from the fake host and landed (a rehearsal: no --apply) twice into an empty store and an empty site."""
    landing["host"].put_rows(_fixture_rows())
    seen = []
    real_restore = L._restore_this_runs_writes

    def spy(dirty_before, site_files, site_new=()):
        if L.SITE_PAYLOAD.exists():                         # read the payload the site would have been given
            seen.append(json.loads(L.SITE_PAYLOAD.read_text()))
        return real_restore(dirty_before, site_files, site_new)

    landing["mp"].setattr(L, "_restore_this_runs_writes", spy)
    # a first pass learns which tables the payload carries, so the fake page source can ask for exactly those
    spec_before = (HERE / "PAGE-SPEC.md").read_bytes()
    try:
        _fake_lanes_ts(landing["site"], [])
        first_try = _land(landing)                         # refused: the page source asks for no table, the payload has them
        ids = [t["id"] for t in json.loads((landing["results"] / "web_benchmarks.json").read_text())["tables"]]
        _fake_lanes_ts(landing["site"], ids)
        capfd.readouterr()
        rc1 = _land(landing)
        out1 = capfd.readouterr().out
        store1 = (landing["results"] / "runs.jsonl").read_bytes()
        frozen1 = (landing["results"] / "runs_paper.csv").read_bytes()
        rc2 = _land(landing)
        out2 = capfd.readouterr().out
    finally:
        spec_after = (HERE / "PAGE-SPEC.md").read_bytes()
        if spec_after != spec_before:                       # never leave the checkout dirty, whatever failed above
            (HERE / "PAGE-SPEC.md").write_bytes(spec_before)
            raise AssertionError("a rehearsed landing left PAGE-SPEC.md rewritten")
    return {"rc1": rc1, "rc2": rc2, "out1": out1, "out2": out2, "store1": store1, "frozen1": frozen1, "seen": seen,
            "first_try": first_try, "ids": ids, **landing}


@needs_chain
def test_a_rehearsed_landing_of_the_fixture_ends_with_a_payload_with_rows(landed_twice):
    d = landed_twice
    assert d["first_try"] == 1, "a payload whose tables the page source does not ask for is refused"
    assert d["rc1"] == 0, d["out1"][-2500:]
    payload = d["seen"][-1]
    assert payload["instrument"] == "2026-11" and not payload.get("skeleton")
    assert payload["tables"] and all(t["entries"] for t in payload["tables"] if t["id"] in ("l2", "e2", "l3d"))
    assert "DRY RUN: stopping before build and commit" in d["out1"]


@needs_chain
def test_the_rehearsal_leaves_no_payload_in_the_site(landed_twice):
    assert not (landed_twice["site"] / "src" / "data" / "dbbench-benchmarks.json").exists()
    assert "removed the site's new generated file(s)" in landed_twice["out1"]


@needs_chain
def test_landing_the_same_pull_twice_is_the_same_result(landed_twice):
    d = landed_twice
    assert d["rc2"] == 0, d["out2"][-2500:]
    assert (d["results"] / "runs.jsonl").read_bytes() == d["store1"]
    assert (d["results"] / "runs_paper.csv").read_bytes() == d["frozen1"]
    assert "nothing new to merge" in d["out2"]
    assert len(d["seen"]) >= 2
    assert json.dumps(d["seen"][-1]["tables"], sort_keys=True) == json.dumps(d["seen"][-2]["tables"], sort_keys=True)


# THE LANDING DEFAULTS NAME THIS REPOSITORY (mmdbbench#26, #100). The host's stages write their rows into the results directory of a
# checkout of this repository; the two defaults that still named the old repository's results directory were flipped when the old
# repository was archived.
def _land_remote(env_value):
    """The REMOTE that a fresh import of land_stage reads (it reads BENCH_LAND_REMOTE once, at import)."""
    env = {k: v for k, v in os.environ.items() if k != "BENCH_LAND_REMOTE"}
    if env_value is not None:
        env["BENCH_LAND_REMOTE"] = env_value
    out = subprocess.run([sys.executable, "-c", "import land_stage; print(land_stage.REMOTE)"],
                         cwd=HERE, env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_land_stage_pulls_from_this_repository_and_the_environment_overrides_it():
    assert _land_remote(None) == "~/repos/humemai/mmdbbench/experiments/results"
    assert _land_remote("~/elsewhere/results") == "~/elsewhere/results"


def test_merge_campaign_pulls_from_this_repository_and_the_flag_overrides_it(monkeypatch):
    seen = []

    def fake_run(cmd, *a, **k):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 1)     # scp "fails", so main() stops right after naming what it would pull

    monkeypatch.setattr(M.subprocess, "run", fake_run)
    for argv, want in ((["merge_campaign.py"], "mini:~/repos/humemai/mmdbbench/experiments/results/runs.jsonl"),
                       (["merge_campaign.py", "--remote", "~/elsewhere/runs.jsonl"], "mini:~/elsewhere/runs.jsonl")):
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(SystemExit):
            M.main()
        assert seen[-1][:2] == ["scp", "-q"] and seen[-1][2] == want
