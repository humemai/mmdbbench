#!/usr/bin/env python3
"""cell_run.py: the cell command of the pilot of mmdbbench#164, the target of a unit in legs L5 and L6 (and in the smoke leg C0). Stdlib only.

One unit is one cell of picks.json at its landed settings on the 26.11.1 pin: one `runner.py` call from a frozen copy of experiments/ (repo/experiments of the
study folder), with the flags of the landed stage (--tier paper --workers 1 --timeout --only-reps 1 --reps 3, --durability strict for the strict cells) on the
cores of the lane (BENCH_CPUSET). The figure is the cell's wall time in seconds, read from the runner's own line `[1/1] <run id> <secs>s (<cpuset>) -> ok`,
the same figure that picks.json was chosen by. The row the runner wrote is checked (backend, repetition, durability, cores, engine, no error) before the
figure counts.

Pins (cell.json of the study folder): the engine commit, the JVM wheel (held to its sha256), the server image (held to the image id of the landed rows) and the
names of the two other images. The landed rows name no image id for those two, so the smoke leg writes their ids into the lock file beside the study folders
(../pilot164-cells-images.lock.json) and every data claim refuses to start unless each id is the same.

PILOT_CELL_RUNNER (a command that stands in for runner.py) and PILOT_DOCKER (a command that stands in for docker) are test hooks; rows made with them say so.
"""
import hashlib
import json
import os
import re
import shlex
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
EXPERIMENTS = os.path.join(HERE, "repo", "experiments")
CONFIG = os.path.join(HERE, "cell.json")
CELLS = {  # the four picks: cell -> (backend of the runner, durability class)
    "l2_arcadedb_graph_embedded_oltp_sf1": ("arcadedb_graph_embedded", "relaxed"),
    "l2_arcadedb_graph_server_oltp_sf1": ("arcadedb_graph_server", "relaxed"),
    "l2_arcadedb_graph_embedded_oltp_sf1_dstrict": ("arcadedb_graph_embedded", "strict"),
    "l2_arcadedb_graph_server_oltp_sf1_dstrict": ("arcadedb_graph_server", "strict"),
}
LINE = re.compile(r"\[\d+/\d+\] (\S+) ([0-9]+\.[0-9]+)s \(([0-9,\-]+)\) -> (.*)$", re.M)


class CellError(Exception):
    """The cell cannot run, or what it wrote does not count."""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_config(path=CONFIG):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_hooks():
    return any(os.environ.get(k) for k in ("PILOT_CELL_RUNNER", "PILOT_DOCKER"))


def image_id(name):
    docker = shlex.split(os.environ.get("PILOT_DOCKER") or "docker")
    p = subprocess.run(docker + ["image", "inspect", "--format", "{{.Id}}", name], capture_output=True, text=True, timeout=60)
    return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else None


def find_wheel(cfg):
    for d in cfg["wheel_dirs"]:
        path = os.path.join(os.path.expanduser(d), cfg["wheel_name"])
        if os.path.isfile(path) and sha256_file(path) == cfg["wheel_sha256"]:
            return path
    return None


def lock_path():
    return os.path.join(os.path.dirname(HERE), "pilot164-cells-images.lock.json")


def preflight(data_leg, config=CONFIG, lock=None):
    """The pins of cell.json against this host. Returns the facts; raises CellError with every problem. A data leg needs the lock file the smoke wrote."""
    cfg = load_config(config)
    lock = lock or lock_path()
    problems = []
    if not (os.environ.get("PILOT_CELL_RUNNER") or os.path.isfile(os.path.join(EXPERIMENTS, "runner.py"))):
        problems.append("the study folder has no repo/experiments/runner.py")
    wheel = find_wheel(cfg)
    if wheel is None:
        problems.append(f"wheel {cfg['wheel_name']} with the pinned sha256 is in none of {cfg['wheel_dirs']}")
    ids = {name: image_id(name) for name in (cfg["server_image"], cfg["embedded_image"], cfg["client_image"])}
    for name, got in ids.items():
        if got is None:
            problems.append(f"image {name} is absent")
    if ids[cfg["server_image"]] not in (None, cfg["server_image_id"]):
        problems.append(f"image {cfg['server_image']} is {ids[cfg['server_image']]}, the landed rows name {cfg['server_image_id']}")
    if os.path.isfile(lock):
        with open(lock, encoding="utf-8") as fh:
            locked = json.load(fh)
        for name, got in ids.items():
            if got is not None and locked.get(name) != got:
                problems.append(f"image {name} is {got}, the lock file of the smoke says {locked.get(name)}")
    elif data_leg:
        problems.append(f"no lock file {lock}: the smoke leg C0 runs first and writes it")
    if problems:
        raise CellError("; ".join(problems))
    if not os.path.isfile(lock):
        with open(lock + ".new", "w", encoding="utf-8") as fh:
            json.dump(ids, fh, indent=1, sort_keys=True)
        os.replace(lock + ".new", lock)
    return {"config": cfg, "wheel": wheel, "images": ids}


