-- purpose: information_schema.columns lists the columns of a type with PostgreSQL data types (schema names are not compared).
-- tables: typed
SELECT column_name, data_type FROM information_schema.columns WHERE table_schema NOT IN ('pg_catalog', 'information_schema') AND table_name = 'typed' ORDER BY column_name;
