# Experiments

The code, the pins and the documents behind the published MMDBBench results.

This directory is filled in steps, so that each step is one pull request that a reader can compare with its origin:

1. The method documents and [PROVENANCE.md](PROVENANCE.md), which says where every file came from and which commit of the origin measured which rows.
2. The harness, copied verbatim.
3. The edits that make it work from this layout.

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

The documents were written beside the harness and name its files by their old paths (`benchmarks/experiments/...`). The paths are fixed together with the code in step 3.

The first study that lives here, [sql-corpus](sql-corpus/README.md), is independent of the harness.
