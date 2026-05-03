ALTER TABLE IF EXISTS bronze_havi.ento_mosquito
    ADD COLUMN IF NOT EXISTS clocation TEXT;

ALTER TABLE IF EXISTS silver_havi.ento_mosquito
    ADD COLUMN IF NOT EXISTS clocation TEXT;

ALTER TABLE IF EXISTS gold_havi.ento_mosquito
    ADD COLUMN IF NOT EXISTS clocation TEXT;

ALTER TABLE IF EXISTS havi.ento_mosquito
    ADD COLUMN IF NOT EXISTS clocation TEXT;
