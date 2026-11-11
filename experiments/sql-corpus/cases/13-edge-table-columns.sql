-- purpose: An edge type reads as a link table with the columns id, source_id, target_id, and its own properties.
-- tables: knows
SELECT id, source_id, target_id, since FROM knows ORDER BY id;
