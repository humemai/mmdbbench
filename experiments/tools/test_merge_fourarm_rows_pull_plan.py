"""merge_fourarm_rows --rows-name and --worktrees (humemai/mmdbbench#29): the post2 rows live in two worktrees under another file name.
Light: no files. Run with pytest, or as plain functions from this directory."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import merge_fourarm_rows as m  # noqa: E402


def test_the_defaults_are_the_four_arm_files():
    plan = m.pull_targets("a3a5d1245")
    assert len(plan) == 4 and all(p.endswith("/runs_page_a3a5d1245_2611.jsonl") for _b, p in plan)


def test_a_rows_name_and_a_worktree_list_name_the_post2_files_and_keep_the_local_names_apart():
    plan = m.pull_targets("a3a5d1245", "runs_page_{pin}_2611_post2.jsonl", "~/post2-wt/jvm:~/post2-wt/native")
    assert [p for _b, p in plan] == [f"~/post2-wt/{x}/{m.RESULTS}/runs_page_a3a5d1245_2611_post2.jsonl" for x in ("jvm", "native")]
    assert len({m.local_name(i, b) for i, (b, _p) in enumerate(plan)}) == 2, "two worktrees must not share one local file"
