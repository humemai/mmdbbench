# MMDBBench

MMDBBench is an open benchmark of multi-model databases: databases that serve tables, time series, documents, graphs, key-values, and vectors from one storage engine. Specialist databases built for a single model run the same tasks as per-model baselines, so a reader can see what one engine gives up or gains against the engine built for that job. Tasks are written in SQL, Cypher, and each engine's native language, and run on x86 Linux. MMDBBench runs the same tasks on the same machine with published settings, records every result with the exact engine version
that produced it, and keeps the history, so a number can always be traced and a change can always be seen.

!!! note "Status"
    The protocol version is `2026-11`, in development until its first release; the results on the project page are measured with it. The benchmark code is in [`experiments/`](https://github.com/humemai/mmdbbench/tree/main/experiments) of this repository, copied in steps from
    [humemai/arcadedb-embedded-python](https://github.com/humemai/arcadedb-embedded-python), which is retiring; new work goes here. The live results are on
    the [project page](https://humem.ai/research/mmdbbench); these documents describe how they are produced.

## Lanes

| lane | what it measures |
|---|---|
| Tables | documents and SQL analytics |
| Graphs | interactive queries and analytical queries over a social graph |
| Vectors | dense and sparse similarity search |
| Time series | ingestion and the usual monitoring queries |
| Cross-model | queries that combine more than one data model in one transaction |
| Lifecycle | durability, restarts and the cost of staying consistent |

Every engine is compared only in the lanes it is built for. An in-process engine and a server engine are different categories and are labelled as such.

## Where to go next

- [Methodology](methodology.md): the rules every run follows.
- [Engines](engines.md): what we run for each engine, and how to tell us it is wrong (generated from the first 2026-11 rows when they land).
- [Reproduce](reproduce.md): how to repeat a result on your own hardware.
- [Result rows](results-schema.md): what one published measurement contains.
- [Related work](related-work.md): the academic multi-model benchmarks and how MMDBBench differs.
- [Contribute](contribute.md): corrections, new engines, new queries.
- [Changelog](changelog.md): changes to the protocol.
