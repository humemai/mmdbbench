-- purpose: A company with no persons still appears, with a count of 0.
-- tables: company, person
SELECT c.name AS company, count(p.id) AS persons FROM company c LEFT JOIN person p ON p.company_id = c.id GROUP BY c.name;
