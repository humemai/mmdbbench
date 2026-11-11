# SQL for relational users

This is a study beside the lanes, not a lane. It asks how natural a multi-model database is for someone who already knows PostgreSQL, and how that can be measured instead of argued. The first subject is ArcadeDB; HumemAI contributes to ArcadeDB, which is one reason the scoring is written down here, with the reference answers coming from PostgreSQL 18 and not from the engine under test.

!!! note "Status"
    The first evidence exists: two small experiments, with their harness and pre-registered rules, are described in [ArcadeDB discussion 11292](https://github.com/ArcadeData/arcadedb/discussions/11292). The corpus described below extends them and is tracked in [humemai/mmdbbench#18](https://github.com/humemai/mmdbbench/issues/18). A first version of the corpus (20 cases, psycopg only) and its first smoke run are in [`experiments/sql-corpus`](https://github.com/humemai/mmdbbench/tree/main/experiments/sql-corpus). The full corpus and the client matrix have not been measured yet, so the targets below are targets, not results, and no date is promised.

## Why PostgreSQL

Agents, BI tools, ORMs, and drivers speak standard SQL, and the PostgreSQL wire protocol and catalog are what most of them implement. In the evidence of the discussion above, of the 228 model-written answers that were correct on DuckDB, 225 (98.7 percent) were also correct unchanged on PostgreSQL 18. A database that behaves like PostgreSQL for the common cases is therefore reachable by all of them without a dialect of its own.

## What is measured

| part | question | reference |
|---|---|---|
| Client matrix | does the client connect, list the tables, describe a table, and run a query | what the client itself sends |
| Model-written SQL | do the standard-SQL answers of language models to 40 questions run and return the right rows | PostgreSQL 18 |
| Relational view cases | does a record type behave like a table: keys, joins, grouping, writes | PostgreSQL 18, result sets compared as complete multisets |

## What the relational view cases expect

| expectation | what is checked |
|---|---|
| A document or vertex type is a table, and each column has a standard type | the catalog lists the type with PostgreSQL types (`text`, `int8`, `numeric`, `jsonb`) |
| Every table has a primary key | `id` is declared as the primary key in `information_schema` and `pg_catalog` |
| Links are foreign keys | the link properties and the two ends of an edge type are declared as foreign keys, so a client draws the join by itself |
| An edge type is a link table | its columns are `source_id` and `target_id`, not engine-specific names, because `in` is a reserved word in SQL |
| One hop is an ordinary join | `JOIN ... ON` equality returns one row per edge, so two parallel edges give two rows |
| An unmatched `LEFT JOIN` keeps its row | rows with no match come back once, with `NULL` on the right |
| Everyday SQL works | `INSERT`, `UPDATE`, `DELETE`, transactions, `RETURNING`, `LIMIT` and `OFFSET`, `$1` parameters, `COPY` |
| What is not supported fails loudly | the error carries SQLSTATE `0A000` (feature not supported), never a different result |

Paths and multi-hop queries are not part of this study; they stay in Cypher.

## Scoring

A case passes when its result equals the reference result as a complete multiset of rows (and in order when the statement orders). A client passes only when every one of its connect, list, describe, and query steps passes, because one failing introspection query breaks the whole tool. Results are published per client with the counts, not as a single average. A feature list marks each feature as works, planned, or not planned.

## Targets for the first subject

- Every connect, list-tables, and describe-table query of psql, DBeaver, Metabase, SQLAlchemy, JDBC, and psycopg.
- 80 to 90 percent of the statements from real sources (ORM-generated SQL, what BI tools send, model-written SQL, the 40 questions) run and return the same rows as PostgreSQL 18.

Not promised: full PostgreSQL compatibility, which means `PL/pgSQL`, triggers, `CREATE EXTENSION`, and the `pg_stat_*` views. Planned: common table expressions including `WITH RECURSIVE`, window functions, JSON operators, and `ON CONFLICT`.

## Follow the work

The design discussion is [ArcadeDB discussion 11292](https://github.com/ArcadeData/arcadedb/discussions/11292), and the corpus and its results are tracked in [humemai/mmdbbench#18](https://github.com/humemai/mmdbbench/issues/18). If a client, a statement, or a case is missing, say so there.
