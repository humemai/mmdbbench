# Changelog

Changes to the protocol, newest first. Engine versions are not listed here; they are on every result row.

## 2026-11 (in development)

The benchmark was renamed from DBBench to MMDBBench on 2026-11-07 and refocused on multi-model databases. The protocol version is unchanged.

The protocol version, in development until its first release. The method is described on the [Methodology](methodology.md) page.

Method changes made while it is in development, before any result is published with them:

- Served ArcadeDB leaves the initial heap (`-Xms`) unset, like embedded ArcadeDB. Neo4j and Elasticsearch keep a pinned initial heap, as their vendors recommend.
- Neo4j's heap and page cache come from its own `neo4j-admin server memory-recommendation` for each memory cap. Elasticsearch's heap is the smaller of the tier heap, 50% of the cap and 26 GiB.
- Container io figures count a stacked block device once. Earlier rows summed every device line of the cgroup `io.stat`, which counted the benchmark machine's NVMe disk and the device-mapper device on top of it twice. The harness now stamps `io_stat_dedup: 1` into each row, and the frozen table halves the io figures of rows without the stamp (see [Result rows](results-schema.md)).
- Each cell is run three times and no more. The plan to add a fourth and a fifth repetition after the third was dropped on 2026-11-14: three repetitions are enough for the claims the page makes, and the machine time goes to reruns of changed cells instead.
- Milvus runs as 3.0.3 on the vendor's Docker Compose standalone (three containers sharing the cell's memory cap), ingests by bulk import, waits for every segment to be flushed and the index to be finished before timed searches, and records the storage mode, the output fields and the filter. Storage V3 is a sensitivity setting.

## 2026-10

A development release, superseded by 2026-11 before any comparison was published from it.
