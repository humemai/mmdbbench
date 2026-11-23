"""The `addHierarchy` stamp of the embedded ArcadeDB dense arm, on either wheel (humemai/mmdbbench#31, FAIRNESS F15).

F15 wants every embedded dense row to say whether its LSM_VECTOR index was built with `addHierarchy`. The harness used to ask the Java
schema object, which the native wheel does not have, so six native deep10m rows carried no stamp. The stamp now comes from the first of
three sources that answers, and the row's `arcadedb_add_hierarchy_source` names it:

  1. `schema:index`  `metadata.addHierarchy` of `SELECT FROM schema:index:<name>` (ArcadeData/arcadedb#13097, either wheel)
  2. `java-schema`   the Java schema object (JVM wheel only)
  3. `schema.json`   the database directory's schema file, read after the cell's close

Light and pure: fakes for the database and the schema object, a temporary directory for schema.json, no engine and no wheel.
"""
import io
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bench_common as BC  # noqa: E402
import override_registry as OV  # noqa: E402

INDEX = "Article[embedding]"
STATEMENT = "SELECT FROM schema:index:`Article[embedding]`"


class NotOnNativeYet(Exception):
    """What the native wheel raises for a Java-object call."""


class _Json:
    def __init__(self, text):
        self.text = text

    def toString(self):
        return self.text


class _Bucket:
    def __init__(self, value):
        self.value = value

    def toJSON(self):
        return _Json(json.dumps({"addHierarchy": self.value, "dimensions": 128}))


class _TypeIndex:
    def __init__(self, value):
        self.value = value

    def getIndexesOnBuckets(self):
        return [_Bucket(self.value)]


class FakeSchema:
    """The Java schema object: answers on the JVM wheel, raises NotOnNativeYet on the native one. `calls` says whether it was asked."""

    def __init__(self, java_value=None, native=False):
        self.java_value, self.native, self.calls = java_value, native, []

    def get_index_by_name(self, name):
        self.calls.append(name)
        if self.native:
            raise NotOnNativeYet("the Java schema object is not on the native wheel")
        return _TypeIndex(self.java_value)


class FakeDb:
    def __init__(self, rows=(), java_value=None, native=False, query_error=None):
        self.schema = FakeSchema(java_value, native)
        self.rows, self.query_error, self.statements = list(rows), query_error, []

    def sql(self, statement):
        self.statements.append(statement)
        if self.query_error:
            raise self.query_error
        return self.rows

    def query(self, lang, statement):
        rows = self.sql(statement)

        class _Rs:
            def to_list(self_inner):
                return rows
        return _Rs()


def with_metadata(value):
    """The rows an engine with ArcadeData/arcadedb#13097 answers: the detail of one index, a `metadata` map among its keys."""
    return [{"name": INDEX, "indexType": "LSM_VECTOR", "metadata": {"dimensions": 128, "addHierarchy": value, "similarity": "EUCLIDEAN"}}]


WITHOUT_METADATA = [{"name": INDEX, "indexType": "LSM_VECTOR", "typeName": "Article", "properties": ["embedding"]}]


def write_schema(directory, value, buckets=1, type_name="Article", **entry):
    """A schema.json as the engine writes it (26.10.2 and 26.11.1): one entry per bucket under `types.<type>.indexes`, the
    vector index's settings at the top of the entry, and an unrelated index beside it."""
    indexes = {f"{type_name}_{i}_3422547696028{i}": dict({
        "type": "LSM_VECTOR", "bucket": f"{type_name}_{i}", "typeName": type_name, "properties": ["embedding"], "dimensions": 128,
        "similarityFunction": "EUCLIDEAN", "maxConnections": 32, "beamWidth": 100, "storeVectorsInGraph": False,
        "addHierarchy": value, "buildState": "READY"}, **entry) for i in range(buckets)}
    indexes[f"{type_name}_0_1"] = {"type": "LSM_TREE", "bucket": f"{type_name}_0", "typeName": type_name, "properties": ["vid"],
                                   "unique": True}
    doc = {"schemaVersion": 5, "dbmsVersion": "26.11.1", "types": {type_name: {"type": "v", "indexes": indexes}}}
    (Path(directory) / "schema.json").write_text(json.dumps(doc))


