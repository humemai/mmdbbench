-- purpose: SELECT * returns exactly the declared columns, with no engine metadata columns.
-- tables: person
SELECT * FROM person WHERE id = 3;
