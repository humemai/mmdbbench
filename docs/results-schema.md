# Result rows

One published measurement is one row. A row says what ran, on what, and how it went. The fields below are the ones every row carries; lanes add their own metrics.

| field | meaning |
|---|---|
| `backend` | the engine and arm that ran, for example an in-process arm or a server arm |
| `lane` | the lane (tables, graphs, vectors, time series, cross-model, lifecycle) |
| `scale` / `tier` | the corpus size |
| `workload` | the task within the lane |
| `rep` | the repetition number |
| `engine_version` | the exact engine version; container runs also record the image digest |
| `durability_class` | the durability class the run used, where the engine offers more than one |
| `mem_cap` | the memory cap the run had |
| `heap` | the heap setting the cell asked for (`ARCADEDB_HEAP`, for example `4g`) |
| `jvm_input_args` / `jvm_java_version` | on an embedded ArcadeDB run on the JVM build: the command-line arguments the running JVM received (`ManagementFactory.getRuntimeMXBean().getInputArguments()`, space-joined: the `-D` settings, `-X` flags, `--add-modules` and `--add-opens` options) and its `java.version`. Read from the JVM after the cell ran, not restated from what the harness meant to pass. Empty for every arm that runs no JVM in its own process, including the native build, whose counterpart is `native_isolate_args` (the arguments its isolate was created with) |
| `io_*_mib` | the bytes the cell's containers read from and wrote to disk, per phase and in total, from the container's `io.stat`. Rows written on the benchmark machine before the fix for [issue #555](https://github.com/humemai/arcadedb-embedded-python/issues/555) counted a stacked block device (an NVMe disk and the device-mapper device on top of it) twice, so those figures are about twice their value. The fixed harness counts the device once and stamps `io_stat_dedup: 1` into the row; the frozen table halves the io figures of the earlier rows, which lack the stamp, and lists each corrected row with its raw values in `generated/io_stat_correction.json` |
| `error` / `oom_killed` | what went wrong, if anything; a failure is a result |
| metric fields | latencies (median and percentiles), throughput, peak memory and the like, per lane |
| `*_censored` / `*_budget_s` | whether a query hit its time budget, and the budget |

Rows are never edited. A correction adds a row; the history keeps both. The one correction made after the fact is the io figures above, which is applied in the frozen copy the tables are built from, never in the recorded rows.
