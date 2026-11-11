-- purpose: Each column type comes back with the PostgreSQL type and the same value (int4, int8, numeric, float8, bool, text, date, NULL).
-- tables: typed
-- types: yes
SELECT i, big, n, f, b, s, d FROM typed ORDER BY i;
