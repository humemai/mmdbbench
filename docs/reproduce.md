# Run it yourself

Every published number can be repeated on your own hardware. The benchmark runs each engine with published settings and pinned versions and writes one result row per measurement; the tables on the results page are generated from those rows. This page shows how to run one cell for one engine on a clean checkout, from the smallest cell of a lane to the filtered 3-hop read of the graph lane (`hop3f`). Nothing here needs a private file, a private image or the benchmark host. The commands in the blocks marked as runnable are checked twice: a test fails when a block names a script, backend, scale or variable that no longer exists, and a weekly workflow ([`reproduce-smoke.yml`](https://github.com/humemai/mmdbbench/blob/main/.github/workflows/reproduce-smoke.yml)) runs the first cell from this page on a clean runner and fails when its commands fail.

A reproduction is comparable when it keeps the memory cap, the durability class and the corpus the same, and compares engines on the same machine. Absolute times on different hardware differ; the order of engines and the size of the gaps are what a reproduction should be compared on. The rest of the protocol is in [Methodology](methodology.md) and in [`experiments/PROTOCOL.md`](https://github.com/humemai/mmdbbench/blob/main/experiments/PROTOCOL.md).

## What you need

- A Linux machine on x86-64 with `git`, `curl` and [`uv`](https://docs.astral.sh/uv/). `uv` fetches Python 3.12 (the repository pins it in `.python-version`) and every package, so you install nothing else. The graph cell also needs `zstd`, because the LDBC data is a `.tar.zst` file. The `arcadedb-jvm` wheels for macOS arm64 and Linux arm64 exist too, but the benchmark was only run on Linux x86-64.
- No Java installation: the `arcadedb-jvm` package bundles its own runtime, and the `arcadedb` package is a native build with no JVM at all.
- Docker only for the engines that run as servers (the served ArcadeDB arm and most comparators). The cells on this page run in one process and need no Docker.
- Memory and time as in the table below. The published rows ran inside the memory cap in its last column; a machine with less free memory than the peak column fails with an out-of-memory error. The database of a cell is built in `/tmp`: about 36 MB for `e2`, 706 MB for `tpch1`, 773 MB for the SIFT1M cell, 11 MB for `sf1`. Some Linux distributions mount `/tmp` in memory, so check `df -h /tmp` first.

The table is generated from the published rows (`experiments/results/runs_paper.csv`, three repetitions per cell, `rc == 0`) by `tools/small_cell_cost.py` and is never typed; a test fails when it differs from the rows. The cell time is `build_s` plus `oltp_total_s` plus the elapsed time of the five analytics queries of `l1tpc`, a lower bound because the timed reads of the other lanes are not in it. The memory is the highest of the five phase peaks plus the client peak. These are the numbers of the benchmark host (12 performance cores, 61 GB of memory): a slower machine takes longer.

| lane | scale | backend id | workload | rows | cell time, median (s) | peak memory, median / max (GiB) | cap in the rows |
|---|---|---|---|---|---|---|---|
| `e2` | `e2` | `arcadedb_e2` | hybrid | 3 | 8 | 2.1 / 2.4 | 12g |
| `e2` | `e2` | `duckdb_e2` | hybrid | 3 | 3 | 0.7 / 0.7 | 12g |
| `l1tpc` | `tpch1` | `arcadedb_embedded` | olap | 3 | 513 | 12.2 / 13.3 | 16g |
| `l1tpc` | `tpch1` | `sqlite` | oltp | 3 | 53 | 1.8 / 1.8 | 16g |
| `l3d` | `small` | `arcadedb_dense_embedded` | all | 3 | 145 | 10.9 / 11.3 | 16g |
| `l3d` | `small` | `sqlite_vec_dense` | all | 3 | 12 | 1.2 / 1.2 | 16g |
| `l2` | `sf1` | `arcadedb_graph_embedded` | oltp | 3 | 575 | 1.4 / 1.4 | 8g |

## Set up

```bash
git clone https://github.com/humemai/mmdbbench.git
cd mmdbbench
```

Every command below runs from `experiments/` inside the clone. The repository's `.python-version` pins Python 3.12 and `uv` finds it from there; from another directory `uv` may pick a newer Python where JPype has no wheel and the build fails (seen 2026-11-21: `Could NOT find Java (missing: Java_JAVAC_EXECUTABLE ...)` while building `jpype1`).

<!-- runnable: enter -->
```bash
cd experiments
```

A cell builds its database at a fixed path under `/tmp` and stops with `Database '/tmp/e2_arcade' already exists` when the path is left over from an earlier run. Remove the paths before you run a cell again:

<!-- runnable: clean -->
```bash
rm -rf /tmp/e2_arcade /tmp/e2_duck.db /tmp/tpc_arcade /tmp/tpc_sqlite.db /tmp/l3d_arcade /tmp/l3d_sqlitevec.db /tmp/l2_arcade
```

The packages are named on the command line, `uv run --no-project --with <package>==<version>`: nothing is installed into your system and nothing is added to the repository. The versions are the ones the published images carry (`experiments/build_images.sh`): `numpy==2.5.3`, `pandas==3.0.6`, `pyarrow==25.0.1`, `duckdb==2.0.1`, and the ArcadeDB wheel of the published rows, `arcadedb-jvm==26.11.1` (the Java engine through JPype) or `arcadedb==26.11.1` (the native build). A test fails when a version on this page differs from `build_images.sh`. A cell writes its result row next to the script, to the file you give with `--out`; delete the rows when you are done.

## The cells

| lane | what it measures | data | the cell |
|---|---|---|---|
| `e2` | one vector search, one graph hop and one record update in one transaction | none, generated | [e2](#e2-the-smallest-cell-about-10-seconds) |
| `l1tpc` | TPC-H SF1 analytics and a New-Order-style transaction mix on documents | generated with DuckDB, 214 MB | [tpch1](#l1tpc-tpc-h-sf1) |
| `l3d` | dense vector search on SIFT1M at a matched HNSW operating point | ann-benchmarks download, 525 MB | [small](#l3d-dense-vectors-sift1m) |
| `l2` | graph reads and writes on the LDBC persons and `KNOWS` graph | LDBC download, 211 MB | [sf1 and hop3f](#l2-graph-ldbc-sf1-and-the-filtered-3-hop-read) |

### e2: the smallest cell, about 10 seconds

The `e2` lane runs 50,000 products with 64-dimensional vectors and about 150,000 edges, generated from a fixed seed, so every run and every engine sees the same catalog. There is no data to fetch. ArcadeDB embedded on the JVM:

<!-- runnable: e2-arcadedb -->
```bash
export ARCADEDB_HEAP=6g              # heap of the engine; the published cap of this cell is 12g
export BENCH_DURABILITY=relaxed      # the default class; strict also flushes the write-ahead log on every commit
uv run --no-project --with arcadedb-jvm==26.11.1 --with numpy==2.5.3 \
  python e2_hybrid.py --backend arcadedb_e2 --workload hybrid --scale e2 --out e2_arcadedb.json
```

The cell prints `PHASE` lines while it runs and ends with one `RESULT {...}` line; the row is also in `e2_arcadedb.json`. Put it next to the published rows of the same cell:

<!-- runnable: e2-compare -->
```bash
uv run --no-project --with pandas==3.0.6 python tools/compare_published.py e2_arcadedb.json \
  --lane e2 --backend arcadedb_e2 --scale e2 --workload hybrid
```

For every timing and recall field that your row shares with the published rows it prints your value, the median of the published repetitions and the ratio, and then whether your answers match theirs (`res_*_digest`: `same` means the published rows hold your digest). The native build is `--with arcadedb==26.11.1` in place of `--with arcadedb-jvm==26.11.1` and nothing else; the row says `engine_backend: native` and the comparison reads the published native rows.

A comparator that needs nothing but a package is DuckDB with its `vss` and `duckpgq` extensions. DuckDB downloads the two extensions from its extension servers on the first run, so the machine needs network access:

<!-- runnable: e2-duckdb -->
```bash
uv run --no-project --with duckdb==2.0.1 --with numpy==2.5.3 --with pyarrow==25.0.1 \
  python e2_hybrid.py --backend duckdb_e2 --workload hybrid --scale e2 --out e2_duckdb.json
```

`--workload atomicity` runs the failure-injection variant of the same lane. The other backends of the lane (`surrealdb_e2`, `ladybug_e2` and the servers) are in `BACKENDS` of `e2_hybrid.py` and pinned in [`COMPARATORS.md`](https://github.com/humemai/mmdbbench/blob/main/experiments/COMPARATORS.md); the server arms need Docker and their pinned images.

### l1tpc: TPC-H SF1

The lane reads `sf1_lineitem.parquet` and `sf1_part.parquet` from `$BENCH_TPC_DATA`. They come from DuckDB's own TPC-H generator, so there is no download and no checksum of a source file. `gen_tpch_parquet.py` writes the two tables in key order and prints their counts and two column sums. Compare them with these before you trust the data:

| table | rows | check |
|---|---|---|
| `lineitem` | 6,001,215 | `sum(l_quantity)` 153,078,795.00, `sum(l_extendedprice)` 229,577,310,901.20 |
| `part` | 200,000 | `sum(p_retailprice)` 299,899,200.00 |

<!-- runnable: tpch1-data -->
```bash
export BENCH_TPC_DATA=$HOME/bench-data/tpch
uv run --no-project --with duckdb==2.0.1 python gen_tpch_parquet.py --sf 1
```

This takes about 10 seconds. DuckDB installs its `tpch` extension on the first call, so the machine needs network access once. The analytics cell of ArcadeDB embedded (five queries, 100 timed runs each):

<!-- runnable: tpch1-arcadedb -->
```bash
export BENCH_TPC_DATA=$HOME/bench-data/tpch
export ARCADEDB_HEAP=8g              # the published cap of this cell is 16g
export BENCH_DURABILITY=relaxed
uv run --no-project --with arcadedb-jvm==26.11.1 --with numpy==2.5.3 --with pandas==3.0.6 --with pyarrow==25.0.1 \
  python l1_tpc.py --backend arcadedb_embedded --workload olap --scale tpch1 --out tpch1_olap_arcadedb.json
```

In the clean-room run on four efficiency cores of a laptop at the lowest priority this cell took 13.5 minutes (810 s) and exited with code 0, and all five answer digests matched the published rows. The rows of the benchmark host sum to 513 s. For a smoke run set `BENCH_OLAP_ITER=5`: the row then records the lower count and is not comparable with a published row.

SQLite is the comparator that needs nothing at all (it is the `sqlite3` of the Python build). Its transaction-mix cell:

<!-- runnable: tpch1-sqlite -->
```bash
export BENCH_TPC_DATA=$HOME/bench-data/tpch
uv run --no-project --with numpy==2.5.3 --with pandas==3.0.6 --with pyarrow==25.0.1 \
  python l1_tpc.py --backend sqlite --workload oltp --scale tpch1 --out tpch1_oltp_sqlite.json
```

Compare a row the same way, for example `python tools/compare_published.py tpch1_olap_arcadedb.json --lane l1tpc --backend arcadedb_embedded --scale tpch1 --workload olap`.

### l3d: dense vectors, SIFT1M

The `small` size is the full SIFT1M corpus of ann-benchmarks: 1,000,000 vectors of 128 dimensions, and exact L2 ground truth for 10,000 queries.

| | |
|---|---|
| Source | <https://ann-benchmarks.com/sift-128-euclidean.hdf5> |
| Size | 525,128,288 bytes |
| SHA-256 of the file we used | `dd6f0a6ed6b7ebb8934680f861a33ed01ff33991eaee4fd60914d854a0ca5984` |

<!-- runnable: sift-data -->
```bash
export BENCH_PREP_DATA=$HOME/bench-data
mkdir -p "$BENCH_PREP_DATA/dense"
curl -4 -fL -C - --retry 5 -o "$BENCH_PREP_DATA/dense/sift-128-euclidean.hdf5" https://ann-benchmarks.com/sift-128-euclidean.hdf5
echo "dd6f0a6ed6b7ebb8934680f861a33ed01ff33991eaee4fd60914d854a0ca5984  $BENCH_PREP_DATA/dense/sift-128-euclidean.hdf5" | sha256sum -c -
uv run --no-project --with h5py --with numpy python gen_dense_npy.py sift
```

The last line turns the HDF5 file into the three `.npy` files the cell reads (`sift_train.npy`, `sift_test.npy` and `sift_neighbors.npy`, 512 MB, 5 MB and 8 MB in `$BENCH_PREP_DATA/dense`). Then ArcadeDB embedded, with the degree-matched index (`maxConnections` 32, which is `M` 16 of the other engines; the reason is at the top of `l3d_dense.py`):

<!-- runnable: l3d-arcadedb -->
```bash
export BENCH_DENSE_DATA=$HOME/bench-data/dense
export ARCADEDB_HEAP=8g              # the published cap of this cell is 16g
export BENCH_DURABILITY=relaxed
uv run --no-project --with arcadedb-jvm==26.11.1 --with numpy==2.5.3 \
  python l3d_dense.py --backend arcadedb_dense_embedded --workload search --scale small --out l3d_small_arcadedb.json
```

In the clean-room run on four efficiency cores at the lowest priority this cell took 9.2 minutes (554 s) and exited with code 0. Its recall at 10 was 0.988 against the published 0.989. The index build was 3.7 times slower than on the benchmark host (536 s against 145 s) and the queries 1.4 to 1.6 times slower, which is what four slow cores do to a graph build. SQLite with the `sqlite-vec` extension is the comparator with the least to install. It is an exact scan, so its recall is 1.0 by construction, and every query reads all 1,000,000 vectors: the cell took 9.5 minutes (567 s) in the clean-room run, so it is the comparator with the least to install and not the quickest.

<!-- runnable: l3d-sqlitevec -->
```bash
export BENCH_DENSE_DATA=$HOME/bench-data/dense
uv run --no-project --with sqlite-vec==0.1.9 --with numpy==2.5.3 \
  python l3d_dense.py --backend sqlite_vec_dense --workload search --scale small --out l3d_small_sqlitevec.json
```

### l2: graph, LDBC SF1, and the filtered 3-hop read

The graph lane reads the persons and `KNOWS` files of the pre-generated LDBC Social Network Benchmark, Interactive v1, scale factor 1, in the `CsvCompositeMergeForeign` layout with the `LongDateFormatter` serializer. It is published by the LDBC council.

| | |
|---|---|
| Source | <https://datasets.ldbcouncil.org/snb-interactive-v1/social_network-sf1-CsvCompositeMergeForeign-LongDateFormatter.tar.zst> |
| Size | 211,535,038 bytes |
| SHA-256 of the file we used | `0b2e240061e51098bc19e9d5ee535cc16d01da522c8aab3d6dfde6350cbe5bf6` |

<!-- runnable: sf1-data -->
```bash
export BENCH_GRAPH_DATA=$HOME/bench-data/ldbc
mkdir -p "$BENCH_GRAPH_DATA/sf1" && cd "$BENCH_GRAPH_DATA/sf1"
curl -4 -fLO -C - --retry 5 https://datasets.ldbcouncil.org/snb-interactive-v1/social_network-sf1-CsvCompositeMergeForeign-LongDateFormatter.tar.zst
echo "0b2e240061e51098bc19e9d5ee535cc16d01da522c8aab3d6dfde6350cbe5bf6  social_network-sf1-CsvCompositeMergeForeign-LongDateFormatter.tar.zst" | sha256sum -c -
tar --zstd -xf social_network-sf1-CsvCompositeMergeForeign-LongDateFormatter.tar.zst
cd - >/dev/null
```

The cell finds the data as `$BENCH_GRAPH_DATA/sf1/social_network-*/dynamic`. It loads only the persons and the friendships: 9,892 persons and 180,623 friendships. Each friendship is stored once, and the questions treat it as undirected. The result rows carry `n_persons` 10,995 for this scale. That number is a constant of the harness that names the scale; it is not a count of what was loaded. The loaded counts are in the row itself (`n_persons_ingested`, `n_edges_ingested`) and in the header of the per-start file described below.

<!-- runnable: hop3f-arcadedb -->
```bash
export BENCH_GRAPH_SOURCE=ldbc        # read the LDBC files; without it the synthetic generator runs
export BENCH_GRAPH_DATA=$HOME/bench-data/ldbc
export ARCADEDB_HEAP=4g               # heap of the engine; the published cap of this cell is 8g
export BENCH_DURABILITY=relaxed
export BENCH_GRAPH_SAMPLES_OUT=$PWD/samples.jsonl   # optional: one record per timed read, see below
uv run --no-project --with arcadedb-jvm==26.11.1 --with numpy==2.5.3 \
  python l2_graph.py --backend arcadedb_graph_embedded --workload oltp --scale sf1 --out hop3f_sf1.json
```

In the clean-room run on four efficiency cores of a laptop at the lowest priority the whole sequence of the blocks above (the download was already there, the cell, and the per-start report below) took 8.4 minutes (504 s) and exited with code 0. The row had `hop3f_p50_ms` 270 against the published 330, and the answer digests matched. There is no switch for one operation: the cell times the point read, the one-hop, two-hop and filtered three-hop reads in turn, and then the writes. The database is created fresh at `/tmp/l2_arcade` (about 11 MB) in every run; delete it when you are done.

The query of the filtered 3-hop read is in [`graph_common.py`](https://github.com/humemai/mmdbbench/blob/main/experiments/graph_common.py):

```
MATCH (p:Person)-[:KNOWS]-(:Person)-[:KNOWS]-(:Person)-[:KNOWS]-(x:Person)
WHERE p.id = $id AND x.age > 41 RETURN count(DISTINCT x) AS n
```

The 500 start persons are drawn with a fixed seed (777) from the persons file, so every run asks for the same starts. The timer covers planning, execution, the iteration of the result and its conversion to Python objects.

## The same cell on another build or engine

- **Embedded, native build.** Replace `--with arcadedb-jvm==26.11.1` by `--with arcadedb==26.11.1` in any command above. The native package has no JVM: it reads `-Xmx` and the system properties from `ARCADEDB_NATIVE_ISOLATE_ARGS`, and the harness turns `ARCADEDB_HEAP` and the durability flag into that for you. The row says `engine_backend: native`.
- **Served ArcadeDB and the comparators that run as servers.** They run through `runner.py`, which starts the server in a container pinned by image digest, gives the server and the client container one cpuset and a split memory cap, and writes the row to `experiments/results/runs.jsonl`. All 18 images the runner pins by digest can be pulled by anyone (checked 2026-11-25). The runner needs Docker and the benchmark images that `build_images.sh` builds. For ArcadeDB it also needs a server image of the same engine commit as the wheel (`ARCADEDB_WHEEL` and `ARCADEDB_SERVER_IMAGE`, set together): the published 26.11.1 server rows ran from such a build, whose recipe `build_matched_pair.sh` needs a checkout of the Python bindings, which is not in this repository. Without it the runner uses the stock 26.8.1 server image, and the rows say so. There is no one-command path for a served cell yet; the work is tracked in the issue list of this repository and the steps are in [`experiments/CAMPAIGN.md`](https://github.com/humemai/mmdbbench/blob/main/experiments/CAMPAIGN.md).
- **Other embedded comparators** (`duckdb`, `sqlite`, `ladybug_graph`, `surrealdb_*`) name their package in `experiments/build_images.sh` (the `PKGS` table) and take the same command line with `--with <package>==<version>` in place of the ArcadeDB wheel.

## Environment variables

The cells read these, and the row records what ran.

| variable | default | meaning |
|---|---|---|
| `ARCADEDB_HEAP` | `4g` | `-Xmx` of the engine; the runner sets it per scale (`HEAP_BY_SCALE` in `runner.py`) |
| `BENCH_DURABILITY` | `relaxed` | `relaxed` does not wait for the disk at commit; `strict` flushes the write-ahead log on every commit. Every engine has a relaxed and a strict setting that the row names |
| `BENCH_TPC_DATA` | `/data/tpch` | directory with `sf1_lineitem.parquet` and `sf1_part.parquet` (`l1tpc`); `gen_tpch_parquet.py` writes there too |
| `BENCH_DENSE_DATA` | `/data/dense` | directory with the three `sift_*.npy` files (`l3d`) |
| `BENCH_PREP_DATA` | `experiments/data` | root of `gen_dense_npy.py`: it reads and writes `$BENCH_PREP_DATA/dense` |
| `BENCH_GRAPH_SOURCE`, `BENCH_GRAPH_DATA` | synthetic, `/data/ldbc` | `ldbc` reads the LDBC files from `$BENCH_GRAPH_DATA/<scale>` |
| `BENCH_GRAPH_SAMPLES_OUT` | unset | writes one record per timed read of the graph cell |
| `BENCH_OLAP_ITER`, `E2_OPS` | 100, 300 | number of timed runs; lower them for a smoke run. The row records what ran (`olap_iters`), and a row with fewer runs is not comparable with a published one |
| `BENCH_DUCKDB_THREADS` | the size of the cpuset | DuckDB's thread count; the fairness rule holds it to the cores the cell has |
| `BENCH_CPUSET`, `BENCH_DATA` | `0-11`, `experiments/data` | `runner.py` only: the cores of the containers and the corpus root it mounts as `/data` |

The complete list is the `bench_env` tuple in `experiments/runner.py`.

## What it writes

`--out` is the result row of the cell: a JSON object with one entry per measurement. For each timed read it holds the median, the 95th and the 99th percentile in milliseconds (for example `hop3f_p50_ms`, `retrieval_p99_ms`), the build, ingest and index times in seconds, the answer digests (`res_*_digest`), the engine and wheel versions, the heap and the durability class. [Result rows](results-schema.md) lists the fields. The runner writes the same rows to `experiments/results/runs.jsonl`; a cell run by hand writes `--out` and prints the `RESULT` line.

`samples.jsonl` exists only when `BENCH_GRAPH_SAMPLES_OUT` is set; it is written after the row, so it cannot change a measurement. The first line is a header with the run's identifying fields and the counts of persons and edges the cell loaded. Every further line is one timed read: `op`, `pass` (1 or 2), `position`, `start_id`, `latency_ms`, `answer` and `discarded` (the first reads of a pass are not counted in the percentiles). The percentiles in the row are over the reads that are not discarded.

## Compare with the published rows

`tools/compare_published.py` (shown in the e2 section) is the whole comparison: your value, the published median over the three repetitions, the ratio, and whether your answer digests match. Read it in this order.

- The answer digests first. A `DIFFERENT` digest means your engine, data or version returned another answer, and no timing is comparable until that is explained.
- Then the ratios between fields, not the absolute values. If your machine is 2 times slower, every timing is about 2 times larger and the shape stays: which query is the long one, the recall, the build time against the query time.
- The published rows were measured with the cell pinned to 12 performance cores and nothing else running. The page shows the same rows by table.

## Reading the latency per start

The work of a filtered 3-hop read grows with the number of three-relationship paths that start at the person, and in a social graph that number differs by orders of magnitude between persons, so one median hides a long tail of heavy starts. [`experiments/tools/walks_per_start.py`](https://github.com/humemai/mmdbbench/blob/main/experiments/tools/walks_per_start.py) counts those paths for every person from the two CSV files alone, without any engine, and compares them with the latencies of a run:

<!-- runnable: walks-per-start -->
```bash
uv run --no-project python tools/walks_per_start.py --data "$BENCH_GRAPH_DATA" --samples samples.jsonl
```

It prints the walks per person for the whole corpus, the latency and walks of the timed starts, the rank correlation of the two, and the microseconds per walk. This is the output of the clean-room run above, on four efficiency cores of a laptop at the lowest priority:

```
corpus: 9892 persons, 180623 friendships
3-hop walks per person: p50 331073  p95 1238493  p99 2219364  max 6577302
samples: 9892 persons and 180623 edges ingested by the cell, 990 timed hop3f reads
latency ms: p50 276.4  p95 840.3  p99 1297.0
walks per timed start: p50 339781  p95 1026327  p99 1792149
Spearman(latency, walks) = 0.996; microseconds per walk: median 0.79, p5 0.75, p95 0.94
```

The latency of every start was close to proportional to its walk count, at about 0.8 microseconds per walk on that machine; the walks per person (the first two lines) are a property of the data and are the same on every machine. This shows how the latency spreads over the starts. It does not explain why a walk costs what it does. If your graph is smaller or less connected than the LDBC SF1 persons graph, the walks per start are fewer and the latencies are lower for that reason alone, so compare the walks per start before comparing the latencies.

## Settings that matter for a fair comparison

Keep these the same for every engine you compare, and the same as the published rows when you compare with them. The full list, with what enforces each rule, is [`experiments/PROTOCOL.md`](https://github.com/humemai/mmdbbench/blob/main/experiments/PROTOCOL.md), and what "the same thing" means is [`experiments/FAIRNESS.md`](https://github.com/humemai/mmdbbench/blob/main/experiments/FAIRNESS.md).

- **Memory.** The heap is half of the memory cap of the cell (`HEAP_BY_SCALE` and `MEM_BY_SCALE` in `runner.py`; the caps are in the last column of the table above). Give every JVM engine the same heap, and run each engine inside the same cap. A heap near the cap makes the kernel kill the process instead of raising an out-of-memory error.
- **Cores.** The published cells run on a fixed set of cores, one cell at a time, with nothing else running. Pin your run (for example `taskset -c 0-7 uv run ...`) and do not run two cells at once. DuckDB's thread count follows the cores of the cell.
- **Durability.** One class for every engine (`BENCH_DURABILITY`). The default `relaxed` is a commit that does not wait for the disk; compare relaxed with relaxed.
- **SQLite and DuckDB versions.** `sqlite` is the library inside your Python build and DuckDB is the pinned package, so read `engine_version` of your row: the published SQLite rows ran 3.46.1 (the `python:3.12-slim` image) and the Python that `uv` fetches can carry another one. The comparison tool prints both versions.
- **Engine version.** The published rows name the wheel (`engine_version`, `engine_backend`) and the commit it was built from. Use the same version, and read both fields of your row before you compare. A different version is a different measurement.
- **Defaults.** Engines run at their documented defaults with a few declared exceptions; the page lists each one. Do not add a tuning flag to one engine.
- **Data.** The same corpus (the checksums above) and the same scale. The row carries the counts of what was loaded.
- **Repetitions.** The published rows are three repetitions of each cell, one fresh process per repetition. Run it three times and take the median; one run is a smoke test.

## What needs the benchmark host

The cells above run on a laptop with 16 GB of memory. These do not:

- The large sizes (`tpch10`, the `sf10` graph, the ten-million-vector dense cells, the 8.84-million sparse corpus, the 1,000-host time series) need 24 to 48 GB of memory in one cap and hours of run time. They are not rerun before February 2027.
- The served ArcadeDB arms and the comparators that run as servers need Docker, the images that `build_images.sh` builds, and for ArcadeDB a server image built from the engine commit of the wheel; that build needs a checkout of the Python bindings, which is not in this repository.
- Published numbers come from one host at a time with the cores pinned and no other load. The helper in `experiments/host/` installs a root-owned file and only matters for the memory peaks per phase, which the row marks as absent when it is not installed.

## Known issue: the native server at 10 million vectors

The two dense-vector cells with ten million vectors on the native ArcadeDB server end with an out-of-memory error during the index build, with the default settings. The published rows show that failure. A server flag made the same cells finish in our tests, but it is a workaround whose cause is not known, so the published rows do not use it. The report is [ArcadeData/arcadedb#12639](https://github.com/ArcadeData/arcadedb/issues/12639), closed on 2026-11-21; the fix in flight is [ArcadeData/arcadedb#12675](https://github.com/ArcadeData/arcadedb/pull/12675), still open. The tracking issue is [#99](https://github.com/humemai/mmdbbench/issues/99): the two cells are rerun with the large sizes after February 2027.

## Questions about a result

If your numbers differ from a published row, or this page is wrong or unclear, open an issue in this repository with the command you ran, the engine version, and the row or samples file. The aim is that a reader never needs to ask anyone for the command, the data or the settings.
