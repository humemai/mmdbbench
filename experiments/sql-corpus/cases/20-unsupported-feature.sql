-- purpose: A feature that is not supported fails loudly with SQLSTATE 0A000 (feature not supported), never with a different result.
-- tables: none
-- expect-error: 0A000
CREATE EXTENSION vector;
