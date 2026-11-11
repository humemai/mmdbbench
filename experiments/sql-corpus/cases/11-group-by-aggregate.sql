-- purpose: GROUP BY with count and max keeps the NULL group as its own row.
-- tables: person
SELECT company_id, count(*) AS n, max(age) AS oldest FROM person GROUP BY company_id;
