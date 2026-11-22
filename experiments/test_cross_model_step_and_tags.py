"""The cross-model table names its third step and says, per row, how the engine gets to the three models (mmdbbench#47).

- the step is a record update (a document, a table row, or a node's properties), not a document update: the caption says so;
- every adapter declares MODELS (vector, graph, record) in a fixed vocabulary, and a served twin inherits its engine's declaration;
- the exporter puts the declaration on every row of the two cross-model tables as `models`, and on no other table;
- one generated sentence under the table names the rows in each group, from the rows that are on the table;
- the per-engine list in docs/methodology.md is the adapters' declarations, value for value.
Light: no rows and no engine. Run with pytest, or as plain functions from this directory.
"""
import inspect
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("BENCH_RESULTS_DIR", tempfile.mkdtemp(prefix="cross-model-tags-"))
os.environ.setdefault("BENCH_ONLY_LANES", "l2,l3d")   # the exporter refuses to load without the E4 overlay unless the lanes are scoped
import e2_hybrid as E2  # noqa: E402
import export_web as EW  # noqa: E402

HOW = ("built in", "extension (", "separate process (", "separate product (", "none (")
RECORD = ("document", "table row", "node properties")
# The engine name each adapter has in the list of docs/methodology.md.
DOC_ROW = {
    "arcadedb_e2": "ArcadeDB (embedded and server)", "arcadedb_e2_server": "ArcadeDB (embedded and server)",
    "surrealdb_e2": "SurrealDB (embedded and server)", "surrealdb_e2_server": "SurrealDB (embedded and server)",
    "arangodb_e2": "ArangoDB", "mongodb_e2": "MongoDB", "pg_age_e2": "PostgreSQL + pgvector + AGE", "neo4j_e2": "Neo4j",
    "memgraph_e2": "Memgraph", "ladybug_e2": "LadybugDB", "duckdb_e2": "DuckDB", "composed_qdrant_neo4j": "Qdrant + Neo4j",
    "composed_embedded_sqlite_lance_ladybug": "SQLite + LanceDB + LadybugDB",
}


def _entries(*keys):
    return [{"backend": EW.display_name(k), "backend_key": k, "scale": "e2", "metrics": {}} for k in keys]


def test_every_adapter_declares_how_it_gets_to_the_three_models():
    assert set(E2.BACKENDS) == set(DOC_ROW), sorted(set(E2.BACKENDS) ^ set(DOC_ROW))
    for name, cls in E2.BACKENDS.items():
        decl = getattr(cls, "MODELS", None)
        assert isinstance(decl, dict) and sorted(decl) == ["graph", "record", "vector"], (name, decl)
        for k in ("vector", "graph"):
            assert decl[k] == "built in" or (decl[k].startswith(HOW[1:]) and decl[k].endswith(")")), (name, k, decl[k])
        assert decl["record"] in RECORD, (name, decl["record"])
    assert E2.ArcadeE2Server.MODELS == E2.ArcadeE2.MODELS and E2.SurrealServedE2.MODELS == E2.SurrealE2.MODELS
    # what the issue is about: a graph engine passes the third step with node properties, and a composed stack is separate products
    assert E2.BACKENDS["ladybug_e2"].MODELS == {"vector": "extension (vector)", "graph": "built in", "record": "node properties"}
    assert E2.BACKENDS["memgraph_e2"].MODELS["record"] == "node properties"
    assert all(E2.BACKENDS["composed_qdrant_neo4j"].MODELS[k].startswith("separate product (") for k in ("vector", "graph"))


def test_the_caption_names_a_record_update():
    spec = next(v["e2"] for v in vars(EW).values()
                if isinstance(v, dict) and isinstance(v.get("e2"), dict) and "dataset" in v["e2"])
    assert EW.MODEL_STEP == "record update (a document, a table row, or a node's properties)"
    assert EW.MODEL_STEP in spec["dataset"] and "document update" not in spec["dataset"], spec["dataset"]


