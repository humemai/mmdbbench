# benchmarks

`python-bindings/` is the frozen artifact of the SciPy 2026 paper on the Python bindings of ArcadeDB. It is copied from [humemai/arcadedb-embedded-python](https://github.com/humemai/arcadedb-embedded-python) at commit `6463877445` (the last commit that touched it) and is never edited here. The origin repository stays the citation target of that paper.

The MMDBBench harness reads some of its files from this path (the Python overhead results and the frozen rows of the bindings suite), which is why it sits at `benchmarks/python-bindings/` and not under `experiments/`. The harness itself is in [experiments/](../experiments/README.md).