def stamp(value, source):
    return {"arcadedb_add_hierarchy": value, "arcadedb_add_hierarchy_source": source}


# ---------------------------------------------------------------------------
# source 1: the SQL statement, on either wheel

@pytest.mark.parametrize("wheel", ["native", "jvm"])
@pytest.mark.parametrize("value", [True, False])
def test_source_one_reads_the_metadata_map_and_names_itself(wheel, value):
    """The setting in force comes from `metadata.addHierarchy`, for `true` and for `false`; the Java object is not asked."""
    db = FakeDb(rows=with_metadata(value), java_value=not value, native=(wheel == "native"))
    got, tried = BC.arcadedb_hierarchy_live(db, INDEX, db.sql, wheel)
    assert got == stamp(value, "schema:index") and tried == []
    assert db.statements == [STATEMENT]
    assert db.schema.calls == [], "source 1 answered, so the Java schema object has nothing to add"


def test_source_one_beats_the_java_object_when_they_disagree():
    db = FakeDb(rows=with_metadata(True), java_value=False)
    assert BC.arcadedb_hierarchy_live(db, INDEX, db.sql, "jvm")[0] == stamp(True, "schema:index")


@pytest.mark.parametrize("rows,why", [
    (WITHOUT_METADATA, "no `metadata` map"),
    ([], "no row"),
    ([{"name": INDEX, "metadata": {"dimensions": 128}}], "no `addHierarchy`"),
    ([{"name": INDEX, "metadata": {"addHierarchy": "maybe"}}], "not a boolean"),
    ([{"name": INDEX, "metadata": "not json"}], "not JSON"),
])
def test_source_one_gives_way_when_the_engine_does_not_report_the_setting(rows, why):
    got, tried = BC.arcadedb_hierarchy_live(FakeDb(rows=rows), INDEX, lambda sql: rows, "native")
    assert got is None and tried[0].startswith("schema:index: ") and why in tried[0], tried


def test_source_one_reads_a_json_text_and_never_a_truthy_string():
    """A map that arrives as JSON text is read; the string "false" is False, not the truthy string."""
    for text, want in ((json.dumps({"addHierarchy": False}), False), (json.dumps({"addHierarchy": "true"}), True),
                       ({"addHierarchy": "false"}, False)):
        got, _ = BC.arcadedb_hierarchy_live(None, INDEX, lambda sql, t=text: [{"metadata": t}], "native")
        assert got == stamp(want, "schema:index"), text


# ---------------------------------------------------------------------------
# source 2: the Java schema object, on the JVM wheel only

@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("sql", ["no metadata", "statement fails"])
def test_source_two_is_the_java_object_on_the_jvm_wheel(value, sql):
    db = FakeDb(rows=WITHOUT_METADATA, java_value=value,
                query_error=RuntimeError("no such schema entry") if sql == "statement fails" else None)
    got, tried = BC.arcadedb_hierarchy_live(db, INDEX, db.sql, "jvm")
    assert got == stamp(value, "java-schema")
    assert len(tried) == 1 and tried[0].startswith("schema:index: "), tried
    assert db.schema.calls == [INDEX]


def test_source_two_is_never_asked_on_the_native_wheel_and_the_reason_says_why():
    db = FakeDb(rows=WITHOUT_METADATA, native=True)
    got, tried = BC.arcadedb_hierarchy_live(db, INDEX, db.sql, "native")
    assert got is None and db.schema.calls == []
    assert [t.split(":")[0] for t in tried] == ["schema:index", "java-schema"] and "NotOnNativeYet" in tried[1]


def test_a_failing_java_read_is_a_reason_not_an_empty_stamp():
    """A JVM wheel whose Java read raises has no stamp from the live sources; schema.json is the next one."""
    db = FakeDb(rows=WITHOUT_METADATA, native=True)          # raises on the call, whatever the wheel label says
    got, tried = BC.arcadedb_hierarchy_live(db, INDEX, db.sql, "jvm")
    assert got is None and tried[-1].startswith("java-schema: NotOnNativeYet")


# ---------------------------------------------------------------------------
# source 3: schema.json of the closed database

