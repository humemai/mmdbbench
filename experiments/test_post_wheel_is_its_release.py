"""A `.postN` wheel of an engine release is that release for the freeze, the page and the gates (humemai/mmdbbench#53, refs #52).

A wheels-only `26.11.1.postN` carries the engine jars of `26.11.1` (DECISIONS #297, engine_pin.jar_pin; byte-identity proven at the release,
DECISIONS #324 and #330). A rerun on it replaces the row of its cell at the cell's own pin (DECISIONS #327), and the page and the paper never
name the rerun. Before this change the freeze kept `engine_version` `26.11.1.post3` on those rows and two gates refused it:
`arm_identity.pair_problems` (two builds name different engine_version values) and `export_web._one_version` (an entry pools two versions).

What each test proves is in its docstring. Run with `python -m pytest test_post_wheel_is_its_release.py -q` from this directory; the exporter test
needs numpy and pandas and stages the publish_2611 fixture, like test_build_pair_page.py. The unit tests need neither (except the two on
`_one_version`, which import export_web).
"""
import copy
import datetime
import gzip
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import arm_identity as AI  # noqa: E402

REL = "26.11.1"
POST = "26.11.1.post3"
COMMIT = "a3a5d1245"
FIXTURE = HERE / "fixtures" / "publish_2611" / "results"
PIN = "261100fix"


def row(version=REL, build="native", backend="arcadedb_graph_embedded", commit=COMMIT, **kw):
    r = {"lane": "l2", "scale": "sf1", "workload": "oltp", "backend": backend, "engine_version": version, "engine_commit": commit,
         "engine_backend": build}
    r.update(kw)
    return r


def post(**kw):
    """A row of the post3 wheel: the raw identity (wheel_label and friends) rides on it."""
    return row(POST, wheel_label=POST, wheel_name="arcadedb-26.11.1.post3-py3-none-manylinux_2_28_x86_64.whl", wheel_sha256="c" * 64, **kw)


# ---------------------------------------------------------------- the one definition
def test_a_post_wheel_names_its_release_and_nothing_else_is_stripped():
    assert AI.engine_release(POST) == REL and AI.engine_release("26.11.1.post12") == REL
    assert AI.engine_release(REL) == REL and AI.engine_release("26.11.1.dev0") == "26.11.1.dev0"
    assert AI.engine_release("server:26.11.1 (build abc123def/1/main)") == "server:26.11.1 (build abc123def/1/main)"
    assert AI.engine_release(None) == "" and AI.engine_release("PostgreSQL 17.11 + age:1.7.0") == "PostgreSQL 17.11 + age:1.7.0"


def test_a_post_row_is_its_release_only_when_every_row_of_the_release_names_one_commit():
    assert AI.post_releases([row(), post()]) == {REL}
    assert AI.post_releases([post()]) == {REL}                                   # a freeze of post rows only still has one commit
    assert AI.post_releases([row(), post(commit="fff000999")]) == set()          # two commits under one release
    assert AI.post_releases([row(commit=""), post(commit="")]) == set()          # no commit, nothing proves the jars equal
    assert AI.post_releases([row(), post(), row("26.11.2", commit="fff000999")]) == {REL, "26.11.2"}   # per release, not across releases
    # a served row's banner and a comparator are not in-process ArcadeDB rows: they never count, never collapse
    assert AI.post_releases([row(backend="arcadedb_graph_server", version="server:26.11.1 (build a3a5d1245/1/main)", build="jvm")]) == set()
    assert AI.post_releases([row(backend="postgres", version="16.1.post1", commit="")]) == set()


def test_the_freeze_names_the_release_and_keeps_every_other_field_and_the_input():
    rows = [row(), post(), row(version="server:26.11.1 (build a3a5d1245/1/main)", backend="arcadedb_graph_server", build="jvm")]
    before = copy.deepcopy(rows)
    out = AI.name_post_wheels(rows)
    assert rows == before                                                        # the raw rows are not touched
    assert [r["engine_version"] for r in out] == [REL, REL, "server:26.11.1 (build a3a5d1245/1/main)"]
    assert out[1]["wheel_label"] == POST and out[1]["wheel_sha256"] == "c" * 64 and out[1]["engine_commit"] == COMMIT
    assert {k: v for k, v in out[1].items() if k != "engine_version"} == {k: v for k, v in rows[1].items() if k != "engine_version"}


def test_the_freeze_keeps_the_post_identity_of_a_row_it_cannot_vouch_for():
    other = [row(), post(commit="fff000999")]
    assert [r["engine_version"] for r in AI.name_post_wheels(other)] == [REL, POST]          # the gates then refuse it
    assert [r["engine_version"] for r in AI.name_post_wheels([post(commit="")])] == [POST]


# ---------------------------------------------------------------- arm_identity.pair_problems
def test_a_post_row_beside_a_release_row_of_one_engine_passes_the_pair_gate():
    rows = [row(), post(), row(build="jvm", backend="arcadedb_graph_embedded"), row(build="jvm", backend="arcadedb_graph_server",
            version="server:26.11.1 (build a3a5d1245/1/main)")]
    assert AI.pair_problems(rows) == []
    assert AI.pair_problems([post(), row(build="jvm")]) == []                    # post on one build, release on the other


