"""export_web.DENSE_PRECISION must hold every dense arm that has rows (the exporter raises on a missing one), and each entry must match the DDL
its adapter issues, not the row's `quantization` field (humemai/mmdbbench#63).

Light: reads two source files (the map is read from the source, so the test needs no results directory). Run with pytest, or as plain
functions from this directory."""
import ast
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _precision():
    tree = ast.parse((HERE / "export_web.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "DENSE_PRECISION" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("DENSE_PRECISION not found in export_web.py")


def _class_source(name):
    text = (HERE / "l3d_dense.py").read_text(encoding="utf-8")
    m = re.search(rf"^class {name}\(Base\):\n(.*?)(?=^class |^def )", text, re.S | re.M)
    assert m, f"{name} not found in l3d_dense.py"
    return m.group(1)


def test_redis_dense_has_an_entry_and_the_adapter_creates_a_float32_index():
    assert _precision().get("redis_dense") == "fp32"
    src = _class_source("RedisDense")
    assert re.search(r'"FT\.CREATE".*"VECTOR", "HNSW".*"TYPE", "FLOAT32"', src, re.S), "the entry says fp32 because the index is FLOAT32"


def test_every_dense_arm_of_the_n3_data_has_an_entry():
    have = _precision()
    for arm in ("arangodb_dense", "arcadedb_dense_embedded", "arcadedb_dense_server", "duckdb_vss_dense", "ladybug_dense", "mongodb_dense",
                "pgvector_dense", "qdrant_dense", "redis_dense", "sqlite_vec_dense", "surrealdb_dense", "surrealdb_dense_server", "cratedb_dense"):
        assert arm in have, arm
