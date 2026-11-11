-- purpose: UPDATE reports the number of rows it changed.
-- tables: person
-- write: yes
-- cleanup: UPDATE person SET age = 33 WHERE id = 5
UPDATE person SET age = 99 WHERE id = 5;
