-- gold_havi.pheno_assay
-- Gold adds typed analytics fields while preserving raw CRF columns.
SELECT
    *,
    CASE
        WHEN assaydate ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
        THEN left(assaydate, 10)::date
    END AS assay_date,
    CASE WHEN numtested ~ '^-?[0-9]+$' THEN numtested::integer END AS num_tested,
    CASE WHEN numdead ~ '^-?[0-9]+$' THEN numdead::integer END AS num_dead,
    CASE WHEN numkd ~ '^-?[0-9]+$' THEN numkd::integer END AS num_knockdown,
    CASE WHEN pctmortality ~ '^-?[0-9]+([.][0-9]+)?$' THEN pctmortality::double precision END AS pct_mortality_value,
    CASE WHEN pctkd ~ '^-?[0-9]+([.][0-9]+)?$' THEN pctkd::double precision END AS pct_knockdown_value
FROM silver_havi.pheno_assay;
