"""comparator_constraints.json is data for the pin-freshness process of humemai/mmdbbench#175: the shape of its two tables, and that the pins its
exception lines name are the pins the code carries (a hold that names a version the files do not pin is a stale line)."""
import datetime
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = json.loads((HERE / "comparator_constraints.json").read_text(encoding="utf-8"))
CONSTRAINT_KEYS = ("backend", "component", "supported_versions", "source_url", "date_read")
EXCEPTION_KEYS = ("backend", "pinned", "latest_release", "reason", "date", "decided_by")
PIN_FILES = ("runner.py", "build_images.sh", "Dockerfile.pgage", "Dockerfile.mongosearch", "Dockerfile.composed")


def _iso(value):
    return datetime.date.fromisoformat(value)


def test_every_constraint_row_has_backend_component_versions_source_and_date():
    assert DATA["constraints"], "the constraint table is empty"
    for row in DATA["constraints"]:
        for key in CONSTRAINT_KEYS:
            assert isinstance(row.get(key), str) and row[key].strip(), (row.get("backend"), row.get("component"), key)
        assert row["source_url"].startswith("https://"), row["source_url"]
        _iso(row["date_read"])


def test_every_exception_line_has_version_reason_date_and_who_decided():
    assert DATA["exceptions"], "no exception lines"
    for row in DATA["exceptions"]:
        for key in EXCEPTION_KEYS:
            assert isinstance(row.get(key), str) and row[key].strip(), (row.get("backend"), key)
        _iso(row["date"])   # a date, not checked against today: the owner's day and the CI clock (UTC) can differ by one


def test_the_exceptions_that_name_a_pin_name_the_pin_the_code_carries():
    text = "\n".join((HERE / name).read_text(encoding="utf-8") for name in PIN_FILES)
    named = {"PostgreSQL": "18.7", "SurrealDB server": "v3.2.6", "SurrealDB embedded": "surrealdb==2.0.0", "CrateDB": "6.4.7"}
    for prefix, token in named.items():
        rows = [r for r in DATA["exceptions"] if r["backend"].startswith(prefix)]
        assert rows, f"no exception line for {prefix}"
        assert token in text, f"{prefix}: the exception names {token}, no pin file carries it"
