"""The cell command of the pilot of mmdbbench#164 (pilot164/study/cell_run.py), run through the pilot's own runner with a stand-in for runner.py and for
docker: no container, no engine, and nothing timed. The sysfs readings are the runner's test hooks, and the cores are the first ones of this machine."""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PILOT = os.path.join(HERE, "pilot164")
CELL = "l2_arcadedb_graph_embedded_oltp_sf1"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cells = load("pilot_cells_under_test", os.path.join(PILOT, "study", "cell_run.py"))
plan = load("pilot_plan_under_test", os.path.join(PILOT, "plan.py"))
analyze = load("pilot_analyze_under_test", os.path.join(PILOT, "analyze.py"))
CFG = cells.load_config()

FAKE_RUNNER = r"""
import json, os, sys, time
a = dict(zip(sys.argv[1::2], sys.argv[2::2]))
os.makedirs("results", exist_ok=True)
cpus = os.environ["BENCH_CPUSET"]
row = {"backend": a["--backends"], "scale": a["--scale"], "rep": int(a["--only-reps"]), "rc": 0, "durability_class": a.get("--durability", "relaxed"),
       "cpuset": os.environ.get("FAKE_CPUSET", cpus), "engine_version": "26.11.1", "build_s": 1.0, "oltp_total_s": 2.0}
with open(os.path.join("results", a["--results-file"]), "a") as fh:
    fh.write(json.dumps(row) + "\n")
time.sleep(4)  # long enough that a start a few tens of milliseconds apart stays inside the 95 percent coverage rule
print("  [1/1] l2_x_sf1_r1 %s (%s) -> %s" % (os.environ.get("FAKE_SECONDS", "12.5s"), cpus, os.environ.get("FAKE_STATUS", "ok")))
"""
FAKE_DOCKER = r"""
import os, sys
name = sys.argv[-1]
if name == os.environ.get("FAKE_ABSENT"):
    sys.exit(1)
print(os.environ["FAKE_SERVER_ID"] if name == os.environ["FAKE_SERVER_NAME"] else "sha256:id-of-" + name)
"""


@pytest.fixture
def study(tmp_path, monkeypatch):
    """A study folder as build_cell_study.sh lays it out, with the pins pointed at a wheel in tmp_path and the two stand-ins."""
    folder = tmp_path / "pilot164-c0"
    folder.mkdir()
    for name in ("pilot_run.py", "probes.py", "run_ab.sh", "cell_run.py"):
        shutil.copy(os.path.join(PILOT, "study", name), folder)
    wheel = tmp_path / "wheels" / CFG["wheel_name"]
    wheel.parent.mkdir()
    wheel.write_bytes(b"not a wheel")
    cfg = dict(CFG, wheel_dirs=[str(wheel.parent)], wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest())
    (folder / "cell.json").write_text(json.dumps(cfg))
    (tmp_path / "fake_runner.py").write_text(FAKE_RUNNER)
    (tmp_path / "fake_docker.py").write_text(FAKE_DOCKER)
    sysfs = tmp_path / "sys"
    for cpu in range(os.cpu_count()):
        d = sysfs / f"cpu{cpu}" / "thermal_throttle"
        d.mkdir(parents=True)
        for name in ("core_throttle_total_time_ms", "package_throttle_total_time_ms"):
            (d / name).write_text("0\n")
    (tmp_path / "temp").write_text("52000\n")
    env = {"PILOT_CELL_RUNNER": f"{sys.executable} {tmp_path / 'fake_runner.py'}", "PILOT_DOCKER": f"{sys.executable} {tmp_path / 'fake_docker.py'}",
           "FAKE_SERVER_NAME": cfg["server_image"], "FAKE_SERVER_ID": cfg["server_image_id"], "PILOT_TEMP_FILE": str(tmp_path / "temp"),
           "PILOT_THROTTLE_ROOT": str(sysfs), "PILOT_GATE_C": "500"}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return folder


def facts_of(study, data_leg=False):
    return cells.preflight(data_leg, config=str(study / "cell.json"), lock=str(study.parent / "lock.json"))


def test_every_pick_has_a_cell():
    picks = json.load(open(os.path.join(PILOT, "picks.json")))
    chosen = [c for v in picks["picks"].values() for c in v]
    assert sorted(c["cell"] for c in chosen) == sorted(cells.CELLS)
    for c in chosen:
        backend, durability = cells.CELLS[c["cell"]]
        assert c["cell"].startswith("l2_" + backend)
        assert (durability == "strict") == c["cell"].endswith("_dstrict")
        assert c["arm"].startswith("jvm-")  # the one wheel and the one server image of cell.json are the JVM build