@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("buckets", [1, 3])
def test_source_three_reads_schema_json_for_true_and_false(tmp_path, value, buckets):
    write_schema(tmp_path, value, buckets=buckets)
    assert BC.arcadedb_hierarchy_closed(str(tmp_path), INDEX, ["schema:index: x"]) == stamp(value, "schema.json")
    assert BC.arcadedb_hierarchy_after_close(str(tmp_path), INDEX, []) == stamp(value, "schema.json")


def test_schema_json_reads_the_string_false_as_false(tmp_path):
    write_schema(tmp_path, "false")
    assert BC.hierarchy_from_schema_json(str(tmp_path), INDEX) is False


def _schema_failures():
    return [
        ("missing file", lambda d: None, "cannot read"),
        ("not json", lambda d: (Path(d) / "schema.json").write_text("{not json"), "cannot read"),
        ("another type", lambda d: write_schema(d, True, type_name="Other"), "lists no LSM_VECTOR index on Article(embedding)"),
        ("no setting", lambda d: (write_schema(d, True), _drop_key(d)), "has no `addHierarchy`"),
        ("not a boolean", lambda d: write_schema(d, "maybe"), "not a boolean"),
        ("buckets disagree", lambda d: _disagree(d), "disagree"),
    ]


def _drop_key(d):
    p = Path(d) / "schema.json"
    doc = json.loads(p.read_text())
    for ix in doc["types"]["Article"]["indexes"].values():
        ix.pop("addHierarchy", None)
    p.write_text(json.dumps(doc))


def _disagree(d):
    write_schema(d, True, buckets=2)
    p = Path(d) / "schema.json"
    doc = json.loads(p.read_text())
    first = sorted(k for k, v in doc["types"]["Article"]["indexes"].items() if v["type"] == "LSM_VECTOR")[0]
    doc["types"]["Article"]["indexes"][first]["addHierarchy"] = False
    p.write_text(json.dumps(doc))


@pytest.mark.parametrize("label,make,why", _schema_failures(), ids=[c[0] for c in _schema_failures()])
def test_source_three_fails_loudly_and_names_the_problem(tmp_path, label, make, why):
    make(tmp_path)
    tried = ["schema:index: the row has no `metadata` map (the engine predates ArcadeData/arcadedb#13097)",
             "java-schema: not on the native wheel (the Java schema object raises NotOnNativeYet there)"]
    with pytest.raises(BC.HierarchyStampError) as e:
        BC.arcadedb_hierarchy_closed(str(tmp_path), INDEX, tried)
    msg = str(e.value)
    # every source is in the message with its reason, and so is the index and the consequence for the row
    assert INDEX in msg and "schema:index: " in msg and "java-schema: " in msg and "schema.json: " in msg, msg
    assert why in msg and "F15" in msg and str(tmp_path) in msg, msg


def test_a_cell_no_source_can_answer_records_the_error_and_never_an_empty_stamp(tmp_path):
    """The lane's call after close: no stamp keys at all, the message on the row, and the message printed. The cell's row is kept."""
    err = io.StringIO()
    got = BC.arcadedb_hierarchy_after_close(str(tmp_path), INDEX, ["schema:index: no row", "java-schema: not on the native wheel"], err=err)
    assert set(got) == {"arcadedb_readback_error"}
    assert "arcadedb_add_hierarchy" not in got and "arcadedb_add_hierarchy_source" not in got
    assert all(s in got["arcadedb_readback_error"] for s in ("schema:index", "java-schema", "schema.json", INDEX))
    assert err.getvalue().startswith("HIERARCHY STAMP MISSING: ") and got["arcadedb_readback_error"] in err.getvalue()


def test_the_three_sources_are_the_ones_the_docs_name():
    assert BC.HIERARCHY_SOURCES == ("schema:index", "java-schema", "schema.json")
    text = (HERE / "FAIRNESS.md").read_text() + (HERE / "PROTOCOL.md").read_text()
    for s in BC.HIERARCHY_SOURCES:
        assert f"`{s}`" in text, s


def test_the_index_name_and_the_statement():
    assert BC.parse_index_name("Article[embedding]") == ("Article", ["embedding"])
    for bad in ("Article", "Article[]", "[embedding]", "A[b][c]"):
        with pytest.raises(ValueError):
            BC.parse_index_name(bad)
    assert BC.hierarchy_index_statement(INDEX) == STATEMENT
    with pytest.raises(ValueError):
        BC.hierarchy_index_statement("A`[b]")


