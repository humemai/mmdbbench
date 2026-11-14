"""export_web.DENSE_10M_ARMS holds every arm of the dense lane roster that the runner writes an overlay for (humemai/mmdbbench#79).

An arm with overlay rows and no entry here is dropped from the page without a message (redis_dense in the n=3 landing). The three lists are kept by hand,
so this reads them all: runner.LANES['l3d'] (the roster), runner.MP_LABELS (backend -> overlay label) and export_web.DENSE_10M_ARMS and DENSE_PRECISION
(read from the source, so no results directory is needed). Light. Run with pytest, or as plain functions from this directory."""
import ast
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("BENCH_ENGINE_COMMIT", "abc123def")
import runner  # noqa: E402


def _literal(name):
    tree = ast.parse((HERE / "export_web.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in export_web.py")


def test_every_arm_of_the_dense_roster_has_an_entry_in_the_page_arm_table():
    arms = {a[0] for a in _literal("DENSE_10M_ARMS")}
    missing = [(b, runner.MP_LABELS[b]) for b in runner.LANES["l3d"][1] if b in runner.MP_LABELS and runner.MP_LABELS[b] not in arms]
    assert not missing, f"arms of the l3d roster with an overlay label and no DENSE_10M_ARMS entry: {missing}"


def test_every_arm_table_entry_names_a_backend_with_a_precision_and_the_runner_label():
    prec = _literal("DENSE_PRECISION")
    for arm, backend, label, ours in _literal("DENSE_10M_ARMS"):
        assert backend in prec, (arm, backend)
        assert runner.MP_LABELS.get(backend) == arm or arm in runner.MP_LABELS.values(), (arm, backend)
        assert isinstance(ours, bool) and label.endswith(")"), label


def test_the_two_arms_the_n3_landing_dropped_are_there():
    arms = {a[0]: a for a in _literal("DENSE_10M_ARMS")}
    assert arms["redis"][1] == "redis_dense" and arms["redis"][2] == "Redis (fp32)"
    assert arms["cratedb"][1] == "cratedb_dense" and arms["cratedb"][2] == "CrateDB (fp32)"
