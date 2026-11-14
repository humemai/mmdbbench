# Methodology

These are the rules every published result follows. A result that breaks one of them is not published as a comparison; it is published as a declared exception, or not at all.

## The rules

1. **Same task, same data, same machine.** Every engine in a lane answers the same queries over the same corpus on the same dedicated machine. The machine's specification is on the results page.
2. **Answers are checked.** Each query's answer is reduced to a digest and compared between engines. A fast wrong answer is a failure, not a result.
3. **Settings are published.** Each engine runs at its documented defaults unless a setting is required to run the task (a memory limit, a durability class, an index the task needs).
   Every deviation is listed on the [Engines](engines.md) page with the reason. An index added for one engine is added, in its equivalent form, for every engine that has one.
4. **Equal resources.** Every engine gets the same memory cap and CPU allotment inside a lane, and the same durability classes are measured for every engine that offers them
   (a relaxed class and a strict class where the engine supports both).
5. **Repetitions and medians.** Each cell is run three times, in whole passes of one repetition each, for every engine (the four ArcadeDB arms included). The page prints the median with the minimum and maximum, never a single run and never the mean, and states the number of repetitions behind a table whenever it is below three. With three repetitions a difference below about 1.3 times is not claimed.
6. **Budgets and censoring.** A query that cannot finish within its time budget is recorded as censored, with the budget, and is never silently dropped or counted as fast. Where an engine
   can be asked to stop a query itself, the budget is enforced by the engine; otherwise it is checked between iterations.
7. **Failures are results.** An engine that runs out of memory, times out or refuses a task has that recorded as its result for the cell, with the error it gave.
8. **Versions are exact.** Every row records the engine version and, for containers, the image digest it ran on. A cell never mixes rows from different versions: when an engine ships a new
   version, new rows are added next to the old ones. ArcadeDB is pinned by upstream commit rather than by release number when it runs a development build, because its build line reads the same development version for every commit;
   its embedded and server arms in one table are built from the same commit and run the same JVM. The 2026-11 measurement of ArcadeDB runs the 26.11.1 release in four arms: embedded and served, each on the JVM and as the native build.
9. **Warm-up is declared.** Whether a timing includes the first run, a warm-up, or an index build is stated in the table it appears in.
10. **History is kept.** A correction or a new version adds rows; the earlier rows stay visible.

## The 2026-11 instrument

The protocol version is `2026-11`, in development until its first release, and every row is stamped with the instrument that measured it. There is one method and no switch for another: the harness refuses
to run a cell under any other instrument value. These choices are part of the instrument and are the same for every cell:

