-- purpose: A lookup by primary key returns the one row with its NULL-able link column.
-- tables: person
SELECT id, name, age, company_id FROM person WHERE id = 3;
