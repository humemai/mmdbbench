-- purpose: COPY (query) TO STDOUT streams the rows, the way a bulk export tool reads them.
-- tables: person
-- mode: copy-out
COPY (SELECT id, name FROM person ORDER BY id) TO STDOUT;