# ---------------------------------------------------------------------------
# the adapter and where the lane calls it

@pytest.fixture
def L():
    pytest.importorskip("numpy")
    import l3d_dense
    return l3d_dense


def _adapter(L, monkeypatch, tmp_path, wheel, **db_kw):
    monkeypatch.setattr(BC, "engine_backend", lambda: wheel)
    a = L.ArcadeEmbedded()
    a.db = FakeDb(native=(wheel == "native"), **db_kw)
    a.DB_PATH = str(tmp_path)
    return a


def test_the_native_adapter_answers_from_schema_json_only_after_the_close(L, monkeypatch, tmp_path):
    write_schema(tmp_path, True)
    a = _adapter(L, monkeypatch, tmp_path, "native", rows=WITHOUT_METADATA)
    assert not a.hierarchy_unresolved and a.readbacks_after_close() == {}, "nothing is owed before readbacks() has run"
    assert a.readbacks() == {}, "no live source on the native wheel of an engine without #13097: no stamp yet, and no error yet"
    assert a.hierarchy_unresolved and a.db.schema.calls == []
    assert a.readbacks_after_close() == stamp(True, "schema.json")


def test_the_native_adapter_records_the_error_when_schema_json_is_missing_too(L, monkeypatch, tmp_path, capsys):
    a = _adapter(L, monkeypatch, tmp_path, "native", rows=WITHOUT_METADATA)
    a.readbacks()
    got = a.readbacks_after_close()
    assert set(got) == {"arcadedb_readback_error"} and "NotOnNativeYet" in got["arcadedb_readback_error"]
    assert "HIERARCHY STAMP MISSING" in capsys.readouterr().err


@pytest.mark.parametrize("wheel", ["native", "jvm"])
def test_an_adapter_whose_live_source_answered_reads_no_file_after_the_close(L, monkeypatch, tmp_path, wheel):
    """The directory has no schema.json: a live answer must not need it."""
    a = _adapter(L, monkeypatch, tmp_path, wheel, rows=with_metadata(True))
    assert a.readbacks() == stamp(True, "schema:index")
    assert not a.hierarchy_unresolved and a.readbacks_after_close() == {}


def test_the_jvm_adapter_keeps_the_java_read_and_needs_no_file(L, monkeypatch, tmp_path):
    a = _adapter(L, monkeypatch, tmp_path, "jvm", rows=WITHOUT_METADATA, java_value=False)
    assert a.readbacks() == stamp(False, "java-schema")
    assert not a.hierarchy_unresolved and a.readbacks_after_close() == {}


def test_the_int8_and_pq_embedded_arms_inherit_the_stamp(L, monkeypatch, tmp_path):
    monkeypatch.setattr(BC, "engine_backend", lambda: "jvm")
    a = L.ArcadeEmbeddedInt8()
    a.db, a.DB_PATH = FakeDb(rows=with_metadata(True)), str(tmp_path)
    assert a.readbacks() == stamp(True, "schema:index")
    # the PQ arm adds its index size to the same read-back through super(), so it keeps the stamp by inheritance
    assert issubclass(L.ArcadeEmbeddedPQ, L.ArcadeEmbedded) and "readbacks" in vars(L.ArcadeEmbeddedPQ)


def test_every_other_arm_has_nothing_to_read_after_the_close(L):
    assert L.Base().readbacks_after_close() == {} and L.Base.hierarchy_unresolved is False
    assert L.ArcadeServer().readbacks_after_close() == {}


def test_the_lane_reads_schema_json_after_close_s_and_outside_the_close_phase():
    """The order in main(): the timed close, `close_s` on the row, the close phase over, and only then the file read."""
    src = (HERE / "l3d_dense.py").read_text()
    lines = src.splitlines()
    hook = [i for i, ln in enumerate(lines) if ln == "    out.update(b.readbacks_after_close())"]
    assert len(hook) == 1, "main() calls the hook once, at the indent of the function body (outside the `with` of the close phase)"
    phase = [i for i, ln in enumerate(lines) if ln == '    with _beat.phase("close"):']
    close_s = [i for i, ln in enumerate(lines) if ln.strip() == 'out["close_s"] = round(time.perf_counter() - _t, 3)']
    assert len(phase) == 1 and len(close_s) == 1 and phase[0] < close_s[0] < hook[0]
    # the first live read stays where it always was: after the build timer, before the warm-up
    live = [i for i, ln in enumerate(lines) if ln.strip().startswith("out.update(b.readbacks())")]
    assert len(live) == 1 and live[0] < phase[0]


