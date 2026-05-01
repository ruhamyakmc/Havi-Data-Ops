-- gold_havi.pheno_site
-- Gold adds typed analytics fields while preserving raw CRF columns.
SELECT
    *,
    CASE
        WHEN assaydate ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
        THEN left(assaydate, 10)::date
    END AS assay_date,
    CASE WHEN nassays ~ '^-?[0-9]+$' THEN nassays::integer END AS assay_count
FROM silver_havi.pheno_site;
