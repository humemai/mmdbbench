# Experiments

The code, the pins and the documents behind the published MMDBBench results.

This directory is filled in steps, so that each step is one pull request that a reader can compare with its origin:

1. The method documents and [PROVENANCE.md](PROVENANCE.md), which says where every file came from and which commit of the origin measured which rows.
2. The harness, copied verbatim at one commit of its origin.
3. The edits that make it work from this layout, and a test workflow.

## Documents

| Document | What it holds |
| --- | --- |
| [PROTOCOL.md](PROTOCOL.md) | how the harness must be operated; every rule names what enforces it |
| [FAIRNESS.md](FAIRNESS.md) | what "the same thing" means for a comparison, what may differ, and what is checked mechanically |
| [COMPARATORS.md](COMPARATORS.md) | the engines compared against ArcadeDB, their pinned images and versions |
| [PAGE-SPEC.md](PAGE-SPEC.md) | what the project page contains and what each cell must satisfy |
| [PUBLISHING.md](PUBLISHING.md) | how the frozen rows get onto the project page |
| [READING-RESULTS.md](READING-RESULTS.md) | how to read the results without misreading them |
| [QUANTIZATION.md](QUANTIZATION.md) | what each vector engine ships and which quantization arms the page runs |

## Running the tests

The harness has its own unit tests. They need no Docker, no data and no benchmark host: they fake docker and read the fixtures in this directory. From this directory:

```
uv run --no-project --with pytest --with numpy --with pandas --with pyarrow --with requests python -m pytest -q -p no:cacheprovider .
```

`.github/workflows/test-experiments.yml` runs the same command on every change under `experiments/`. `test_moved_paths.py` checks that every module imports and that every file the code names exists in this layout.

## Paths that stay as they are

The benchmark host runs its stages from a checkout of the repository the harness came from, until its chain ends. Three places name that checkout on purpose and are not changed here:

- the stage scripts that `make_2611_stages.py` writes (and `stage_drafts_2611.sha256`, which pins them) go to that checkout and to its `bindings/python/dist`
- the defaults of `BENCH_LAND_REMOTE` in `land_stage.py` and of `--remote` in `merge_campaign.py`
- `queue_lint.py` and its test, which match the host's own stage processes by their command line

`build_c25_wheel.sh` and `verify_pair_c25.sh` need `BINDINGS_REPO`, the checkout that holds `bindings/python`, because the engine bindings are not in this repository. `CAMPAIGN.md`, the runbook of the host, is not copied, so the four tests that read it skip.

The first study that lives here, [sql-corpus](sql-corpus/README.md), is independent of the harness.
