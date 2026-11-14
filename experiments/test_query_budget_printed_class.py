"""The per-query budget sentences count the reps the table prints, not every rep of the lane (2026-11-14, numbers verification of the n=3 rows).

`_query_budget_notes` read `_FROZEN_ROWS`, which still holds the strict-class reps: main() sets the strict rows of a cell aside (BUGS F52, one
class per table) only after it has set `_FROZEN_ROWS`. The printed medians are the relaxed reps, so the sentence under the graph OLTP table said
"ArcadeDB (embedded) at SF10: 3-hop filtered (83 starts)" although no printed rep hit the budget (only a strict rep did), and widened the other
spans ("7 to 13 starts" where the printed reps gave "10 to 13"). The class a table prints is the relaxed one wherever a cell has relaxed reps;
a cell with strict reps only keeps them.
Light: no files. Run with pytest, or as plain functions from this directory.
"""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("BENCH_RESULTS_DIR", tempfile.mkdtemp(prefix="budget-printed-class-"))
os.environ.setdefault("BENCH_ONLY_LANES", "l2")
import export_web as EW  # noqa: E402

BACKEND = "arcadedb_graph_embedded"


def _row(rep, klass, starts=None, scale="sf10", backend=BACKEND):
    """One l2 rep: `starts` is the count of 3-hop starts it timed before its budget ran out, None when it finished."""
    r = {"lane": "l2", "scale": scale, "workload": "oltp", "backend": backend, "rep": rep, "durability_class": klass,
         "hop3f_censored": "False", "hop3f_iters": 100, "hop3f_budget_s": 300.0, "hop3f_elapsed_s": 120.0}
    if starts is not None:
        r.update(hop3f_censored="True", hop3f_iters=starts, hop3f_elapsed_s=299.0)
    return r


def _notes(rows):
    old = list(EW._FROZEN_ROWS)
    try:
        EW._FROZEN_ROWS[:] = rows
        return EW._query_budget_notes("l2")
    finally:
        EW._FROZEN_ROWS[:] = old


def test_a_strict_rep_that_hit_the_budget_makes_no_sentence_when_the_printed_reps_finished():
    rows = [_row(1, "relaxed"), _row(2, "relaxed"), _row(3, "relaxed"), _row(1, "strict", starts=83)]
    assert _notes(rows) == []


def test_the_span_and_the_count_come_from_the_printed_reps_only():
    rows = [_row(1, "relaxed", starts=10), _row(2, "relaxed", starts=12), _row(3, "relaxed", starts=13),
            _row(1, "strict", starts=7)]
    notes = _notes(rows)
    text = " ".join(notes)
    assert len(notes) == 2, notes                       # the lead and the one engine's line
    assert "10 to 13" in text and "7 to 13" not in text, text
    assert notes[0].startswith("One query cell"), notes[0]


def test_a_cell_with_strict_reps_only_keeps_them_and_a_cell_with_relaxed_reps_is_judged_alone():
    # sf1 has relaxed reps (its strict rep that hit the budget is set aside); sf10 has strict reps only, so they are what the table prints
    rows = [_row(1, "relaxed", scale="sf1"), _row(1, "strict", starts=9, scale="sf1"),
            _row(1, "strict", starts=5), _row(2, "strict", starts=6)]
    text = " ".join(_notes(rows))
    assert "5 to 6" in text, text
    assert f"at {EW.scale_label('l2', 'sf1')}:" not in text, text      # sf1 printed relaxed reps that finished: no sentence for it


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
