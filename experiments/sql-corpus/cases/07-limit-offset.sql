-- purpose: LIMIT and OFFSET with ORDER BY return the same page.
-- tables: person
SELECT id, name FROM person ORDER BY id LIMIT 2 OFFSET 1;
