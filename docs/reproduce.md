# Reproduce

Every published number can be repeated on your own hardware. The benchmark runs each engine in a container pinned by image digest (or an installed package pinned by version) and writes one result row per measurement; the tables on the results page are generated from those rows. This page shows how to run one cell on a clean checkout, using the filtered 3-hop read of the graph lane (`hop3f`) as the example. Nothing here needs a private file or the benchmark host.

A reproduction is comparable when it keeps the memory cap, the durability class and the corpus the same, and compares engines on the same machine. Absolute times on different hardware differ; the order of engines and the size of the gaps are what a reproduction should be compared on. The rest of the protocol is in [Methodology](methodology.md) and in [`experiments/PROTOCOL.md`](https://github.com/humemai/mmdbbench/blob/main/experiments/PROTOCOL.md).

## What you need

- A Linux machine on x86-64, [`uv`](https://docs.astral.sh/uv/), and a clone of this repository. Python 3.11 to 3.14 is fetched by `uv`.
- No Java installation: the `arcadedb-jvm` package bundles its own runtime. Docker is needed only for the cells that run a server or a comparator engine, not for the command below.
- About 1.1 GB of disk for the SF1 data (a 211 MB download, 888 MB extracted) and a few GB of memory. The published rows used a 4 GB heap inside an 8 GB cap.

## The data

The graph lane reads the persons and `KNOWS` files of the pre-generated LDBC Social Network Benchmark, Interactive v1, scale factor 1, in the `CsvCompositeMergeForeign` layout with the `LongDateFormatter` serializer. It is published by the LDBC council.

| | |
|---|---|
| Source | <https://datasets.ldbcouncil.org/snb-interactive-v1/social_network-sf1-CsvCompositeMergeForeign-LongDateFormatter.tar.zst> |
| Size | 211,535,038 bytes |
| SHA-256 of the file we used | `0b2e240061e51098bc19e9d5ee535cc16d01da522c8aab3d6dfde6350cbe5bf6` |

```bash
export BENCH_GRAPH_DATA=$HOME/bench-data/ldbc
mkdir -p "$BENCH_GRAPH_DATA/sf1" && cd "$BENCH_GRAPH_DATA/sf1"
curl -LO https://datasets.ldbcouncil.org/snb-interactive-v1/social_network-sf1-CsvCompositeMergeForeign-LongDateFormatter.tar.zst
echo "0b2e240061e51098bc19e9d5ee535cc16d01da522c8aab3d6dfde6350cbe5bf6  social_network-sf1-CsvCompositeMergeForeign-LongDateFormatter.tar.zst" | sha256sum -c -
tar --zstd -xf social_network-sf1-CsvCompositeMergeForeign-LongDateFormatter.tar.zst
```

The cell finds the data as `$BENCH_GRAPH_DATA/sf1/social_network-*/dynamic`. It loads only the persons and the friendships: 9,892 persons and 180,623 friendships. Each friendship is stored once, and the questions treat it as undirected.

The result rows carry `n_persons` 10,995 for this scale. That number is a constant of the harness that names the scale; it is not a count of what was loaded. The loaded counts are in the row itself (`n_persons_ingested`, `n_edges_ingested`) and in the header of the per-start file described below.

## Run the cell

```bash
cd experiments
export BENCH_GRAPH_SOURCE=ldbc        # read the LDBC files; without it the synthetic generator runs
export BENCH_GRAPH_DATA=$HOME/bench-data/ldbc
export ARCADEDB_HEAP=4g               # heap of the engine
export BENCH_DURABILITY=relaxed       # the default class; strict also flushes the write-ahead log on every commit
export BENCH_GRAPH_SAMPLES_OUT=$PWD/samples.jsonl   # optional: one record per timed read, see below
uv run --no-project --with arcadedb-jvm==26.11.1 python l2_graph.py \
  --backend arcadedb_graph_embedded --workload oltp --scale sf1 --out hop3f_sf1.json
```

This is the command we ran from a clean checkout of this repository. It finished in about 12 minutes on the benchmark host, with exit code 0. There is no switch for one operation: the cell times the point read, the one-hop, two-hop and filtered three-hop reads in turn, and then the writes. The database is created fresh at `/tmp/l2_arcade` (about 11 MB) in every run; delete it when you are done.

The query of the filtered 3-hop read is in [`graph_common.py`](https://github.com/humemai/mmdbbench/blob/main/experiments/graph_common.py):

```
MATCH (p:Person)-[:KNOWS]-(:Person)-[:KNOWS]-(:Person)-[:KNOWS]-(x:Person)
WHERE p.id = $id AND x.age > 41 RETURN count(DISTINCT x) AS n
```

The 500 start persons are drawn with a fixed seed (777) from the persons file, so every run asks for the same starts. The timer covers planning, execution, the iteration of the result and its conversion to Python objects.

## What it writes

`hop3f_sf1.json` is the result row of the cell. For each read it holds the median, the 95th and the 99th percentile in milliseconds (for example `hop3f_p50_ms`), the engine and wheel versions, the heap and the cores. [Result rows](results-schema.md) lists the fields.

`samples.jsonl` exists only when `BENCH_GRAPH_SAMPLES_OUT` is set; it is written after the row, so it cannot change a measurement. The first line is a header with the run's identifying fields and the counts of persons and edges the cell loaded. Every further line is one timed read: `op`, `pass` (1 or 2), `position`, `start_id`, `latency_ms`, `answer` and `discarded` (the first reads of a pass are not counted in the percentiles). The percentiles in the row are over the reads that are not discarded.

## Reading the latency per start

The work of a filtered 3-hop read grows with the number of three-relationship paths that start at the person, and in a social graph that number differs by orders of magnitude between persons, so one median hides a long tail of heavy starts. [`experiments/tools/walks_per_start.py`](https://github.com/humemai/mmdbbench/blob/main/experiments/tools/walks_per_start.py) counts those paths for every person from the two CSV files alone, without any engine, and compares them with the latencies of a run:

```bash
uv run python tools/walks_per_start.py --data "$BENCH_GRAPH_DATA" --samples samples.jsonl
```

It prints the walks per person for the whole corpus, the latency and walks of the timed starts, the rank correlation of the two, and the microseconds per walk. This is the output of the run above, on the benchmark host's efficiency cores at the lowest priority, so its absolute latencies are higher than the published rows:

```
corpus: 9892 persons, 180623 friendships
3-hop walks per person: p50 331073  p95 1238493  p99 2219364  max 6577302
samples: 9892 persons and 180623 edges ingested by the cell, 824 timed hop3f reads
latency ms: p50 514.3  p95 1485.5  p99 2639.6
walks per timed start: p50 339781  p95 995687  p99 1792149
Spearman(latency, walks) = 1.000; microseconds per walk: median 1.51, p5 1.48, p95 1.54
```

In that run, the latency of every start was proportional to its walk count, at about 1.5 microseconds per walk. This shows how the latency spreads over the starts. It does not explain why a walk costs what it does. If your graph is smaller or less connected than the LDBC SF1 persons graph, the walks per start are fewer and the latencies are lower for that reason alone, so compare the walks per start before comparing the latencies.

## Other cells and engines

The cells of the other lanes, the comparator engines and the served and native arms are described in [`experiments/README.md`](https://github.com/humemai/mmdbbench/blob/main/experiments/README.md) and [`experiments/PROTOCOL.md`](https://github.com/humemai/mmdbbench/blob/main/experiments/PROTOCOL.md). The runbook of the benchmark host, [`CAMPAIGN.md`](https://github.com/humemai/mmdbbench/blob/main/experiments/CAMPAIGN.md), is in the same directory.

## Known issue: the native server at 10 million vectors

The two dense-vector cells with ten million vectors on the native ArcadeDB server end with an out-of-memory error during the index build, with the default settings. The published rows show that failure. A server flag made the same cells finish in our tests, but it is a workaround whose cause is not known, so the published rows do not use it. The report is [ArcadeData/arcadedb#12639](https://github.com/ArcadeData/arcadedb/issues/12639) and the tracking issue is [#99](https://github.com/humemai/mmdbbench/issues/99).

## Questions about a result

If your numbers differ from a published row, or this page is wrong or unclear, open an issue in this repository with the command you ran, the engine version, and the row or samples file. The aim is that a reader never needs to ask anyone for the command, the data or the settings.
