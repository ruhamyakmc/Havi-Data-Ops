-- gold_havi.hbo_person
-- Intentional pass-through from silver_havi.
-- The gold layer is the designated place for future business-logic transforms
-- (type casting, computed columns, derived fields). For now the table is an
-- exact copy of silver so that promote_havi can swap it into the stable havi
-- schema without coupling directly to silver. Add transforms here as needed.
DROP TABLE IF EXISTS gold_havi.hbo_person;
CREATE TABLE gold_havi.hbo_person AS
SELECT * FROM silver_havi.hbo_person;