def runner_argv(cfg, cell, results_file):
    backend, durability = CELLS[cell]
    argv = ["--lanes", "l2", "--scale", "sf1", "--backends", backend, "--workloads", "oltp", "--tier", "paper", "--workers", "1", "--timeout", str(cfg["timeout_s"])]
    if durability == "strict":
        argv += ["--durability", "strict"]
    return argv + ["--only-reps", "1", "--reps", "3", "--results-file", results_file]


def runner_env(cfg, wheel, cpus_text, gate):
    env = {k: v for k, v in os.environ.items() if not k.startswith("ARCADEDB_") and k != "BENCH_SERVER_BUILD"}  # the pins come from cell.json alone
    env.update({"BENCH_INSTRUMENT": cfg["instrument"], "BENCH_DATA": os.path.expanduser(cfg["bench_data"]), "BENCH_HOST": cfg["bench_host"], "BENCH_CPUSET": cpus_text,
                "BENCH_GRAPH_SOURCE": "ldbc", "BENCH_ALLOW_DEV": "0", "ARCADEDB_WHEEL": wheel, "ARCADEDB_SERVER_IMAGE": cfg["server_image"],
                "ARCADEDB_ENGINE_COMMIT": cfg["engine_commit"], "BENCH_PRECELL_GATE_OK": "true" if gate["ok"] else "false",
                "BENCH_PRECELL_GATE_WAIT_S": str(int(gate["waited"])), "BENCH_PRECELL_GATE_MAX_C": str(int(gate.get("max_c", 70)))})
    if gate.get("temp") is not None:
        env["BENCH_PRECELL_GATE_TEMP_C"] = f"{gate['temp']:.1f}"
    return env


def check_row(cfg, cell, cpus_text, rows):
    """Why the row of the runner does not count; (row, []) when it does."""
    backend, durability = CELLS[cell]
    mine = [r for r in rows if r.get("backend") == backend and r.get("scale") == "sf1" and r.get("rep") == 1]
    if len(mine) != 1:
        return None, [f"{len(mine)} rows of {backend} sf1 rep 1 in the results file, expected 1"]
    row, why = mine[0], []
    if row.get("error") or row.get("rc") != 0:
        why.append(f"the row has rc {row.get('rc')} and error {str(row.get('error'))[:80]}")
    if row.get("durability_class") != durability:
        why.append(f"durability {row.get('durability_class')}, expected {durability}")
    if str(row.get("cpuset")) != cpus_text:
        why.append(f"the containers ran on cores {row.get('cpuset')}, the lane is {cpus_text}")
    if cfg["engine_version"] not in str(row.get("engine_version")):
        why.append(f"engine {row.get('engine_version')}, expected {cfg['engine_version']}")
    return row, why


def run(facts, cell, cpus_text, outdir, label, gate):
    """One run of the cell. Returns {"value": wall seconds, "extra": {...}}; raises CellError when it does not count."""
    cfg = facts["config"]
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", label)
    results_file = f"runs_pilot164_{safe}.jsonl"
    fake = os.environ.get("PILOT_CELL_RUNNER")
    command = (shlex.split(fake) if fake else cfg["python"] + ["runner.py"]) + runner_argv(cfg, cell, results_file)
    cwd = outdir if fake else EXPERIMENTS
    results = os.path.join(cwd, "results", results_file)
    if os.path.exists(results):
        raise CellError(f"{results} exists: a unit never appends to the rows of an earlier run")
    os.makedirs(os.path.join(outdir, "logs"), exist_ok=True)
    log = os.path.join(outdir, "logs", safe + ".log")
    with open(log, "w", encoding="utf-8") as fh:
        fh.write("$ " + " ".join(shlex.quote(x) for x in command) + "\n")
        fh.flush()
        try:
            rc = subprocess.run(command, cwd=cwd, env=runner_env(cfg, facts["wheel"], cpus_text, gate), stdout=fh, stderr=subprocess.STDOUT, timeout=cfg["timeout_s"] + 600).returncode
        except subprocess.TimeoutExpired as exc:
            raise CellError(f"the runner did not end within {cfg['timeout_s'] + 600} s") from exc
    with open(log, encoding="utf-8", errors="replace") as fh:
        lines = LINE.findall(fh.read())
    if rc != 0:
        raise CellError(f"runner exit {rc}, see {log}")
    if len(lines) != 1 or lines[0][3].strip() != "ok":
        raise CellError(f"expected one cell line ending in ok, found {[x[3] for x in lines]}, see {log}")
    with open(results, encoding="utf-8") as fh:
        rows = [json.loads(x) for x in fh if x.strip()]
    row, why = check_row(cfg, cell, cpus_text, rows)
    if why:
        raise CellError("; ".join(why))
    keep = ("run_id", "engine_version", "engine_commit", "durability_class", "cpuset", "build_s", "oltp_total_s", "server_image", "heap", "mem_cap",
            "host_throttle_total_ms_start", "host_throttle_total_ms_end")
    extra = {"cell_" + k: row[k] for k in keep if k in row}
    extra.update({"cell_results_file": results_file, "cell_results_sha256": sha256_file(results), "cell_images": facts["images"]})
    return {"value": float(lines[0][1]), "extra": extra}
