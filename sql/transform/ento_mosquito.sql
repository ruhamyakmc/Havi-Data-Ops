-- gold_havi.ento_mosquito
-- Gold adds typed analytics fields while preserving raw CRF columns.
SELECT
    *,
    CASE
        WHEN dateofcollection ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
        THEN left(dateofcollection, 10)::date
    END AS collection_date,
    CASE WHEN mosqnum ~ '^-?[0-9]+$' THEN mosqnum::integer END AS mosquito_number
FROM silver_havi.ento_mosquito;
