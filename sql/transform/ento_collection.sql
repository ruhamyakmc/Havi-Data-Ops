-- gold_havi.ento_collection
-- Gold adds typed analytics fields while preserving raw CRF columns.
SELECT
    *,
    CASE
        WHEN dateofcollection ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
        THEN left(dateofcollection, 10)::date
    END AS collection_date,
    COALESCE(CASE WHEN numfanoph ~ '^-?[0-9]+$' THEN numfanoph::integer END, 0)
        + COALESCE(CASE WHEN nummanoph ~ '^-?[0-9]+$' THEN nummanoph::integer END, 0)
        + COALESCE(CASE WHEN numculex ~ '^-?[0-9]+$' THEN numculex::integer END, 0)
        AS total_mosquito_count
FROM silver_havi.ento_collection;