def test_every_cross_model_row_carries_the_tag_and_no_other_table_does():
    for tid in ("e2", "e2atom"):
        table = {"id": tid, "entries": _entries(*E2.BACKENDS)}
        EW._tag_models(table)
        for e in table["entries"]:
            decl = E2.BACKENDS[e["backend_key"]].MODELS
            assert e["models"] == f"vector: {decl['vector']}; graph: {decl['graph']}; record: {decl['record']}", e
    assert table["entries"][0]["models"] == "vector: built in; graph: built in; record: document", table["entries"][0]
    other = {"id": "l2", "entries": _entries("arcadedb_e2")}
    EW._tag_models(other)
    assert "models" not in other["entries"][0]
    unknown = {"id": "e2", "entries": [{"backend": "x", "backend_key": "not_an_arm"}]}
    EW._tag_models(unknown)
    assert "models" not in unknown["entries"][0]            # an arm that declares nothing gets no tag, never a guessed one
    # and the two functions are called where every table passes
    assert "_tag_models(table)" in inspect.getsource(EW._finish_table)
    assert "_models_note(table)" in inspect.getsource(EW._oct_conditions)


def test_the_sentence_names_the_step_and_groups_the_rows_on_the_table():
    text = EW._models_note({"id": "e2", "entries": _entries(*E2.BACKENDS)})
    assert "record update" in text and "a document, a table row, or a node's properties" in text, text
    n = EW.display_name
    built = f"{n('arangodb_e2')}, {n('arcadedb_e2')}, {n('arcadedb_e2_server')}, {n('surrealdb_e2')}, and {n('surrealdb_e2_server')} have the vector index"
    assert built in text, text
    assert f"{n('duckdb_e2')}, {n('ladybug_e2')}, and {n('pg_age_e2')} reach the vector search, the graph, or both through an extension." in text, text
    assert f"{n('ladybug_e2')}, {n('memgraph_e2')}, and {n('neo4j_e2')} keep the record as the properties of a graph node." in text, text
    assert f"{n('composed_qdrant_neo4j')} and {n('composed_embedded_sqlite_lance_ladybug')} are stacks of separate products." in text, text
    assert f"For {n('mongodb_e2')}, vector search: separate process (mongot); graph: none (the hop is a $lookup join); record: document." in text, text
    assert any(g["text"] == text for g in EW._GENERATED), "the sentence is registered as generated"
    # only the rows that are on the table are named, a single row reads in the singular, and other tables get nothing
    one = EW._models_note({"id": "e2", "entries": _entries("neo4j_e2")})
    assert f"{n('neo4j_e2')} keeps the record as the properties of a graph node." in one and n("arcadedb_e2") not in one, one
    assert EW._models_note({"id": "e2atom", "entries": _entries("neo4j_e2")}) is None
    assert EW._models_note({"id": "e2", "entries": []}) is None


def test_the_methodology_list_is_the_declarations():
    doc = (HERE.parent / "docs" / "methodology.md").read_text()
    assert "## The cross-model transaction" in doc
    for name, cls in E2.BACKENDS.items():
        d = cls.MODELS
        row = f"| {DOC_ROW[name]} | `{d['vector']}` | `{d['graph']}` | `{d['record']}` |"
        assert row in doc, row
    spec = (HERE / "PAGE-SPEC.md").read_text()
    assert "`export_web.MODEL_STEP`" in spec and EW.MODEL_STEP in spec and "`models`" in spec


if __name__ == "__main__":
    test_every_adapter_declares_how_it_gets_to_the_three_models()
    test_the_caption_names_a_record_update()
    test_every_cross_model_row_carries_the_tag_and_no_other_table_does()
    test_the_sentence_names_the_step_and_groups_the_rows_on_the_table()
    test_the_methodology_list_is_the_declarations()
    print("ok")
