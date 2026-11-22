# Rename map

The ids in the rows, the code and the documents are not uniform: lane codes beside plain words, four styles of size name, two spellings of one engine. [humemai/mmdbbench#122](https://github.com/humemai/mmdbbench/issues/122) proposes one naming pass. This file is its map: every id as it is today, the new name where the issue proposes one, and where each id is written, so the pass knows what changes together and what needs a compatibility read.

**Nothing is renamed yet.** The issue moved the rename to after the 26.12.1 rerun has landed, together with #118. Until then the left column is what the code, the rows and the page payload use.

How to read the columns:

- **proposed** is what the issue says. "no proposal" means the issue names nothing for that id; "unchanged" means the issue says to keep it.
- **suggestion** is not from the issue. It is one possible name with one reason, following the issue's rule: a size is named by what it holds, in the unit its own community uses, and the dataset name lives in its own field. An empty cell means no suggestion. A suggestion decides nothing.
- **frozen rows** is the number of rows in `results/runs_paper.csv` that carry the id (in `lane`, `scale` or `backend`). The file holds 708 rows today, in the lanes `e2`, `l1tpc`, `l2`, `l3d`.
- **payload** is whether `results/web_benchmarks.json`, the file the page reads, carries the id today.
- **written in** is four file counts: code / tests / documents / data files. Code and tests count the Python files under `experiments/` that hold the id as a quoted string. Documents count the Markdown files in `experiments/`, `docs/` and the root `README.md` that hold it as a word. Data files count the `.json`, `.sh` and `.sha256` files at the top of `experiments/`. An id that is also an ordinary word or an engine name (`small`, `restart`, `e2`, `duckdb`) is over-counted in documents.

When the rename is applied, each row gets the date in an `applied` column and the file becomes append-only (old id, new id, date), as the issue plans.

## Lane ids

A lane is a key of `runner.LANES`. It is the `lane` field of every row, a `--lanes` argument, a key of `LANE_CORPUS` and of the stage list, and part of file names.

| lane | script | proposed | suggestion | frozen rows | written in |
|---|---|---|---|---|---|
| `e4` | `e4_decomp.py` | no proposal | none (the issue waits for its spec) | 0 | 7 / 5 / 4 / 1 |
| `l1` | `l1_tabular.py` | no proposal | none (the lane has no frozen rows and no page table; decide whether it stays before naming it) | 0 | 8 / 7 / 4 / 2 |
| `l2` | `l2_graph.py` | `graph` |  | 189 | 26 / 44 / 7 / 6 |
| `l1tpc` | `l1_tpc.py` | `document` |  | 216 | 18 / 23 / 6 / 3 |
| `e2` | `e2_hybrid.py` | no proposal | `crossmodel` (one lane, two tables, as the issue does for `graph`) | 234 | 17 / 19 / 7 / 2 |
| `lifecycle` | `l5_lifecycle.py` | unchanged |  | 0 | 15 / 9 / 8 / 2 |
| `restart` | `l6_restart.py` | no proposal | unchanged (already a plain word) | 0 | 9 / 7 / 6 / 1 |
| `l3s` | `l3_sparse.py` | no proposal | `vector_sparse` (same reason) | 0 | 17 / 15 / 5 / 2 |
| `l3d` | `l3d_dense.py` | no proposal | `vector_dense` (the issue gives this as the table id; the lane and its one table can share it) | 69 | 17 / 30 / 5 / 3 |
| `l4` | `l4_tsbs.py` | no proposal | `timeseries` (same reason) | 0 | 15 / 13 / 7 / 4 |

The issue gives lane names only for `l1tpc` (`document`) and `l2` (`graph`, "one lane"). For `l3d`, `l3s`, `l4` and `e2` it gives table ids, in the next section, and does not say what the lane is called.

File names carry lane codes too. 23 files under `experiments/` (outside `results/`, `fixtures/` and `evidence/`; 15 without the tests) have one of `l1`, `l1tpc`, `l2`, `l3`, `l3d`, `l3s`, `l4`, `l5`, `l6`, `e2`, `e3`, `e4` as a part of their name:

`e2_hybrid.py`, `e3_recovery.py`, `e4_decomp.py`, `l1_tabular.py`, `l1_tpc.py`, `l2_graph.py`, `l3_sparse.py`, `l3d_dense.py`, `l4_tsbs.py`, `l5_lifecycle.py`, `l5_lifecycle_embedded.py`, `l5_lifecycle_server.py`, `l5_lifecycle_sql.py`, `l5_lifecycle_surreal.py`, `l6_restart.py`, `test_e2_recall_point.py`, `test_e4_client_axis.py`, `test_l2_samples.py`, `test_l4_analyze.py`, `test_l4_arrow_digest_gate.py`, `test_l6_restart_reattach.py`, `test_landing_gates_l3d.py`, `test_provenance_scope_l4.py`.

120 of the 235 Python files under `experiments/` hold at least one lane id as a quoted string.

## Table ids

A table id is the `id` of a table in the page payload. The site names each table by this id (`tableId` in `src/lib/dbbench/lanes.ts` of the humem.ai checkout, see PUBLISHING.md), and `page_check.py` keys its column lists by it. "rows from" is the lane and workload the exporter reads for the table (`export_web._TABLE_LANE`).

| table id | page title | rows from | proposed | suggestion | payload | written in |
|---|---|---|---|---|---|---|
| `docs_oltp` | Document OLTP | `l1tpc`, `oltp` | `document_oltp` |  | yes | 5 / 14 / 3 / 1 |
| `docs_olap` | Document OLAP | `l1tpc`, `olap` | `document_olap` |  | yes | 5 / 12 / 3 / 0 |
| `l2` | Graph OLTP | `l2`, `oltp` | `graph_oltp` |  | yes | 26 / 44 / 7 / 6 |
| `l2olap` | Graph OLAP | `l2`, `olap` | `graph_olap` |  | yes | 5 / 8 / 3 / 0 |
| `l3d` | Dense vector search | `l3d`, every workload | `vector_dense` |  | yes | 17 / 30 / 5 / 3 |
| `l3s` | Sparse vector search | `l3s`, every workload | `vector_sparse` |  | no | 17 / 15 / 5 / 2 |
| `l4` | Time series | `l4`, every workload | `timeseries` |  | no | 15 / 13 / 7 / 4 |
| `e2` | Cross-model transaction | `e2`, `hybrid` | `crossmodel_tx` |  | yes | 17 / 19 / 7 / 2 |
| `e2atom` | Cross-model transaction: what survives a crash | `e2`, `atomicity` | `crossmodel_crash` |  | yes | 4 / 4 / 3 / 0 |
| `lifecycle` | Session cost, open to close | `lifecycle`, every workload | unchanged |  | no | 15 / 9 / 8 / 2 |
| `restart` | Server restart | `restart`, `restart` | no proposal | unchanged (already a plain word, like `durability`) | no | 9 / 7 / 6 / 1 |
| `l1tpc` | Documents (TPC-H and TPC-C shapes) | not in `_TABLE_LANE` (derived, a table spec, or its own artifact) | no proposal | none (a table spec in the exporter, not a table on the page: it becomes `docs_oltp` and `docs_olap`) | no | 18 / 23 / 6 / 3 |
| `e4` | What the client/server split costs | not in `_TABLE_LANE` (derived, a table spec, or its own artifact) | no proposal ("named after reading their specs") |  | no | 7 / 5 / 4 / 1 |
| `multimodel` | What the four multi-model engines cover | not in `_TABLE_LANE` (derived, a table spec, or its own artifact) | unchanged |  | yes | 5 / 2 / 3 / 0 |
| `pycost` | What Python costs | not in `_TABLE_LANE` (derived, a table spec, or its own artifact) | no proposal ("named after reading their specs") |  | no | 2 / 1 / 3 / 0 |
| `pyb_tabular` | none in the exporter | not in `_TABLE_LANE` (derived, a table spec, or its own artifact) | no proposal |  | no | 1 / 0 / 1 / 0 |
| `pyb_graph` | none in the exporter | not in `_TABLE_LANE` (derived, a table spec, or its own artifact) | no proposal |  | no | 1 / 0 / 1 / 0 |
| `pyb_vector` | none in the exporter | not in `_TABLE_LANE` (derived, a table spec, or its own artifact) | no proposal |  | no | 1 / 0 / 1 / 0 |
| `l3smp` | Sparse search: what a second pass buys | not in `_TABLE_LANE` (derived, a table spec, or its own artifact) | no proposal | `vector_sparse_second_pass` (follows `vector_sparse` and the table's title) | no | 2 / 0 / 2 / 0 |
| `durability` | What waiting for the disk costs | not in `_TABLE_LANE` (derived, a table spec, or its own artifact) | unchanged |  | yes | 16 / 5 / 14 / 0 |

9 ids are a lane id and a table id at once (`l2`, `l3d`, `l3s`, `l4`, `e2`, `lifecycle`, `restart`, `l1tpc`, `e4`), and `e2` is also a size id. A rename by word boundary cannot tell these uses apart, so each use has its own row in this file.

`l2olap` has no lane: its rows are stored under lane `l2` with size `sf1full`. `docs_oltp` and `docs_olap` are the two workloads of lane `l1tpc`. `e2atom` is the `atomicity` workload of lane `e2`.

## Size ids

A size id is the `scale` field of a row and a key of `MEM_BY_SCALE`, `TIMEOUT_BY_SCALE` and `HEAP_BY_SCALE` in `runner.py`. Those three tables are keyed by the size id alone, not by lane. The page label is `export_web.SCALE_LABELS`, keyed by lane and size. The page also says whether a size is the small or the large one of its table: `export_web.SIZE_CLASS`, keyed the same way, gives each size its class (`small`, `large`, or `extra` for a size outside the pair), and the Size label on the page starts with that word (humemai/mmdbbench#131). A rename of a size id changes its key in both tables.

| size id | used by (lane: page label) | proposed | suggestion | frozen rows | payload | written in |
|---|---|---|---|---|---|---|
| `micro` | no page label | no proposal | unchanged (no frozen row uses it) | 0 | no | 6 / 13 / 6 / 1 |
| `tiny` | `l3s`: 100k vectors | `100k` |  | 0 | no | 11 / 7 / 5 / 3 |
| `small` | `l3s`: 1M vectors; `l3d`: 1M vectors; `restart`: dense vectors, 1M (SIFT) | `1m` (dense and sparse; on the dense table the dataset goes in a `dataset` field) |  | 36 | yes | 16 / 13 / 9 / 2 |
| `medium` | `l3s`: 8.84M vectors | `full` |  | 0 | no | 14 / 4 / 2 / 2 |
| `large` | no page label | no proposal | unchanged (no frozen row uses it) | 0 | no | 5 / 1 / 6 / 1 |
| `lc10k` | `lifecycle`: 10k | no proposal | unchanged (see "Ids that would merge") | 0 | no | 7 / 1 / 1 / 2 |
| `lc100k` | `lifecycle`: 100k | no proposal | unchanged (same) | 0 | no | 7 / 1 / 1 / 2 |
| `lc1m` | `lifecycle`: 1M | no proposal | unchanged (same) | 0 | no | 6 / 1 / 3 / 2 |
| `lc10m` | `lifecycle`: 10M | no proposal | unchanged (same) | 0 | no | 6 / 1 / 3 / 2 |
| `ts100` | `l4`: computed, `f"{_l4_points('ts100')} points"`; `restart`: computed, `f"time series, {_l4_points('ts100')} points"` | `100hosts` |  | 0 | no | 9 / 2 / 3 / 2 |
| `sf1` | `l2`: SF1 (11k people); `restart`: graph, LDBC SF1 (11k people) | `sf1` |  | 72 | yes | 12 / 15 / 3 / 2 |
| `sf10` | `l2`: SF10 (73k people); `restart`: graph, LDBC SF10 (73k people) | `sf10` |  | 72 | yes | 12 / 8 / 2 / 2 |
| `deep10m` | `l3d`: 9.99M vectors; `restart`: dense vectors, 9.99M (Deep) | `10m` (the dataset goes in a `dataset` field) |  | 33 | yes | 16 / 14 / 6 / 2 |
| `e2` | `e4`: 50k products; `e2`: computed, `f"{_e2_products('e2')} products"` | `50k` |  | 126 | yes | 17 / 19 / 7 / 2 |
| `tpch1` | `l1tpc`: TPC-H SF1 (6.0M line items); `restart`: documents, TPC-H SF1 (6.0M line items) | `sf1` |  | 120 | yes | 13 / 14 / 4 / 3 |
| `tpch10` | `l1tpc`: TPC-H SF10 (60.0M line items); `restart`: documents, TPC-H SF10 (60.0M line items) | `sf10` |  | 96 | yes | 7 / 8 / 3 / 3 |
| `sf1full` | `l2`: computed, `f"SF1, full network ({_l2_full_network('sf1full')})"` | `sf1` (the table says projection or full, not the size) |  | 45 | yes | 8 / 13 / 3 / 2 |
| `ts1000` | `l4`: computed, `f"{_l4_points('ts1000')} points (1,000 hosts)"`; `restart`: computed, `f"time series, {_l4_points('ts1000')} points (1,000 hosts)"` | `1000hosts` |  | 0 | no | 8 / 1 / 3 / 3 |
| `e2_500k` | `e2`: computed, `f"{_e2_products('e2_500k')} products"` | `500k` |  | 108 | yes | 6 / 4 / 3 / 2 |

Frozen rows per lane and size: `e2` `e2` 126, `e2` `e2_500k` 108, `l1tpc` `tpch1` 120, `l1tpc` `tpch10` 96, `l2` `sf1` 72, `l2` `sf10` 72, `l2` `sf1full` 45, `l3d` `deep10m` 33, `l3d` `small` 36.

`LARGE_SCALES` in `runner.py` is `deep10m`, `tpch10`, `sf1full`. `SCALE_ORDER` in `export_web.py`, which sorts the rows of a table, is `tiny`, `small`, `medium`, `large`, `deep10m`, `sf1`, `sf10`, `tpch1`, `tpch10`, `lc10k`, `lc100k`, `lc1m`, `lc10m`.

### Ids that would merge

The proposal gives one new id to sizes that are separate ids today. Because the per-size tables in `runner.py` are keyed by the size alone, each pair below needs a check before it merges:

| today | today | one new id | memory cap | timeout s | heap |
|---|---|---|---|---|---|
| `tpch1` | `sf1` | `sf1` | 16g and 8g (differ) | 10800 and 3600 (differ) | 8g and 4g (differ) |
| `tpch10` | `sf10` | `sf10` | 32g and 24g (differ) | 7200 and 28800 (differ) | 16g and 12g (differ) |
| `sf1full` | `sf1` | `sf1` | 32g and 8g (differ) | 7200 and 3600 (differ) | 16g and 4g (differ) |

Where the values differ, the tables must be keyed by lane and size (or by table and size) before the ids merge, or one of the two cells gets the other's envelope.

The `restart` lane is the hardest case. Its sizes are borrowed from four other lanes and the size alone says which model a row restarts (`tpch1` documents, `sf1` graph, `small` dense vectors, `ts100` time series; see the comment above `"restart"` in `runner.LANES`). With `tpch1` and `sf1` both renamed `sf1`, a restart row no longer says which model it holds, so the lane needs its own field for the model first.

`small` is one id for two corpora today (the dense 1M and the sparse 1M), and both become `1m`, so that pair does not change. `lc1m` and `lc10m` would collide with `1m` and `10m` if the `lc` prefix were dropped, which is why the suggestion keeps them.

## Backend ids

A backend id is a key of `runner.BACKENDS` (99 today) and the `backend` field of every row. The payload carries it as `backend_key`, and the page shows the name from `export_web.DISPLAY_NAMES` (103 entries; an id with no entry falls back to `display_name`, which prints `ArcadeDB` for an `arcadedb` id and the id with spaces otherwise).

The issue proposes two changes and leaves the rest alone: one spelling, `pg_age`, for PostgreSQL with AGE, and one suffix for the documents-lane arms, which carry `_tpc` or no suffix today.

| backend id | page name | lanes | proposed | suggestion | frozen rows | payload | written in |
|---|---|---|---|---|---|---|---|
| `arcadedb_embedded` | ArcadeDB (embedded) | `l1`, `l1tpc`, `lifecycle` | one suffix for the documents-lane arms (the issue does not name it) | none: also an arm of `l1`, `lifecycle`, so a suffix would split one id into several | 36 | yes | 15 / 14 / 4 / 3 |
| `arcadedb_server` | ArcadeDB (server) | `l1`, `l1tpc`, `lifecycle`, `restart` | one suffix for the documents-lane arms (the issue does not name it) | none: also an arm of `l1`, `lifecycle`, `restart`, so a suffix would split one id into several | 36 | yes | 12 / 17 / 2 / 2 |
| `duckdb` | DuckDB | `l1`, `l1tpc`, `l4` | one suffix for the documents-lane arms (the issue does not name it) | none: also an arm of `l1`, `l4`, so a suffix would split one id into several | 18 | yes | 16 / 18 / 4 / 2 |
| `sqlite` | SQLite | `l1`, `l1tpc`, `l4` | one suffix for the documents-lane arms (the issue does not name it) | none: also an arm of `l1`, `l4`, so a suffix would split one id into several | 18 | yes | 11 / 7 / 7 / 2 |
| `timescaledb` | TimescaleDB | `l4` | unchanged ("leave the rest alone") |  | 0 | no | 6 / 1 / 4 / 1 |
| `postgres_ts` | PostgreSQL | `l4` | unchanged ("leave the rest alone") |  | 0 | no | 4 / 1 / 4 / 1 |
| `mongodb` | MongoDB | `l1`, `l1tpc`, `restart`, `l4` | one suffix for the documents-lane arms (the issue does not name it) | none: also an arm of `l1`, `l4`, `restart`, so a suffix would split one id into several | 15 | yes | 8 / 5 / 3 / 2 |
| `mongodb_graph` | MongoDB | `l2` | unchanged ("leave the rest alone") |  | 15 | yes | 6 / 0 / 1 / 3 |
| `mongodb_dense` | MongoDB | `restart`, `l3d` | unchanged ("leave the rest alone") |  | 6 | yes | 8 / 3 / 3 / 1 |
| `mongodb_dense_int8` | MongoDB | `l3d` | unchanged ("leave the rest alone") |  | 0 | no | 6 / 1 / 4 / 1 |
| `mongodb_e2` | MongoDB | `e2` | unchanged ("leave the rest alone") |  | 18 | yes | 6 / 1 / 1 / 1 |
| `arcadedb_ts_doc` | no entry | `l4` | unchanged ("leave the rest alone") |  | 0 | no | 5 / 2 / 3 / 2 |
| `arcadedb_ts_native` | no entry | `l4` | unchanged ("leave the rest alone") |  | 0 | no | 7 / 2 / 2 / 1 |
| `questdb` | QuestDB | `restart`, `l4` | unchanged ("leave the rest alone") |  | 0 | no | 10 / 1 / 4 / 1 |
| `postgres` | PostgreSQL | `l1`, `l1tpc`, `restart` | one suffix for the documents-lane arms (the issue does not name it) | none: also an arm of `l1`, `restart`, so a suffix would split one id into several | 18 | yes | 13 / 11 / 5 / 2 |
| `postgres_tuned` | PostgreSQL (tuned) | `l1`, `l1tpc` | one suffix for the documents-lane arms (the issue does not name it) | none: also an arm of `l1`, so a suffix would split one id into several | 18 | no | 8 / 3 / 6 / 1 |
| `arcadedb_graph_embedded` | ArcadeDB (embedded) | `l2` | unchanged ("leave the rest alone") |  | 36 | yes | 7 / 20 / 2 / 1 |
| `arcadedb_graph_server` | ArcadeDB (server) | `l2`, `restart` | unchanged ("leave the rest alone") |  | 36 | yes | 8 / 12 / 2 / 2 |
| `neo4j_graph` | Neo4j | `l2`, `restart` | unchanged ("leave the rest alone") |  | 15 | yes | 11 / 9 / 2 / 1 |
| `ladybug_graph` | LadybugDB | `l2` | unchanged ("leave the rest alone") |  | 15 | yes | 8 / 1 / 2 / 1 |
| `memgraph_graph` | Memgraph | `l2`, `restart` | unchanged ("leave the rest alone") |  | 15 | yes | 7 / 2 / 1 / 3 |
| `falkordb_graph` | FalkorDB | `l2`, `restart` | unchanged ("leave the rest alone") |  | 0 | no | 7 / 3 / 2 / 1 |
| `duckpgq_graph` | DuckPGQ | `l2` | unchanged ("leave the rest alone") |  | 3 | yes | 9 / 5 / 2 / 1 |
| `pgage_graph` | PostgreSQL + AGE | `l2` | one spelling, `pg_age` (the issue names the spelling, not the full id) | `pg_age_graph` (the smallest change that gives one spelling) | 15 | yes | 4 / 5 / 2 / 1 |
| `arcadedb_e2` | ArcadeDB (one transaction) | `e2` | unchanged ("leave the rest alone") |  | 36 | yes | 8 / 4 / 1 / 1 |
| `surrealdb_e2` | SurrealDB (embedded) | `e2` | unchanged ("leave the rest alone") |  | 9 | yes | 9 / 2 / 1 / 2 |
| `pg_age_e2` | PostgreSQL + pgvector + AGE | `e2` | one spelling, `pg_age` (the issue names the spelling, not the full id) | keeps `pg_age`; the `_e2` part follows whatever the cross-model lane becomes | 18 | yes | 5 / 0 / 1 / 1 |
| `memgraph_e2` | Memgraph (vector index) | `e2` | unchanged ("leave the rest alone") |  | 18 | yes | 5 / 0 / 2 / 1 |
| `ladybug_e2` | LadybugDB (vector extension) | `e2` | unchanged ("leave the rest alone") |  | 18 | yes | 5 / 2 / 3 / 2 |
| `duckdb_e2` | DuckDB (vss + DuckPGQ) | `e2` | unchanged ("leave the rest alone") |  | 18 | yes | 6 / 0 / 2 / 1 |
| `composed_embedded_sqlite_lance_ladybug` | SQLite + LanceDB + LadybugDB (no shared transaction) | `e2` | unchanged ("leave the rest alone") |  | 18 | yes | 5 / 1 / 3 / 2 |
| `neo4j_e2` | Neo4j (vector index) | `e2` | unchanged ("leave the rest alone") |  | 0 | no | 7 / 4 / 3 / 1 |
| `arangodb_tpc` | ArangoDB | `l1tpc`, `restart` | one suffix for the documents-lane arms (the issue does not name it) | `arangodb_document` (matches the proposed lane name `document`) | 18 | yes | 5 / 0 / 1 / 1 |
| `arangodb_graph` | ArangoDB | `l2` | unchanged ("leave the rest alone") |  | 15 | yes | 4 / 3 / 1 / 3 |
| `arangodb_dense` | ArangoDB | `l3d` | unchanged ("leave the rest alone") |  | 6 | yes | 8 / 3 / 2 / 1 |
| `arangodb_dense_int8` | ArangoDB | `l3d` | unchanged ("leave the rest alone") |  | 0 | no | 6 / 2 / 4 / 1 |
| `arangodb_e2` | ArangoDB | `e2` | unchanged ("leave the rest alone") |  | 18 | yes | 6 / 0 / 1 / 1 |
| `surrealdb_graph` | SurrealDB (embedded) | `l2` | unchanged ("leave the rest alone") |  | 12 | yes | 3 / 2 / 1 / 1 |
| `surrealdb_graph_server` | SurrealDB (server) | `l2` | unchanged ("leave the rest alone") |  | 12 | yes | 3 / 2 / 1 / 1 |
| `surrealdb_tpc` | SurrealDB (embedded) | `l1tpc` | one suffix for the documents-lane arms (the issue does not name it) | `surrealdb_document` (matches the proposed lane name `document`) | 6 | yes | 5 / 5 / 1 / 2 |
| `surrealdb_tpc_server` | SurrealDB (server) | `l1tpc`, `restart` | one suffix for the documents-lane arms (the issue does not name it) | `surrealdb_document_server` (matches the proposed lane name `document`) | 6 | yes | 5 / 1 / 1 / 1 |
| `surrealdb_dense` | SurrealDB (embedded) | `l3d` | unchanged ("leave the rest alone") |  | 0 | yes | 5 / 3 / 2 / 2 |
| `surrealdb_lifecycle` | SurrealDB (embedded) | `lifecycle` | unchanged ("leave the rest alone") |  | 0 | no | 4 / 1 / 1 / 2 |
| `sqlite_lifecycle` | SQLite (embedded) | none (registered, on no lane's roster) | unchanged ("leave the rest alone") |  | 0 | no | 4 / 0 / 2 / 0 |
| `duckdb_lifecycle` | DuckDB (embedded) | none (registered, on no lane's roster) | unchanged ("leave the rest alone") |  | 0 | no | 5 / 0 / 2 / 0 |
| `ladybug_lifecycle` | LadybugDB (embedded) | none (registered, on no lane's roster) | unchanged ("leave the rest alone") |  | 0 | no | 5 / 0 / 3 / 1 |
| `chroma_lifecycle` | Chroma (embedded) | none (registered, on no lane's roster) | unchanged ("leave the rest alone") |  | 0 | no | 5 / 0 / 1 / 0 |
| `lancedb_lifecycle` | LanceDB (embedded) | none (registered, on no lane's roster) | unchanged ("leave the rest alone") |  | 0 | no | 5 / 0 / 1 / 0 |
| `sqlite_vec_lifecycle` | sqlite-vec (embedded) | none (registered, on no lane's roster) | unchanged ("leave the rest alone") |  | 0 | no | 4 / 0 / 1 / 0 |
| `surrealdb_dense_server` | SurrealDB (server) | `l3d` | unchanged ("leave the rest alone") |  | 0 | yes | 4 / 2 / 2 / 2 |
| `surrealdb_e2_server` | SurrealDB (server) | `e2` | unchanged ("leave the rest alone") |  | 9 | yes | 5 / 1 / 1 / 1 |
| `surrealdb_ts` | SurrealDB (embedded) | `l4` | unchanged ("leave the rest alone") |  | 0 | no | 4 / 1 / 1 / 1 |
| `surrealdb_ts_server` | SurrealDB (server) | `l4` | unchanged ("leave the rest alone") |  | 0 | no | 4 / 1 / 1 / 1 |
| `arangodb_ts` | ArangoDB | `l4` | unchanged ("leave the rest alone") |  | 0 | no | 4 / 1 / 1 / 1 |
| `composed_qdrant_neo4j` | Qdrant + Neo4j (no shared transaction) | `e2` | unchanged ("leave the rest alone") |  | 18 | yes | 10 / 1 / 1 / 1 |
| `arcadedb_sparse_embedded` | ArcadeDB (embedded, int8) | `l3s` | unchanged ("leave the rest alone") |  | 0 | no | 8 / 4 / 1 / 1 |
| `arcadedb_sparse_embedded_fp32` | ArcadeDB (embedded, fp32) | `l3s` | unchanged ("leave the rest alone") |  | 0 | no | 6 / 0 / 1 / 1 |
| `arcadedb_sparse_embedded_nocompact` | ArcadeDB (embedded, no settle step) | `l3s` | unchanged ("leave the rest alone") |  | 0 | no | 5 / 0 / 1 / 1 |
| `arcadedb_sparse_server` | ArcadeDB (server, int8) | `l3s` | unchanged ("leave the rest alone") |  | 0 | no | 6 / 5 / 2 / 1 |
| `qdrant_sparse` | Qdrant | `l3s` | unchanged ("leave the rest alone") |  | 0 | no | 10 / 5 / 3 / 1 |
| `qdrant_sparse_uint8` | Qdrant | `l3s` | unchanged ("leave the rest alone") |  | 0 | no | 7 / 2 / 4 / 1 |
| `milvus_sparse` | Milvus | `l3s` | unchanged ("leave the rest alone") |  | 0 | no | 8 / 2 / 1 / 1 |
| `elasticsearch_sparse` | Elasticsearch | `l3s` | unchanged ("leave the rest alone") |  | 0 | no | 8 / 3 / 1 / 1 |
| `arcadedb_dense_embedded` | ArcadeDB (embedded) | `l3d` | unchanged ("leave the rest alone") |  | 12 | yes | 11 / 12 / 2 / 1 |
| `arcadedb_dense_server` | ArcadeDB (server) | `restart`, `l3d` | unchanged ("leave the rest alone") |  | 9 | yes | 10 / 11 / 2 / 1 |
| `arcadedb_dense_server_int8` | ArcadeDB (server) | `l3d` | unchanged ("leave the rest alone") |  | 0 | no | 6 / 3 / 2 / 1 |
| `arcadedb_dense_embedded_int8` | ArcadeDB (embedded) | `l3d` | unchanged ("leave the rest alone") |  | 0 | no | 6 / 2 / 2 / 1 |
| `chroma_dense` | Chroma | `l3d` | unchanged ("leave the rest alone") |  | 0 | no | 9 / 0 / 3 / 1 |
| `lancedb_dense` | LanceDB | `l3d` | unchanged ("leave the rest alone") |  | 0 | no | 8 / 1 / 4 / 1 |
| `lancedb_dense_fp32` | LanceDB | `l3d` | unchanged ("leave the rest alone") |  | 0 | no | 7 / 0 / 4 / 1 |
| `sqlite_vec_dense` | sqlite-vec | `l3d` | unchanged ("leave the rest alone") |  | 6 | yes | 10 / 4 / 2 / 1 |
| `sqlite_vec_dense_int8` | sqlite-vec | `l3d` | unchanged ("leave the rest alone") |  | 0 | no | 7 / 4 / 2 / 1 |
| `duckdb_vss_dense` | DuckDB VSS | `l3d` | unchanged ("leave the rest alone") |  | 6 | yes | 9 / 4 / 3 / 1 |
| `qdrant_dense` | Qdrant | `restart`, `l3d` | unchanged ("leave the rest alone") |  | 6 | yes | 12 / 12 / 1 / 1 |
| `qdrant_dense_int8` | Qdrant | `l3d` | unchanged ("leave the rest alone") |  | 0 | no | 7 / 4 / 2 / 1 |
| `pgvector_dense` | pgvector | `l3d` | unchanged ("leave the rest alone") |  | 6 | yes | 4 / 7 / 2 / 1 |
| `pgvector_sparse` | pgvector | `l3s` | unchanged ("leave the rest alone") |  | 0 | no | 4 / 2 / 2 / 1 |
| `cratedb_tpc` | CrateDB | `l1tpc` | one suffix for the documents-lane arms (the issue does not name it) | `cratedb_document` (matches the proposed lane name `document`) | 18 | yes | 5 / 6 / 1 / 1 |
| `cratedb_dense` | CrateDB | `l3d` | unchanged ("leave the rest alone") |  | 0 | yes | 5 / 4 / 1 / 1 |
| `cratedb_ts` | CrateDB | `l4` | unchanged ("leave the rest alone") |  | 0 | no | 4 / 0 / 1 / 1 |
| `neo4j_dense` | Neo4j | `l3d` | unchanged ("leave the rest alone") |  | 0 | no | 7 / 4 / 3 / 1 |
| `neo4j_dense_int8` | Neo4j | `l3d` | unchanged ("leave the rest alone") |  | 0 | no | 6 / 1 / 4 / 1 |
| `elasticsearch_dense` | Elasticsearch | `restart`, `l3d` | unchanged ("leave the rest alone") |  | 0 | no | 8 / 1 / 4 / 1 |
| `elasticsearch_dense_int8` | Elasticsearch | `l3d` | unchanged ("leave the rest alone") |  | 0 | no | 7 / 0 / 4 / 1 |
| `memgraph_dense` | Memgraph | `l3d` | unchanged ("leave the rest alone") |  | 0 | no | 6 / 4 / 4 / 1 |
| `memgraph_dense_int8` | Memgraph | `l3d` | unchanged ("leave the rest alone") |  | 0 | no | 6 / 2 / 4 / 1 |
| `falkordb_dense` | FalkorDB | `l3d` | unchanged ("leave the rest alone") |  | 0 | no | 5 / 2 / 4 / 1 |
| `redis_dense` | Redis | `l3d` | unchanged ("leave the rest alone") |  | 6 | yes | 5 / 6 / 2 / 1 |
| `redis_tpc` | Redis | `l1tpc` | one suffix for the documents-lane arms (the issue does not name it) | `redis_document` (matches the proposed lane name `document`) | 9 | yes | 5 / 3 / 3 / 1 |
| `redis_ts` | Redis | `l4` | unchanged ("leave the rest alone") |  | 0 | no | 5 / 1 / 3 / 1 |
| `ladybug_dense` | LadybugDB | `l3d` | unchanged ("leave the rest alone") |  | 6 | yes | 6 / 2 / 4 / 2 |
| `milvus_dense` | Milvus | `restart`, `l3d` | unchanged ("leave the rest alone") |  | 0 | no | 10 / 1 / 1 / 1 |
| `milvus_dense_int8` | Milvus | `l3d` | unchanged ("leave the rest alone") |  | 0 | no | 6 / 1 / 1 / 1 |
| `arcadedb_sparse_server_fp32` | ArcadeDB (server, fp32) | `l3s` | unchanged ("leave the rest alone") |  | 0 | no | 5 / 1 / 1 / 1 |
| `arcadedb_e2_server` | ArcadeDB (server, one transaction) | `e2` | unchanged ("leave the rest alone") |  | 36 | yes | 6 / 4 / 1 / 1 |
| `arcadedb_ts_doc_server` | no entry | `l4` | unchanged ("leave the rest alone") |  | 0 | no | 6 / 2 / 3 / 1 |
| `arcadedb_ts_native_server` | no entry | `restart`, `l4` | unchanged ("leave the rest alone") |  | 0 | no | 7 / 3 / 3 / 1 |
| `arcadedb_e4` | no entry | `e4` | unchanged ("leave the rest alone") |  | 0 | no | 1 / 5 / 1 / 0 |
| `arcadedb_imgdefaults_server` | ArcadeDB (server, image JVM defaults) | `l1tpc` | one suffix for the documents-lane arms (the issue does not name it) | none | 0 | no | 6 / 8 / 2 / 1 |

The documents lane (`l1tpc`) has 13 arms: 5 carry `_tpc` (`surrealdb_tpc`, `surrealdb_tpc_server`, `arangodb_tpc`, `cratedb_tpc`, `redis_tpc`) and 8 carry no lane suffix (`arcadedb_embedded`, `arcadedb_server`, `arcadedb_imgdefaults_server`, `duckdb`, `sqlite`, `mongodb`, `postgres`, `postgres_tuned`). Of the second group, 7 are also arms of another lane (`arcadedb_embedded`, `arcadedb_server`, `duckdb`, `sqlite`, `mongodb`, `postgres`, `postgres_tuned`), so one suffix for the documents lane either splits each of those ids per lane or applies only to the arms that carry `_tpc` today. The issue does not decide this.

Ids in the frozen rows or the payload that `runner.BACKENDS` does not hold today: none.

## Not in the issue

The issue does not cover the workload ids (the `workload` field of a row): `decomp`, `oltp`, `olap`, `hybrid`, `atomicity`, `empty`, `doc`, `doc_idx10`, `graph`, `graph_gav`, `vector`, `sparse`, `ts`, `restart`, `search`, `ingest`. No proposal. They are listed here because `e2atom`, `docs_oltp`, `docs_olap` and `l2olap` are each a lane plus a workload or a size, so a table rename touches the code that reads these.

## What changes together

- **A lane id**: `runner.LANES` and `LANE_CORPUS`, every `lane ==` test in the exporter and the gates, the stage list (`STATIC_STAGES` in `make_post1_rerun_stages.py`, `make_2611_stages.py`), the checksums of the generated stages (`stage_drafts_2611.sha256`), the `lane` field of the frozen rows, and the file names above.
- **A table id**: the exporter's table specs, `_TABLE_LANE`, `SOURCES` and the prose registries keyed by table, `page_check.py`, the generated block at the end of PAGE-SPEC.md, and `tableId` in the site's `lanes.ts`. The exporter and the site change in the same publish, or the page names a table the payload does not carry.
- **A size id**: the three per-size tables and `LARGE_SCALES` in `runner.py`, `SCALE_LABELS` and `SCALE_ORDER` in `export_web.py`, the stage list, the `scale` field of the frozen rows, and the names of the overlay directories the dense table reads (`dense_mp5_small_<pin>`, see PAGE-SPEC.md).
- **A backend id**: `runner.BACKENDS`, each lane's roster in `runner.LANES`, the per-lane adapter tables (for example `BACKENDS` in `e2_hybrid.py`), `DISPLAY_NAMES`, the roster file `roster_2611.json`, the `backend` field of the frozen rows, and `backend_key` and `comparator_versions` in the payload.
- **Outside this repository** (from the issue): the site, arcadedb-python, the Humem Ops queue files and stage names, and the old `humem.ai/research/mmdbbench/<lane>` links in upstream posts, which get redirects.

## What is stored and needs a compatibility read

These hold old ids as data. The issue's plan is that frozen rows keep their old ids and the exporter and the provenance check read this map, so rows from 26.11.1 and later join.

- `results/runs_paper.csv`: 708 rows with the old ids in `lane`, `scale`, `backend` and `workload`. The same holds for every published results asset (`publish_results_asset.py` bundles this file) and for rows still on a benchmark host.
- `results/web_benchmarks.json`: table ids, `scale` and `backend_key`. It is regenerated at each publish, so it needs no read of old ids, but a published asset keeps the copy it was bundled with.
- `fixtures/`, `evidence/` and the files under `results/`: recorded data, kept byte for byte (the pre-commit configuration excludes them from every fixing hook). They keep their old ids.
- The data files at the top of `experiments/` that hold a lane, size or backend id (`build_images.sh`, `campaign_env.sh`, `cap_rule_2610.json`, `roster_2611.json`, `smoke_arangodb_server_limit.sh`, `smoke_memgraph_server_limit.sh`, `smoke_mongodb_server_limit.sh`, `smoke_native_server.sh`, `verify_pair_c25.sh`): check each one in the pass. A file that pins measured history keeps the old id and is read through the map; a file that configures the next run is renamed.

The check the issue plans ("fails on any old id left in live files") needs the two lists kept apart: live files, where an old id is an error, and stored files, where it is expected.
