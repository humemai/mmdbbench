-- purpose: Every table declares its primary key in information_schema (schema and constraint names are not compared).
-- tables: company, person, knows, typed
SELECT kcu.table_name, kcu.column_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema
WHERE tc.table_schema NOT IN ('pg_catalog', 'information_schema') AND tc.constraint_type = 'PRIMARY KEY'
ORDER BY kcu.table_name, kcu.column_name;
