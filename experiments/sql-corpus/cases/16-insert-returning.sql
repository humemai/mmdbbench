-- purpose: INSERT ... RETURNING hands back the stored row.
-- tables: person
-- write: yes
-- cleanup: DELETE FROM person WHERE id = 100
INSERT INTO person (id, name, age, company_id) VALUES (100, 'Zed', 40, 1) RETURNING id, name, company_id;
