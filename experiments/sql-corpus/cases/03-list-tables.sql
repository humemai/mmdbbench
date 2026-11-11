-- purpose: A client can list the tables, and each type of the dataset appears as one (schema names are not compared).
-- tables: company, person, knows, typed
SELECT table_name, table_type FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog', 'information_schema') ORDER BY table_name;
