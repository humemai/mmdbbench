-- purpose: A server-side $1 parameter (extended protocol) binds and filters.
-- tables: person
-- params: [2]
SELECT id, name FROM person WHERE id = $1;
