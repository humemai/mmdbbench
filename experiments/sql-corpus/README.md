# SQL acceptance corpus

The first version of the acceptance corpus of [humemai/mmdbbench#18](https://github.com/humemai/mmdbbench/issues/18), the evidence side of [ArcadeDB discussion 11292](https://github.com/ArcadeData/arcadedb/discussions/11292). It checks the relational view of a multi-model database (see [SQL for relational users](../../docs/sql-for-relational-users.md)): the same SQL, sent over the PostgreSQL wire protocol to PostgreSQL 18 and to the engine under test, must return the same rows. The first subject is ArcadeDB's PostgreSQL wire server.

Status: 20 cases, one client (psycopg 3), one run, one machine. This is the corpus and its first smoke run, not the timed study of the issue and not the client matrix. The targets of the issue (every connect, list, and describe step of six clients, then 80 to 90 percent of real statements) are not claimed here.

## Rules

These were written before the run whose output is pasted below. The corpus was developed against ArcadeDB 26.11.1 itself: it ran twice on a first draft, and two things changed after seeing those results, both listed under "Changes after the first draft". Everything else below is as it was written.

1. The reference is PostgreSQL 18, never the engine under test. A case is run once on each engine, on one connection per engine with autocommit on (reconnected only if the connection breaks).
2. The verdict is about the engine under test, one per case: `PASS`, `FAIL`, or `ERROR`.
   - `PASS`: the engine's result equals the reference result. For a case with `expect-error`, `PASS` means the engine failed with exactly that SQLSTATE.
   - `FAIL`: the engine returned a different result, or an error. The SQLSTATE and the message are printed. A case that the engine cannot run today is a `FAIL` with its error, never skipped.
   - `ERROR`: the corpus cannot judge the case, because the reference failed or the case file is malformed. This does not count for or against the engine.
3. Results are compared as complete multisets of rows, and in order only when the statement contains `ORDER BY`. Columns are compared by position, names are ignored, and the column count must match. Numbers compare by value across `int`, `float`, and `numeric`; `bool`, `NULL`, and text never equal a number. A duplicate row counts: two parallel edges must give two rows.
4. A case with `types: yes` (only `01-type-mapping-values`) also compares the type OIDs of the result columns. This is strict on purpose: `varchar` is not `text`.
5. A statement that writes (`write: yes`) runs once and its `cleanup` statements restore the dataset on both engines. A failing cleanup is printed next to the case and is not scored.
6. The case `20-unsupported-feature` states the contract of the engine under test: it must fail with SQLSTATE `0A000`. The reference's own outcome for that statement is not scored.
7. A client passes only when its connect step and all 20 cases pass. The last line of the output is that verdict. The exit code is 0 only for a pass.
8. Time: every statement is timed from the call to `execute` until the last row is fetched, as a client sees it. The first execution decides the verdict. A read-only statement that succeeds runs 4 more times, and the line shows the median of the 5. Writes and the `expect-error` case run once.
9. Schema names are not compared. ArcadeDB reports the database name as the schema where PostgreSQL has `public`, so the catalog cases filter out `pg_catalog` and `information_schema` and do not select a schema name.

The dataset is written once, in `setup.py`: 6 persons (2 without a company), 3 companies (one without persons), 6 `knows` edges (two of them parallel, from person 1 to person 2), and a `typed` table with every column type and a NULL row. Each engine gets its own DDL from those rows. PostgreSQL gets tables with primary and foreign keys. ArcadeDB gets vertex types `person` and `company`, an edge type `knows`, a document type `typed`, a unique index on each `id`, and `company_id` as a plain property, because ArcadeDB SQL has no primary key, no foreign key, and no `source_id` column on an edge. Loading is not scored.

## Pins

| item | value |
|---|---|
| reference | `postgres:18.6`, digest `sha256:3a4264520e121176619f54ff867d12774bc81e95e7b84db58d63bccdb6144b81`, default settings |
| engine under test | `arcadedata/arcadedb:26.11.1`, digest `sha256:22a049898f34f01c256b56a1ba95fb01d32e5e14755d3c4367415c8e55ae5035`, build `a3a5d124572608412aa187f9c4b290e071699473` read from the running server |
| ArcadeDB wire server | enabled with `-Darcadedb.server.plugins=Postgres:com.arcadedb.postgres.PostgresProtocolPlugin`, database `corpus` created with `-Darcadedb.server.defaultDatabases=corpus[root]`, heap `-Xmx1g` |
| client | `psycopg[binary]==3.3.8` (libpq 180006), run with `python -I`, TLS off (`sslmode=disable`) on both |
| limits | each container on cores 12 to 15 with 2 GB of memory; both containers share those cores |
| host | Intel Core Ultra X9 388H laptop, Linux 7.0.0-43-generic, Docker 29.1.3 |

## How to run

One command starts both containers, loads the dataset, runs the corpus, writes `results/first-run.txt` and `results/first-run.jsonl`, and removes only the containers it started:

```bash
bash smoke.sh
```

`smoke.sh` needs Docker and `uv`. The defaults (images, cores, memory, repeats) are variables at its top. To run against servers that are already up, load the dataset and run the corpus yourself:

```bash
uv run --no-project --with "psycopg[binary]==3.3.8" python -I setup.py postgres "host=HOST port=PORT user=USER password=PW dbname=corpus"
uv run --no-project --with "psycopg[binary]==3.3.8" python -I setup.py arcadedb http://HOST:2480 PW
uv run --no-project --with "psycopg[binary]==3.3.8" python -I run.py --reference "host=... dbname=corpus" --engine "host=... dbname=corpus"
```

A case is a plain file in `cases/` named `NN-slug.sql`. Its comment lines at the top are the header: `purpose` (one line) and `tables` are required; `params` (a JSON list, sent as server-side `$1`, `$2`), `types`, `write`, `cleanup`, `mode` (`copy-out`), and `expect-error` are optional. The rest of the file is one SQL statement. To add a case, add a file.

## The 20 cases

| class | cases |
|---|---|
| type mapping and catalog | `01-type-mapping-values`, `02-type-mapping-catalog`, `03-list-tables`, `04-primary-key-catalog`, `05-foreign-key-catalog` |
| single-table queries | `06-primary-key-lookup`, `07-limit-offset`, `10-select-star`, `11-group-by-aggregate` |
| joins and edge tables | `08-inner-join`, `09-left-join-unmatched`, `12-left-join-group-by`, `13-edge-table-columns`, `14-one-hop-edge-join`, `15-parallel-edges` |
| writes and parameters | `16-insert-returning`, `17-parameter`, `18-update-rowcount` |
| bulk and unsupported | `19-copy-out`, `20-unsupported-feature` |

`09-left-join-unmatched` and `15-parallel-edges` are the two cases suggested on the discussion by Sadrak2017. The purpose of each case is the first line of its file.

## What is not measured

- Other clients. The matrix of psql, DBeaver, Metabase, SQLAlchemy, and JDBC (the harness of the discussion, `benchmarks/experiments/sql-evidence`) and the 40 model-written questions are not ported yet; only psycopg runs here.
- Throughput. No `COPY ... FROM STDIN` bulk load, and no scale: the dataset has a handful of rows, so the times show the cost of a statement, not of a scan, a join over many rows, or an aggregation. The expectation of the issue (key lookups, key joins, and one hop at agent-memory scale in the same range as PostgreSQL) is neither confirmed nor refuted by this run.
- Timing quality. Both servers share four cores and the laptop ran other work, each statement has 5 executions, and there is no warm-up and no p95. Read the times as a smoke, not as a result.
- `DELETE`, transactions (`BEGIN`, `COMMIT`, `ROLLBACK`), concurrency, `JSON` types, `ON CONFLICT`, CTEs, window functions, authentication methods other than a password, and TLS.
- Paths and multi-hop queries (these stay in Cypher).
- Other ArcadeDB versions and the native image. One version, one platform, one run.

Found with a development probe and not in the corpus yet: `SELECT current_schema()` fails with "Unknown function name 'current_schema'", and the schema name is the database name (`corpus`), where PostgreSQL clients expect `public` or the answer of `current_schema()`. They are candidates for the next cases.

## First result

Run on 2026-11-11 with the files of this directory. This is `results/first-run.txt` as written by `smoke.sh`; the per-statement rows are in `results/first-run.jsonl`.

```text
# images: postgres:18.6 postgres@sha256:3a4264520e121176619f54ff867d12774bc81e95e7b84db58d63bccdb6144b81
# images: arcadedata/arcadedb:26.11.1 arcadedata/arcadedb@sha256:22a049898f34f01c256b56a1ba95fb01d32e5e14755d3c4367415c8e55ae5035
# limits: cores 12-15 and 2g per container, both containers on the same cores, ArcadeDB heap -Xmx1g
# host: Intel(R) Core(TM) Ultra X9 388H, kernel 7.0.0-43-generic, docker 29.1.3
# arcadedb engine: "version":"26.11.1 (build a3a5d124572608412aa187f9c4b290e071699473/1793826579842/main)"
# arcadedb wire plugin: 2026-11-11 03:54:10.279 INFO  [PluginManager] <ArcadeDB_0> Discovered plugin on main class loader: PostgresProtocolPlugin
# client psycopg 3.3.8 (libpq 180006), repeat 5, 2026-11-11 03:54 UTC
# postgres server_version 18.6 (Debian 18.6-1.pgdg13+2)
# arcadedb server_version 12.0
PASS connect psycopg [postgres 6.37 ms; arcadedb 24.58 ms]
FAIL 01-type-mapping-values psycopg column type OIDs [23, 20, 1700, 701, 16, 1043, 1082], reference [23, 20, 1700, 701, 16, 25, 1082] [postgres 0.28 ms p50 of 5; arcadedb 6.14 ms p50 of 5]
FAIL 02-type-mapping-catalog psycopg first difference at row 6: ('s', 'character varying'), reference ('s', 'text') [postgres 1.92 ms p50 of 5; arcadedb 8.47 ms p50 of 5]
PASS 03-list-tables psycopg 4 rows equal in order [postgres 0.87 ms p50 of 5; arcadedb 1.86 ms p50 of 5]
FAIL 04-primary-key-catalog psycopg 0 rows, reference 4 [postgres 2.39 ms p50 of 5; arcadedb 1.32 ms p50 of 5]
FAIL 05-foreign-key-catalog psycopg SQLSTATE 0A000: Error on executing query: The catalog relation "information_schema.constraint_column_usage" is not supported by this server
PASS 06-primary-key-lookup psycopg 1 rows equal as a multiset [postgres 0.27 ms p50 of 5; arcadedb 1.33 ms p50 of 5]
FAIL 07-limit-offset psycopg SQLSTATE 42601: Syntax error on executing query: SQL syntax error at line 1, column 48: mismatched input 'OFFSET' expecting {<EOF>, ';'} SELECT id, name FROM person ORDER BY id LIMIT 2 OFFSET 1 ^
FAIL 08-inner-join psycopg SQLSTATE 42601: Syntax error on executing query: SQL syntax error at line 1, column 57: mismatched input 'JOIN' expecting {<EOF>, ';'} SELECT p.name AS person, c.name AS company FROM person p JOIN company c ON c.id = p.company_id ^
FAIL 09-left-join-unmatched psycopg SQLSTATE 42601: Syntax error on executing query: SQL syntax error at line 1, column 57: mismatched input 'LEFT' expecting {<EOF>, ';'} SELECT p.name AS person, c.name AS company FROM person p LEFT JOIN company c ON c.id = p.company_id ^
FAIL 10-select-star psycopg 7 columns, reference 4 [postgres 0.11 ms p50 of 5; arcadedb 1.37 ms p50 of 5]
PASS 11-group-by-aggregate psycopg 3 rows equal as a multiset [postgres 0.14 ms p50 of 5; arcadedb 5.55 ms p50 of 5]
FAIL 12-left-join-group-by psycopg SQLSTATE 42601: Syntax error on executing query: SQL syntax error at line 1, column 64: mismatched input 'LEFT' expecting {<EOF>, ';'} SELECT c.name AS company, count(p.id) AS persons FROM company c LEFT JOIN person p ON p.company_id = c.id GROUP BY c.name
FAIL 13-edge-table-columns psycopg first difference at row 0: (1, None, None, 2019), reference (1, 1, 2, 2019) [postgres 0.11 ms p50 of 5; arcadedb 2.76 ms p50 of 5]
FAIL 14-one-hop-edge-join psycopg SQLSTATE 42601: Syntax error on executing query: SQL syntax error at line 2, column 14: mismatched input 'JOIN' expecting {<EOF>, ';'} FROM person a JOIN knows k ON k.source_id = a.id JOIN person b ON b.id = k.target_id ^
FAIL 15-parallel-edges psycopg SQLSTATE 42601: Syntax error on executing query: SQL syntax error at line 2, column 14: mismatched input 'JOIN' expecting {<EOF>, ';'} FROM person a JOIN knows k ON k.source_id = a.id JOIN person b ON b.id = k.target_id ^
FAIL 16-insert-returning psycopg SQLSTATE 42601: Syntax error on executing query: SQL syntax error at line 1, column 74: mismatched input 'RETURNING' expecting {<EOF>, ';'} INSERT INTO person (id, name, age, company_id) VALUES (100, 'Zed', 40, 1) RETURNING id, name, company_id ^
PASS 17-parameter psycopg 1 rows equal as a multiset [postgres 0.30 ms p50 of 5; arcadedb 2.72 ms p50 of 5]
PASS 18-update-rowcount psycopg row count 1 equal [postgres 1.77 ms; arcadedb 21.55 ms]
PASS 19-copy-out psycopg 6 rows equal in order [postgres 0.14 ms p50 of 5; arcadedb 3.54 ms p50 of 5]
FAIL 20-unsupported-feature psycopg expected SQLSTATE 0A000, got 42601: Syntax error on executing query: SQL syntax error at line 1, column 7: no viable alternative at input 'CREATE EXTENSION' CREATE EXTENSION vector ^
VERDICT psycopg FAIL connect=PASS cases=20 PASS=6 FAIL=14 ERROR=0
```

ArcadeDB's verdicts by class (the 20 cases; the connect step passed):

| class | cases | PASS | FAIL | ERROR |
|---|---|---|---|---|
| type mapping and catalog | 5 | 1 | 4 | 0 |
| single-table queries | 4 | 2 | 2 | 0 |
| joins and edge tables | 6 | 0 | 6 | 0 |
| writes and parameters | 3 | 2 | 1 | 0 |
| bulk and unsupported | 2 | 1 | 1 | 0 |
| all | 20 | 6 | 14 | 0 |

The reference ran 19 of 20 statements without an error. The other one is `20-unsupported-feature` (SQLSTATE 0A000, not scored).

What the output shows, in the order of the table:

- ArcadeDB's PostgreSQL wire server connects, answers a server-side `$1` parameter, a primary key lookup, `GROUP BY` with an aggregate (the `NULL` group is kept), the `UPDATE` row count, `COPY (query) TO STDOUT`, and `information_schema.tables` with the four types.
- Every `JOIN`, `LEFT JOIN`, `OFFSET`, `RETURNING`, and `CREATE EXTENSION` is refused as a syntax error (SQLSTATE `42601`). Only the catalog relation `information_schema.constraint_column_usage` is refused with `0A000`, as the corpus requires of a feature that is not supported. The expected `0A000` for `CREATE EXTENSION` is missing.
- Five cases return a different result without any error. Two of them break the rule that what is not supported must fail loudly: selecting `source_id` and `target_id` from an edge type returns `NULL` for every row instead of failing (`13-edge-table-columns`), and `SELECT *` adds the columns `@rid`, `@type`, and `@cat` (`10-select-star`). The others are the type mapping and the primary key, below.
- Types and keys: a string column is `varchar` (OID 1043, `character varying`) where PostgreSQL has `text`, and the other six types match. The unique index on `id` is listed as a `UNIQUE` constraint, never as a `PRIMARY KEY`, so `04-primary-key-catalog` finds no key.

## Changes after the first draft

- The catalog cases first filtered `table_schema = 'public'` and returned 0 rows on ArcadeDB, which says nothing about types or keys. A probe showed that ArcadeDB names the schema after the database, so the filter became `NOT IN ('pg_catalog', 'information_schema')` (rule 9).
- A third `LEFT JOIN` case (an anti-join with `IS NULL`) failed for the same reason as the other two and was replaced by `10-select-star`, which the probe showed to be a gap of its own.

The results are not posted on the discussion yet; that acceptance item of the issue stays open.
