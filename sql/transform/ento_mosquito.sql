-- gold_havi.ento_mosquito
-- Intentional pass-through from silver_havi.
-- The gold layer is the designated place for future business-logic transforms
-- (type casting, computed columns, derived fields). For now the table is an
-- exact copy of silver so that promote_havi can swap it into the stable havi
-- schema without coupling directly to silver. Add transforms here as needed.
DROP TABLE IF EXISTS gold_havi.ento_mosquito;
CREATE TABLE gold_havi.ento_mosquito AS
SELECT * FROM silver_havi.ento_mosquito;
