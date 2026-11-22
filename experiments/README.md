# Experiments

The code, the pins and the documents behind the published MMDBBench results.

This directory was filled in steps, so that each step was one pull request that a reader could compare with its origin:

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
uv run --no-project --with pytest --with numpy --with pandas --with pyarrow --with requests python -m pytest -q -rs -p no:cacheprovider .
```

`.github/workflows/test-experiments.yml` runs the same command on every change under `experiments/`. `test_moved_paths.py` checks that every module imports and that every file the code names exists in this layout.

## Paths that stay as they are

The benchmark host ran its stages from a checkout of the old repository, `humemai/arcadedb-embedded-python` (now archived), and stages already generated still say so; they are records and are not edited. The landing defaults name this repository: `BENCH_LAND_REMOTE` in `land_stage.py` and `--remote` in `merge_campaign.py` default to `~/repos/humemai/mmdbbench/experiments/results` (and its `runs.jsonl`) on the host `BENCH_LAND_HOST` (default `mini`). A stage generated before the host switched wrote its rows into `benchmarks/experiments/results` of the old checkout, and landing those rows takes that path in `BENCH_LAND_REMOTE` or `--remote`. Two places are left as they are on purpose:

- `tools/merge_fourarm_rows.py` and its test: `BENCH_FOURARM_RESULTS` defaults to `benchmarks/experiments/results`, the layout of the four-arm worktrees on the host, which are checkouts of the old repository
- `queue_lint.py` and its test, which match the host's own stage processes by their command line

The stage scripts that `make_2611_stages.py` and `make_post1_rerun_stages.py` write name a checkout of this repository: `REPO` is `BENCH_STAGE_REPO` at generation, default `$HOME/repos/humemai/mmdbbench`, and the harness is `$REPO/experiments`. The pinned wheel is read from `$BINDINGS_REPO/bindings/python/dist`, with `BINDINGS_REPO` defaulting to the stage's `REPO`. `stage_drafts_2611.sha256` pins the drafts and is regenerated with `python3 test_stage_generator_2611.py --rewrite`.

A rerun of the ArcadeDB chains on a later release keeps the instrument and names three things of its own, because the host still holds the first pass's (#126). `--go-marker PATH` is the gate file of the chain: the default one, `$HOME/conf/go-arcadedb-2611`, is refused with another `--arcadedb-release`. `--id-prefix` is checked against `--status-file`: a prefix whose stage ids already have `ALL-DONE` lines there is refused. `--harness-sha <40 hex>` says the stages run from a worktree of this repository pinned at that commit, which `BENCH_STAGE_REPO` names: they check `HEAD` instead of pulling, and the pair install creates the worktree's own wheel directory, `$BINDINGS_REPO/bindings/python/dist`, instead of archiving another release's. The rows of such a chain are in the worktree's own `experiments/results`; `tools/merge_fourarm_rows.py` reads them when `BENCH_FOURARM_PULL` names the worktrees and `BENCH_FOURARM_RESULTS` is `experiments/results`. `test_stage_generator_rerun.py` covers the three arguments.

`build_c25_wheel.sh` and `verify_pair_c25.sh` need `BINDINGS_REPO`, the checkout that holds `bindings/python`, because the engine bindings are not in this repository. `CAMPAIGN.md`, the runbook of the host, is in this directory, so the four tests that read it run.

The first study that lives here, [sql-corpus](sql-corpus/README.md), is independent of the harness.
