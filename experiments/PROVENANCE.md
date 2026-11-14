# Provenance

Where the files in this directory came from, and which code measured which rows.

The benchmark harness was developed in [humemai/arcadedb-embedded-python](https://github.com/humemai/arcadedb-embedded-python) under `benchmarks/experiments/`. It is copied here in steps. The commit message of every copy names its origin as `Origin: humemai/arcadedb-embedded-python@<sha>`, and the table below lists the same SHAs. The origin repository stays readable after it is archived, and every commit named on this page is on a branch that is pushed there.

## What was copied, and from which commit

| Files here | Origin commit | Branch of the origin | Step |
| --- | --- | --- | --- |
| `README.md`, this file | written here | | 1 |
| `PROTOCOL.md`, `FAIRNESS.md`, `COMPARATORS.md`, `PAGE-SPEC.md`, `PUBLISHING.md`, `READING-RESULTS.md`, `QUANTIZATION.md` (verbatim) | `4272386cfa` (2026-11-06) | `main` | 1 |
| the rest of `benchmarks/experiments/` at that commit (verbatim): runners, lanes, generators, gates, tests, fixtures, Dockerfiles, small tracked results | `4272386cfa` (2026-11-06) | `main` | 2 |
| `land_stage.py`, `test_land_stage_branch.py` (taken whole: `land_stage.py` pushes a branch and never `main`) and the two sentences of `PUBLISHING.md` that name its flag and the pulled-file knob | `f5f42f3228` (2026-11-14) | `bench/landing-fixes-2611` | 3 |
| layout and path edits of the step 2 files (root lookups, `BINDINGS_REPO`, links, skips without the runbook) | written here, on `4272386cfa` | | 3 |
| `test_moved_paths.py`, `.github/workflows/test-experiments.yml`, the hook exclusions of `.pre-commit-config.yaml` | written here | | 3 |
| `benchmarks/python-bindings/` (the frozen artifact of the SciPy 2026 paper, 91 files, byte-identical, never edited here) | `6463877445` (2026-10-06, the last commit that touched it; the tree is the same at `4272386cfa` and at the origin's `main`) | `main` | 3b |
| origin PR 554 over `4272386cfa`: four ArcadeDB arms (`arcadedb` and `arcadedb-jvm`), PostgreSQL-wire twin, official driver, page and landing code (68 files, `CAMPAIGN.md` left out; `land_stage.py` stays at its step 3 version) | `17be3f686b` (2026-11-09) | `bench/arcadedb-import-26111` | 4 |
| origin PR 584 (build-only mode, the wheels-only post1 rerun, `post1_rows.py`, `make_post1_rerun_stages.py`, `POST1-RERUN.md`), the post2 names (`--wheel-label postN`, `land_stage --post-tag`) and the `.postN` pair check of `verify_pair_c25.sh`, as three commits on the PR 554 head | `3e9fa32de6`, `a585f03149`, `f24d65aef3` (2026-11-10 to 2026-11-11) | `bench/post3-rerun-harness` | 5 |
| the PG+AGE harness fix of origin PR 596: visited probe budget, `statement_timeout` analytics limit, tests (the two commits cherry-picked onto `4272386cfa` for the rerun) | `236a4d1296`, `9559b02953` (2026-11-13) | `bench/comparator-reruns-2611-on-4272386` | 6 |
| origin PR 559 (a draft there): the 2026-12 instrument (exact per-phase peak, settled per-phase disk, sampled breakdown, its tests) and the host helper `host/bench-cgroup-grant`; no row of the paper used it | `fd7dd6b412`, `4c5764e0a1` | `bench/instrument-2026-12-memory` | 7 |
| the landing-tool and page-gate fixes, in the order they were made (21 commits, `e3ac062cfb` to `9a831c5dbd`, 2026-11-14): `arm_identity` reads `server_settings` as the freeze writes it, `land_stage --apply` needs `--branch`, the dense overlay build count `BENCH_MP_BUILDS`, `land_stage --max-rep` and `--post1-orphans`, the `provenance_check` censored excuse, `BENCH_COMPARATOR_PIN`, the `page_check` and `export_web` fixes of the first 2026-11 landing, display names for every roster key and the raw backend key gate. The landed result files of these commits are not taken | `e3ac062cfb`, `f5f42f3228` on `bench/landing-fixes-2611`; `9a56c96545` on `bench/dense-overlay-n3`; the other 18 on `landing/2611-n3-e2-l1tpc-l2` | those branches | 8 |

`f5f42f3228` is a descendant of `4272386cfa` that also holds the commits of origin PRs 554 and 584, so its `land_stage.py` carries their options too (`--post1-reps`, `--post-tag`, `BENCH_LAND_PULLED_FILE`); `post1_rows.py`, which `--post1-reps` imports, arrives with those PRs.

`4272386cfa` is the base of the copy because it is the commit the comparator reruns were cut from. Work that is on other branches of the origin and that some rows depend on is not copied yet, and is listed in the next section.

## Which code measured which rows

The rows carry the engine version, the engine commit and the wheel, but no harness commit. The harness commit of a family of stages is this:

| Family of stages | Harness commit that ran | Branch of the origin | Copied here |
| --- | --- | --- | --- |
| Comparators, 2611 passes | `main` of the origin at the start of each stage (a stage pulls `main` before it runs); `4272386cfa` is the base of the copy, commits of `main` after it (for example `31fcc9bc7b`, 2026-11-09) are not in the copy | `main` | in part (the base) |
| PG+AGE reruns (visited probe budget, `statement_timeout` limit) | `9559b02953` (2026-11-13), the two commits of origin PR 596 on `4272386cfa` | `bench/comparator-reruns-2611-on-4272386` | yes, step 6 (merged onto the tree of step 5 without a conflict; the rerun ran at `9559b02953`, which has neither PR 554 nor PR 584) |
| ArcadeDB four arms, JVM and native, 26.11.1 | `eb7c767d97` (2026-11-07), part of origin PR 554 | `bench/arcadedb-import-26111` | yes, step 4 (the tree is `17be3f686b`, which holds `eb7c767d97` and seven later commits of the PR) |
| PostgreSQL-wire twin and HTTP catch-up cells | `defe8f18ac` (2026-11-08) | `bench/catchup-2611` | not yet |
| Rerun of the embedded cells with the 26.11.1.post2 wheels | `00f9e7d723` (2026-11-11), origin PR 554 and PR 584 combined, plus two commits | `bench/post2-rerun-on-livepin` | yes, step 5, in the tree of `f24d65aef3`: the same tooling on the PR 554 head with the commits of `main` that `00f9e7d723` lacks (the excluded-windows guard); the `.postN` pair check is the same change as `00f9e7d723` |

The page and the tables are generated by the landing code (`land_stage.py`, `export_web.py`, `make_paper_tables.py`, `page_check.py`), which is not the code that measured. The landing code in this tree is the tip of `landing/2611-n3-e2-l1tpc-l2` (`9a831c5dbd`, 2026-11-14) plus the dense overlay build count (`9a56c96545`); the fix that makes `land_stage.py` push a branch instead of `main` is `f5f42f3228`.

## What is not copied

- `data/` (corpora): downloaded or generated by the scripts, not tracked.
- `docker-wheels/`: the wheels are installed from PyPI by version and checksum.
- `results/raw/`: per-cell client and server logs. The raw rows will be published as a release asset with a checksum file, not in git.
- `CAMPAIGN.md`: the runbook of the benchmark host. It is copied later or not at all.
- `benchmarks/python-bindings/` is not part of `experiments/`; it is copied frozen in a separate step (see the table above).

## Citations that point into private notes

Many comments and documents in the copy cite decisions and bug records by number (for example `DECISIONS #131`). Those records are not part of any repository, so the citations do not resolve here. They are citations of private notes, copied unchanged because they are already in the public origin repository, and are cleaned up later.
