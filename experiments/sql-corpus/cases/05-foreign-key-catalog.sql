-- purpose: Links are declared as foreign keys, including the two ends of the edge table (schema and constraint names are not compared).
-- tables: person, knows, company
SELECT kcu.table_name, kcu.column_name, ccu.table_name AS references_table
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema
JOIN information_schema.constraint_column_usage ccu
  ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
WHERE tc.table_schema NOT IN ('pg_catalog', 'information_schema') AND tc.constraint_type = 'FOREIGN KEY'
ORDER BY kcu.table_name, kcu.column_name;