def test_runner_flags_are_the_landed_ones():
    argv = cells.runner_argv(CFG, CELL + "_dstrict", "x.jsonl")
    assert argv == ["--lanes", "l2", "--scale", "sf1", "--backends", "arcadedb_graph_embedded", "--workloads", "oltp", "--tier", "paper", "--workers", "1",
                    "--timeout", "3600", "--durability", "strict", "--only-reps", "1", "--reps", "3", "--results-file", "x.jsonl"]
    assert "--durability" not in cells.runner_argv(CFG, CELL, "x.jsonl")


def test_cell_figure_and_refusals(study, tmp_path, monkeypatch):
    facts = facts_of(study)
    gate = {"ok": True, "waited": 0, "temp": 52.0}
    res = cells.run(facts, CELL, "0", str(tmp_path / "out"), "s1_unit", gate)
    assert res["value"] == 12.5 and res["extra"]["cell_oltp_total_s"] == 2.0
    with pytest.raises(cells.CellError, match="never appends"):
        cells.run(facts, CELL, "0", str(tmp_path / "out"), "s1_unit", gate)
    monkeypatch.setenv("FAKE_CPUSET", "7")
    with pytest.raises(cells.CellError, match="ran on cores 7"):
        cells.run(facts, CELL, "0", str(tmp_path / "out"), "s1_unit2", gate)
    monkeypatch.delenv("FAKE_CPUSET")
    monkeypatch.setenv("FAKE_STATUS", "timeout_after_3600s")
    with pytest.raises(cells.CellError, match="expected one cell line ending in ok"):
        cells.run(facts, CELL, "0", str(tmp_path / "out"), "s1_unit3", gate)


def test_pins(study, monkeypatch):
    with pytest.raises(cells.CellError, match="the smoke leg C0 runs first"):
        facts_of(study, data_leg=True)
    monkeypatch.setenv("FAKE_ABSENT", CFG["embedded_image"])
    with pytest.raises(cells.CellError, match="is absent"):
        facts_of(study)
    assert not (study.parent / "lock.json").exists()
    monkeypatch.delenv("FAKE_ABSENT")
    facts_of(study)  # the smoke writes the lock
    facts_of(study, data_leg=True)
    monkeypatch.setenv("FAKE_SERVER_ID", "sha256:another")
    with pytest.raises(cells.CellError, match="the landed rows name"):
        facts_of(study, data_leg=True)


def start(study, out, lane, cpus, cls):
    env = dict(os.environ, OUT=out, HUMEM_HOST_LANE=lane, HUMEM_HOST_CPUS=cpus)
    env.pop("HUMEM_HOST_CELL_CLASS", None)
    if cls:
        env["HUMEM_HOST_CELL_CLASS"] = cls
    return subprocess.Popen([sys.executable, "-I", str(study / "pilot_run.py")], cwd=study, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def rows(study, out):
    return [json.loads(x) for x in (study / out / "rows.jsonl").read_text().splitlines()]


@pytest.mark.skipif(not sys.platform.startswith("linux") or (os.cpu_count() or 1) < 3, reason="the runner pins three lanes to three cores")
def test_smoke_leg_runs_through_the_pilot_runner(study):
    order = plan.build("C0", 20261124, dict(plan.DEFAULT_PROVEN), json.load(open(os.path.join(PILOT, "picks.json"))), "x")
    plan.dump(order, str(study / "order.json"))
    solo = start(study, "s1-solo", "solo", "0-2", None)
    out, err = solo.communicate(timeout=120)
    assert solo.returncode == 0, out + err
    got = rows(study, "s1-solo")
    assert [r["status"] for r in got] == ["ok", "ok"] and all(r["figure"] == 12.5 and r["unit_label"] == "s" and r["test_hooks"] for r in got)
    lanes = {c["lane"]: c for c in order["claims"] if c["stage"] == "s2"}
    cpus = {"compare1": "0", "compare2": "1", "compare3": "2"}
    procs = {lane: start(study, c["out"], lane, cpus[lane], c["cell_class"]) for lane, c in lanes.items()}
    for lane, p in procs.items():
        out, err = p.communicate(timeout=240)
        assert p.returncode == 0, f"{lane}: {out}{err}"
    all_rows = [r for lane in lanes for r in rows(study, lanes[lane]["out"])]
    seen = [(r["unit"], r["lane"], r["role"], r["status"], r.get("reason")) for r in all_rows]
    # a busy neighbour is stopped when the target is done, so its row says partial; every other row says ok
    assert all(r["status"] == ("partial" if r["role"] == "busy" else "ok") for r in all_rows), seen
    targets = [r for r in all_rows if r["role"] == "target"]
    assert len(targets) == 4 and all(r["figure"] == 12.5 for r in targets), seen
    assert sum(r["role"] == "busy" for r in all_rows) == 2, seen
    # the registered analysis counts every target run, the neighbour's coverage of the whole cell included
    by_unit = {(r["unit"], r["lane"]): r for r in all_rows}
    for u in (u for u in order["units"] if u["stage"] == "s2"):
        valid, why = analyze.unit_validity(u, by_unit, order["data"])
        assert valid, (u["id"], why, seen)
