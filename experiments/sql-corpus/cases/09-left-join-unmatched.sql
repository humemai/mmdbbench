-- purpose: A LEFT JOIN keeps each person without a company once, with NULL on the right (discussion 11292, Sadrak2017).
-- tables: person, company
SELECT p.name AS person, c.name AS company FROM person p LEFT JOIN company c ON c.id = p.company_id;
