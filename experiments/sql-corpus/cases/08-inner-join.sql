-- purpose: An inner join on equality drops the persons that have no company.
-- tables: person, company
SELECT p.name AS person, c.name AS company FROM person p JOIN company c ON c.id = p.company_id;
