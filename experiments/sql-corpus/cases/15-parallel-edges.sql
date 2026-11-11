-- purpose: Two parallel edges between one pair of persons give two identical rows, not one (discussion 11292, Sadrak2017).
-- tables: person, knows
SELECT a.name AS source, b.name AS target
FROM person a JOIN knows k ON k.source_id = a.id JOIN person b ON b.id = k.target_id
WHERE a.id = 1 AND b.id = 2;
