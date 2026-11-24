"""runner.split_cpuset takes a lane's cpuset as a range or as a list (humemai/mmdbbench#184).

Run with `python -m pytest test_split_cpuset.py -q -rs` from this directory.

The mini's compare2 lane is cores 4,6 and compare3 is 8,10. BENCH_CPUSET carries the lane's cores, and split_cpuset used to read only 'a-b', so
main() raised ValueError before any cell ran. A single range keeps the shards it always gave.
"""
import pytest

import runner


@pytest.mark.parametrize("cpuset, n, want", [
    ("0-11", 1, ["0-11"]),
    ("0-11", 2, ["0-5", "6-11"]),
    ("0-11", 3, ["0-3", "4-7", "8-11"]),
    ("3-3", 1, ["3-3"]),
    ("4-5", 2, ["4-4", "5-5"]),   # a range keeps its 'a-a' shards
])
def test_a_range_gives_the_shards_it_always_gave(cpuset, n, want):
    assert runner.split_cpuset(cpuset, n) == want


@pytest.mark.parametrize("cpuset, n, want", [
    ("4,6", 1, ["4,6"]),
    ("8,10", 1, ["8,10"]),
    ("4,6", 2, ["4", "6"]),
    ("0-5,8-11", 1, ["0-5,8-11"]),
    ("0-5,8-11", 2, ["0-4", "5,8-11"]),
    ("11,0-2,4", 1, ["0-2,4,11"]),   # unsorted input, one shard in docker's own form
    ("3", 1, ["3"]),
])
def test_a_list_gives_docker_cpuset_strings_of_the_same_cores(cpuset, n, want):
    assert runner.split_cpuset(cpuset, n) == want


def test_the_shards_cover_the_cores_once_and_match_the_cpu_count():
    for cpuset in ("4,6", "0-5,8-11", "0-11"):
        for n in (1, 2):
            shards = runner.split_cpuset(cpuset, n)
            got = [c for s in shards for c in runner._cpu_numbers(s)]
            assert got == runner._cpu_numbers(cpuset)
            assert sum(runner._cpuset_size(s) for s in shards) == runner._cpuset_size(cpuset)


def test_more_workers_than_cores_still_refuses():
    with pytest.raises(ValueError, match="3 workers > 2 cpus in 4,6"):
        runner.split_cpuset("4,6", 3)