def test_the_pair_gate_still_refuses_another_release_or_another_commit():
    bad = AI.pair_problems([row(), post(), row("26.11.2", build="jvm")])
    assert len(bad) == 1 and "engine_version" in bad[0] and "26.11.2" in bad[0]
    bad = AI.pair_problems([row(), post(), row("26.11.2.post1", build="jvm", commit=COMMIT)])                 # a post wheel of another release is that release
    assert len(bad) == 1 and "engine_version" in bad[0]
    bad = AI.pair_problems([row(), post(commit="fff000999"), row(build="jvm")])                               # a post row of another engine commit
    assert any("engine_commit" in b for b in bad) and any("engine_version" in b for b in bad)
    bad = AI.pair_problems([row(build="jvm"), post(commit="")])                                              # a post row that names no commit is not vouched for
    assert any("engine_version" in b for b in bad)
    assert len(AI.pair_problems([row(), row("26.11.2", build="jvm")])) == 1 and AI.pair_problems([row(), row(build="jvm")]) == []   # unchanged


# ---------------------------------------------------------------- export_web._one_version
def _ew():
    pytest.importorskip("numpy")
    pytest.importorskip("pandas")
    import export_web
    return export_web


def test_an_entry_may_pool_a_post_row_and_a_release_row_of_one_engine():
    ew = _ew()
    rs = [row(backend="arcadedb_embedded", build="native"), post(backend="arcadedb_embedded", build="native")]
    assert ew._one_version(rs, "durability/arcadedb_embedded/doc_neworder")["engine_version"] in (REL, POST)


def test_an_entry_still_refuses_another_release_another_commit_and_a_comparator_post():
    ew = _ew()
    for rs in ([row(), row("26.11.2", commit=COMMIT)],                           # another release
               [row(), post(commit="fff000999")],                                # a post row of another engine commit
               [row(), post(commit="")],                                         # a post row that names no commit
               [row(), post(), row("26.11.2.post1")],                            # a post wheel of another release
               [row(backend="postgres", version="16.1", commit=""), row(backend="postgres", version="16.1.post1", commit="")]):   # not ArcadeDB
        with pytest.raises(SystemExit) as e:
            ew._one_version(rs, "x/y/z")
        assert "pools rows that ran on different engine versions" in str(e.value)


# ---------------------------------------------------------------- the whole export on the publish fixture
def _fixture_rows():
    with gzip.open(FIXTURE / "runs.jsonl.gz", "rt") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    for r in rows:        # the fixture is a snapshot build: read it as the release, so a post wheel of it is possible
        if r.get("engine_version") == "26.11.1.dev0":
            r["engine_version"] = REL
    return rows


def _later(ts):
    return (datetime.datetime.fromisoformat(ts) + datetime.timedelta(seconds=1)).isoformat()


def _stage(dest, rows):
    import shutil
    shutil.copytree(FIXTURE, dest)
    (dest / "runs.jsonl.gz").unlink()
    (dest / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return dest


def _export(results):
    env = {k: v for k, v in os.environ.items() if not k.startswith("BENCH_")}
    env.update({"BENCH_RESULTS_DIR": str(results), "BENCH_ENGINE_COMMIT": PIN, "PYTHONHASHSEED": "0"})
    out = []
    for script in ("make_paper_tables.py", "export_web.py"):
        done = subprocess.run([sys.executable, str(HERE / script)], cwd=HERE, env=env, capture_output=True, text=True, timeout=1800)
        out.append(done)
        if done.returncode:
            break
    return out


def test_a_rerun_on_a_post_wheel_leaves_the_page_byte_identical_and_never_names_it(tmp_path):
    """The post rows replace the rep 3 rows of two cells (the relaxed class of l2/sf1 and of the l1tpc oltp cell), with the same figures and a
    later time. The page must be the page of the release rows, byte for byte: nothing names the wheel, no entry or gate refuses the pair
    of versions. On main the export stops in `_one_version` (and would print `26.11.1.post3` if it did not)."""
    pytest.importorskip("numpy")
    pytest.importorskip("pandas")
    base_rows = _fixture_rows()
    redo = []
    for r in base_rows:
        if (r.get("rep") == 3 and r.get("durability_class") in (None, "relaxed") and r.get("engine_version") == REL
                and ((r["lane"], r["backend"]) == ("l2", "arcadedb_graph_embedded") or (r["lane"], r["backend"], r.get("workload")) == ("l1tpc", "arcadedb_embedded", "oltp"))):
            redo.append(dict(r, engine_version=POST, wheel_label=POST, wheel_name="arcadedb-26.11.1.post3-py3-none-manylinux_2_28_x86_64.whl",
                             wheel_sha256="c" * 64, ts_utc=_later(r["ts_utc"])))
    assert len(redo) >= 2
    base = _export(_stage(tmp_path / "base", base_rows))
    assert base[-1].returncode == 0, (base[-1].stderr or base[-1].stdout)[-2000:]
    variant = _export(_stage(tmp_path / "post", base_rows + redo))
    assert variant[-1].returncode == 0, (variant[-1].stderr + variant[-1].stdout)[-2000:]
    page = (tmp_path / "post" / "web_benchmarks.json").read_text()
    assert page == (tmp_path / "base" / "web_benchmarks.json").read_text()
    assert "post3" not in page and ".post" not in page
    freeze = (tmp_path / "post" / "runs_paper.csv").read_text()
    assert POST in freeze and "wheel_label" in freeze                           # the identity stays in the freeze's wheel columns
    assert POST in (tmp_path / "post" / "runs.jsonl").read_text()               # and in the raw rows
