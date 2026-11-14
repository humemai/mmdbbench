"""Fairness F14c: an arm that records no `index_s` declares why, and the declaration is true (humemai/mmdbbench#55).

Redis is the case: its index is created before the load and built as each HSET arrives, so there is no index phase to time."""
import io
import re
from contextlib import redirect_stdout
from pathlib import Path

import fairness_check as FC
import publish_instrument

HERE = Path(__file__).resolve().parent


def _row(backend, **kw):
    base = {"lane": "l3d", "backend": backend, "instrument": publish_instrument.PUBLISH_INSTRUMENT}
    base.update(kw)
    return base


def _redis_class_source():
    text = (HERE / "l3d_dense.py").read_text(encoding="utf-8")
    m = re.search(r"^class RedisDense\(Base\):\n(.*?)(?=^class |^def )", text, re.S | re.M)
    assert m, "RedisDense not found in l3d_dense.py"
    return m.group(1)


def test_a_redis_row_with_no_index_phase_is_not_a_finding_beside_arms_that_split():
    rows = [_row("arcadedb_dense_embedded", index_s=12.5), _row("redis_dense")]
    out = io.StringIO()
    with redirect_stdout(out):
        bad = FC.check_phase_split(rows)
    assert bad == 0, out.getvalue()
    assert "declared with no separate index phase" in out.getvalue()


def test_an_arm_that_neither_splits_nor_declares_still_fails():
    rows = [_row("arcadedb_dense_embedded", index_s=12.5), _row("some_new_dense_arm")]
    with redirect_stdout(io.StringIO()):
        assert FC.check_phase_split(rows) == 1


def test_the_redis_declaration_names_the_mechanism():
    text = FC.PHASE_SPLIT_DECLARED[("l3d", "redis_dense")]
    assert "FT.CREATE" in text and "before the load" in text and "drain" in text and "build timer" in text


def test_the_declaration_is_true_of_the_adapter():
    src = _redis_class_source()
    build = src.split("def build(", 1)[1].split("\n    def ", 1)[0]
    assert "FT.CREATE" in build and "hset" in build and build.index("FT.CREATE") < build.index("hset"), "the index must be created before the load"
    assert re.search(r"def post_build\(self\):\n\s+self\._await_indexed\(\)", src), "the wait for the workers must be the post-build step"
    assert "index_s" not in src, "an arm that records index_s no longer needs the declaration"
