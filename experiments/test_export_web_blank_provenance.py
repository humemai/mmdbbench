"""export_web entry builders read `host` and `image` as `x or None` (humemai/mmdbbench#83).

A freeze that gains a column through a new lane (the dense rows carry `host` and `image`) turns a missing key into a blank cell: `csv.DictReader` gives
"" where a missing column gave None, and every entry built from `rs[0].get("host")` changed from null to "" with no row of its table touched.
Source-level and light: no entry dict literal in export_web.py may take `host` or `image` from a bare `.get(...)`. Run with pytest, or as plain functions."""
import ast
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIELDS = ("host", "image")


def _bare_gets():
    tree = ast.parse((HERE / "export_web.py").read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and k.value in FIELDS and isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute) and v.func.attr == "get" \
                    and v.args and isinstance(v.args[0], ast.Constant) and v.args[0].value in FIELDS:
                found.append((k.value, v.lineno))
    return found


def test_no_entry_takes_host_or_image_from_a_bare_get():
    assert _bare_gets() == [], f"entry fields read as a bare .get() (a blank cell is not None): {_bare_gets()}"


def test_the_scan_sees_the_generic_builder_pattern_as_fine():
    tree = ast.parse('d = {"host": rs[0].get("host") or None, "image": _x(rs).get("image") or None}')
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Dict) and any(isinstance(v, ast.Call) for v in n.values)]