def test_the_driver_closes_only_to_read_the_stamp_and_only_after_the_passes():
    src = (HERE / "dense_multipass_driver.py").read_text()
    sampler_done, guard = src.index("cell_mem = mem.finish()"), src.index('if getattr(b, "hierarchy_unresolved", False):')
    last_pass, write = src.index("print(\"RESULT \" + json.dumps(rec), flush=True)"), src.index('with open(outp, "w") as f:')
    assert last_pass < sampler_done < guard < write
    assert src.count("b.close()") == 1 and src.index("b.close()") > guard


# ---------------------------------------------------------------------------
# F15: the row gate accepts each source and refuses a new row with no stamp

def _row(**kw):
    base = {"instrument": OV.INSTRUMENT, "lane": "l3d", "backend": "arcadedb_dense_embedded", "scale": "small", "workload": "search",
            "engine_backend": "native", "ts_utc": "2026-12-03T10:00:00+00:00"}
    base.update(kw)
    return base


def _hierarchy(rows):
    allowed = []
    found, judged = OV.stamp_findings(rows, allowed=allowed)
    return [f for f in found if f["key"] == "arcadedb_hierarchy"], allowed


@pytest.mark.parametrize("source", ["schema:index", "java-schema", "schema.json"])
def test_f15_passes_a_row_stamped_by_any_of_the_three_sources(source):
    found, allowed = _hierarchy([_row(arcadedb_add_hierarchy=True, arcadedb_add_hierarchy_source=source)])
    assert found == [] and allowed == []


def test_f15_fails_a_row_that_has_a_stamp_and_no_source():
    found, _ = _hierarchy([_row(arcadedb_add_hierarchy=True)])
    assert [f["kind"] for f in found] == ["WRONG"] and "arcadedb_add_hierarchy_source" in found[0]["text"]


def test_f15_fails_a_new_row_with_no_stamp_and_prints_the_reason_the_cell_gave(tmp_path):
    """The row a cell lands when no source answered: NOT STAMPED, and the message of the failed read-back is in the finding."""
    err = BC.arcadedb_hierarchy_after_close(str(tmp_path), INDEX, ["schema:index: no row"], err=io.StringIO())
    for row in (_row(), _row(**err), _row(engine_backend="jvm", **err)):
        found, allowed = _hierarchy([row])
        assert [f["kind"] for f in found] == ["NOT STAMPED"] and allowed == [], row
    found, _ = _hierarchy([_row(**err)])
    assert "schema.json" in found[0]["text"] and "could not be read back by any source" in found[0]["text"]


def test_f15_still_fails_a_stamp_of_false_because_the_sentence_says_the_index_is_layered():
    found, _ = _hierarchy([_row(arcadedb_add_hierarchy=False, arcadedb_add_hierarchy_source="schema.json")])
    assert [f["kind"] for f in found] == ["WRONG"]


def test_the_exception_for_rows_measured_before_2026_11_15_is_unchanged():
    old = _row(lane="l3d", scale="deep10m", ts_utc="2026-11-12T01:00:00+00:00",
               arcadedb_readback_error="NotOnNativeYet: the Java schema object is not on the native wheel")
    found, allowed = _hierarchy([old])
    assert found == [] and len(allowed) == 1
    found, allowed = _hierarchy([dict(old, ts_utc="2026-12-03T10:00:00+00:00")])
    assert [f["kind"] for f in found] == ["NOT STAMPED"] and allowed == []
    assert [(e.lane, e.backend, e.engine_backend, e.until_ts) for e in OV.STAMP_EXCEPTIONS if e.key == "arcadedb_hierarchy"] == [
        ("l3d", "arcadedb_dense_embedded", "native", "2026-11-15")]
