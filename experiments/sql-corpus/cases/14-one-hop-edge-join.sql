-- purpose: One hop through the edge table is an ordinary join and returns one row per edge.
-- tables: person, knows
SELECT a.name AS source, b.name AS target
FROM person a JOIN knows k ON k.source_id = a.id JOIN person b ON b.id = k.target_id;