- **A warm-up before the sparse search.** Every sparse engine runs 1,000 untimed searches on queries that are not in the timed set, so a query or result cache cannot flatter an engine.
- **The CPU idle state is held for each timed cell**, at the lowest latency target, so a single-client time under a millisecond does not include a core waking up. A cell that cannot take the hold still runs, and the row says so.
- **The dense lane indexes the vector id** on every engine that would otherwise scan for the record it deletes, so the delete column compares indexed lookups.
- **Each JVM engine runs the memory settings its vendor documents.** The memory cap is the same for every engine in a cell. The heap inside it is not one Java rule for all: ArcadeDB, embedded and served, sets only `-Xmx` (the tier heap) and leaves the initial heap unset; Neo4j and Elasticsearch pin the initial heap to the maximum, as their documentation recommends, and take the heap their vendors' rules give for the cap. The [table below](#jvm-and-memory-settings-per-engine) lists the setting, the vendor's sentence and what the memory column shows for each engine.
- **Milvus runs as its vendor ships it.** Milvus 3.0.3 runs as the vendor's Docker Compose standalone: Milvus, etcd and MinIO as three containers, every image pinned by digest. Data goes in by Milvus's bulk import, not by insert batches. Storage V2, Milvus's default, is the headline; Storage V3 is a switch used only for a sensitivity run, and every row records the mode it ran in. Details are in [Milvus](#milvus).
- **Served ArcadeDB is measured through the benchmark's own minimal HTTP client** (`lean_http.py`, one persistent `http.client` connection), while the other engines are measured through their vendors' Python clients, so client weight differs between the served engines. Bulk loads and transactions use the same client.
- **Large results are read on each engine's documented bulk path** (Arrow for embedded ArcadeDB and DuckDB), with the plain-Python read timed beside it. Small results do not move. The typed read must return the same answer as the plain read, or the cell ends.
- **Memory, disk and IO are read at the end of every phase** of a cell (load, index build, warm-up, queries, and idle), between two timed sections and never inside one. The headline memory is the memory the cell's containers own, the same kernel counter for every engine, summed over every container of a multi-container deployment; the heap figures of JVM engines are context and are not compared across engines. Disk and IO are read the same way for every engine.
- **The dense lane compares engines at matched recall.** After the build, the lane runs one timed pass per search-beam value on the same index (`ef` of 50, 100, 200 and 400 for the HNSW engines; ArangoDB's `nProbe` at 0.5, 1, 2 and 4 times its calibrated value). The headline is the lowest median latency among the passes whose recall@10 reaches 0.95, with the beam that won it. An engine that never reaches 0.95 is printed as `not reached` with its best recall, never as a slower or lower-recall number. Engines with no beam setting run one pass.
- **Product-quantization (PQ) arms are off for now.** They run beside the full-precision and int8 arms only when enabled, with the same setting for every engine that offers it: 32 subspaces of 256 centroids, and a re-rank of the stored vectors where the engine can do one. They stay off until the measured ArcadeDB release carries the upstream PQ fixes (ArcadeData/arcadedb#10516 to #10519), because before them ArcadeDB's SQL search ignores a PQ index and would measure exact search under a PQ label.

The harness documents these choices in [PROTOCOL.md](https://github.com/humemai/arcadedb-embedded-python/blob/main/benchmarks/experiments/PROTOCOL.md) and
[FAIRNESS.md](https://github.com/humemai/arcadedb-embedded-python/blob/main/benchmarks/experiments/FAIRNESS.md).
The 2026-10 instrument was a development version and is retired: nothing is measured with it again, and no result from it is published.

## JVM and memory settings per engine

Every engine runs the memory configuration its own vendor recommends, and every engine gets the same memory cap. A pinned initial heap (`-Xms` equal to `-Xmx`) makes the JVM commit the whole heap at start, so the kernel's memory counters read toward the cap whatever the engine needs. That is the cost of the vendor's recommended setup, and it is reported as such. The heap figures of a JVM engine (used after a full collection, committed) are recorded on the row beside the headline as context and are not compared across engines.

| Engine | Heap setting the harness passes | Initial heap | Vendor source | What the memory column shows |
|---|---|---|---|---|
| ArcadeDB embedded | `-Xmx` of the tier heap, through the bindings' `heap_size` | not pinned | The Python bindings' documented practice; ArcadeDB's maintainers advise no `-Xms` in a container with a fixed memory budget (ArcadeData/arcadedb#9167, arcadedb-docs "JVM settings in a fixed memory budget"). | demand, up to `-Xmx` |
| ArcadeDB served | `ARCADEDB_OPTS_MEMORY=-Xmx{heap}`, the tier heap | not pinned | The same guidance, so embedded and served ArcadeDB run one JVM configuration and the comparison isolates transport. | demand, up to `-Xmx` |
| Neo4j | `server.memory.heap.initial_size` = `server.memory.heap.max_size`, the heap that `neo4j-admin server memory-recommendation` prints for the cap (next table) | pinned | [Neo4j memory configuration](https://neo4j.com/docs/operations-manual/current/performance/memory-configuration/): "It is recommended to set these two parameters to the same value to avoid unwanted full garbage collection pauses." | reads toward the cap |
| Elasticsearch | `ES_JAVA_OPTS=-Xms{heap} -Xmx{heap}`; the heap is the smaller of the tier heap, 50% of the cap and 26 GiB | pinned | [Elasticsearch advanced configuration](https://www.elastic.co/guide/en/elasticsearch/reference/current/advanced-configuration.html): "The minimum and maximum values must be the same." and "Set `Xms` and `Xmx` to no more than 50% of the total memory available to each Elasticsearch node." | reads toward the cap |
| QuestDB | none: the image's own defaults | the image's | The [QuestDB configuration page](https://questdb.com/docs/configuration/) has no JVM heap recommendation, so the harness sets none. | the image's own JVM behaviour; the row records the tier heap although no heap reaches the server |

An unpinned heap is no cure for the headline either: a JVM that has grown stays grown unless the collector returns the pages, which is why the used-after-collection figure sits beside it.

### Neo4j heap and page cache

Neo4j's manual says: "Use the neo4j-admin server memory-recommendation command to get an initial recommendation." The harness runs that command from the pinned Neo4j image for each memory cap in the benchmark's tier table, on an empty data directory, and uses what it prints as the heap (initial equal to maximum) and the page cache. The tool's raw output is kept in the harness repository and a test holds the table in the code equal to it.

| Memory cap | Heap | Page cache |
|---|---|---|
| 8g | 3600m | 2g |
| 12g | 4600m | 4g |
| 16g | 5g | 7g |
| 24g | 8g | 10g |
| 28g | 10g | 11g |
| 32g | 12g | 12g |
| 36g | 13800m | 14g |
| 48g | 18g | 20g |

The tool also prints `-XX:+ExitOnOutOfMemoryError`; the harness does not set it. The tool computes the page cache for an empty data directory, so it does not account for the size of the loaded database.

### Elasticsearch heap

Elastic recommends a heap of no more than 50% of the node's memory and below the threshold for compressed object pointers: "The exact threshold varies but 26GB is safe on most systems and can be as large as 30GB on some systems." The harness takes the smaller of the tier heap, 50% of the cap and 26 GiB, with the initial and maximum heap equal. The rule can only lower a heap; on a tier whose heap is already at most half the cap and under 26 GiB it changes nothing.

### ArcadeDB page cache

`arcadedb.maxPageRAM` is not set, so the engine's default applies, a quarter of `-Xmx`, on both deployments.

### Milvus

- **Deployment.** Milvus 3.0.3 as in the vendor's `milvus-standalone-docker-compose.yaml`: Milvus, etcd (v3.5.25) and MinIO (`milvusdb/minio`, RELEASE.2024-12-18T13-15-44Z) as three containers, each pinned by its amd64 manifest digest (Milvus `812cb91a`, etcd `dc2bdc58`, MinIO `34c8e2f5`; the row records the full digests). The runner starts the three containers itself, in the cell's CPU set and network, and removes them after the cell; it does not call `docker compose`. The client is pymilvus 3.0.2 with the `bulk_writer` extra. Every setting not named here is the compose default, and no configuration file is mounted. The dense arms raise `dataCoord.segment.sealProportion` from 0.12 to 0.5 through an environment variable, so a 10M ingest lands in the merged segment layout directly.
- **Storage mode.** Storage V2, Milvus's default, is the headline. Storage V3 (`common.storage.useLoonFFI=true`) is one switch for a sensitivity run, written to its own results file, and every row records the mode it ran in.
- **Ingest.** Milvus's bulk import: Parquet written through `RemoteBulkWriter` into Milvus's own MinIO, then one import job. File preparation, upload and the job are all inside the ingest time and are also recorded apart. The sparse and the dense lane use the same path, as pgvector uses `COPY` and Elasticsearch its bulk helper.
- **Before any timed search.** The runner waits until every segment is Flushed, the index is Finished with nothing pending, and the loaded segments hold every row. The seal wait, the index wait and the load are each timed on their own and recorded on the row.
- **What a search returns.** Ids and distances only: no output fields, no vector field and no filter. The row records the output fields and the filter, both empty.
- **Memory.** The three containers share the cell's one memory cap, as every other engine's server side has it. etcd takes 512m and MinIO 1g out of the cap, the Milvus container gets the rest, and the split is recorded on the row. The row's memory, CPU, I/O and disk figures are the three containers added together.
- **Index parameters.** HNSW `M` 16, `efConstruction` 100 and `ef` 100, the HNSW_SQ SQ8 arm, and the sparse inverted index are unchanged. Equal `ef` is not equal recall, so every row carries recall@10 beside latency, and the dense lane's beam sweep reports latency at matched recall.

## Reading a result

A bar or a number is only meaningful with its footnotes: the category (in-process or server), the durability class, the scale, the version, and whether any query in the cell was censored.
The results page carries all of these next to every number.

## What this benchmark does not claim

It does not rank databases in general. It measures the tasks listed in each lane on the stated machine and settings. A different workload, scale or tuning can change the order, which is why
the settings are published and why vendors are asked to review them.
