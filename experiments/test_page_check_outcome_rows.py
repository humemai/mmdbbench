"""page_check reads an outcome row (a dense cell that failed or was censored) as a declaration, not as a measured entry of its arm (humemai/mmdbbench#89).

With the arm table's label on the outcome row (`ArcadeDB (server, fp32, native build)`, so it pairs with its overlay twin) the build-pair check read its null
`version_name` as a second engine, and the DEEP-10M cross-check looked for paper values of a cell that did not run. Synthetic payloads; light. Run with pytest,
or as plain functions from this directory."""
import ast
import io
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_RES = tempfile.mkdtemp(prefix="pc-outcome-")
Path(_RES, "runs.jsonl").write_text("")
Path(_RES, "e4decomp_abc123def").mkdir()
os.environ.setdefault("BENCH_RESULTS_DIR", _RES)
os.environ.setdefault("BENCH_ENGINE_COMMIT", "abc123def")
import page_check as PC  # noqa: E402

VERSION = "arcadedb 26.11.1 · a3a5d1245"


def _measured(label, build, **kw):
    e = {"backend": label, "build": build, "backend_key": "arcadedb_dense_server", "is_arcadedb": True, "scale": "deep10m", "version_name": VERSION,
         "metrics": {"cold p50 ms": {"median": 4.0, "n": 3}}}
    e.update(kw)
    return e


def _outcome(label, build):
    return _measured(label, build, version_name=None, outcome="failed", metrics={"cold p50 ms": {"text": "failed"}})


def _pair(entries, absences=()):
    payload = {"tables": [{"id": "l3d", "entries": entries, "declared_absences": [{"backend": b, "kind": "not measured"} for b in absences]}]}
    out = io.StringIO()
    with redirect_stdout(out):
        bad = PC._check_build_pair(payload, [])
    return bad, out.getvalue()


def test_a_failed_build_with_an_outcome_row_does_not_name_a_second_engine():
    bad, text = _pair([_measured("ArcadeDB (server, fp32, JVM build)", "jvm"), _outcome("ArcadeDB (server, fp32, native build)", "native")])
    assert bad == 0, text


def test_a_missing_build_with_no_outcome_row_and_no_declaration_is_still_a_finding():
    bad, text = _pair([_measured("ArcadeDB (server, fp32, JVM build)", "jvm")])
    assert bad == 1 and "ONEBUILD" in text, text


def test_a_declared_absence_still_covers_the_missing_build():
    bad, text = _pair([_measured("ArcadeDB (server, fp32, JVM build)", "jvm")], absences=["ArcadeDB (server, fp32, native build)"])
    assert bad == 0, text


def test_the_declared_absences_of_a_censored_or_failed_dense_cell_carry_the_arm_table_label():
    src = (HERE / "export_web.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_censored_notes")
    appends = [c for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "append"
               and c.args and isinstance(c.args[0], ast.Call) and getattr(c.args[0].func, "id", "") == "_with_build"]
    assert appends and all("_dense_arm_label" in ast.get_source_segment(src, c) for c in appends), "the declaration label is not the arm table's for the dense lane"
