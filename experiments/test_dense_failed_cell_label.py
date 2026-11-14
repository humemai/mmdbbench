"""The outcome row of a dense cell that failed or was censored carries the arm label of the overlay twin (humemai/mmdbbench#89).

`ArcadeDB (server, native build)` (a failed cell) and `ArcadeDB (server, fp32, JVM build)` (its overlay twin) were two arms to the page's build-pair
check, so the l3d landing was refused with ONEBUILD. DENSE_10M_ARMS holds the label with the precision; the outcome row builder of export_web takes it
from there for the dense lane. Source-level and light (the module is read, not imported). Run with pytest, or as plain functions."""
import ast
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = (HERE / "export_web.py").read_text(encoding="utf-8")


def _outcome_dict_source():
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and k.value == "outcome":
                    return ast.get_source_segment(SRC, node)
    raise AssertionError("no outcome row dict in export_web.py")


def test_the_dense_helper_returns_the_arm_table_label():
    tree = ast.parse(SRC)
    fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "_dense_arm_label" in fns, "export_web._dense_arm_label is missing"
    ns = {}
    arms = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "DENSE_10M_ARMS" for t in n.targets))
    exec(compile(ast.Module(body=[fns["_dense_arm_label"]], type_ignores=[]), "export_web.py", "exec"), {"DENSE_10M_ARMS": arms}, ns)
    f = ns["_dense_arm_label"]
    assert f("arcadedb_dense_server") == "ArcadeDB (server, fp32)" and f("arcadedb_dense_embedded") == "ArcadeDB (embedded, fp32)"
    assert f("qdrant_dense") == "Qdrant (fp32)" and f("no_such_dense_arm") is None


def test_the_outcome_row_of_the_dense_lane_takes_its_label_from_the_arm_table():
    seg = _outcome_dict_source()
    assert "_dense_arm_label(" in seg, "the outcome row builder does not use the arm table's label for the dense lane"
