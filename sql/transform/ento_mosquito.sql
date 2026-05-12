-- gold_havi.ento_mosquito
-- Gold adds typed analytics fields while preserving raw CRF columns.
SELECT
    *,
    CASE
        WHEN dateofcollection ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
        THEN left(dateofcollection, 10)::date
    END AS collection_date,
    -- Use field mosqnum when it is unique within the session (valid field data).
    -- Fall back to starttime ordering when duplicates exist (broken device data).
    CASE
        WHEN COUNT(*) OVER (PARTITION BY session_id, mosqnum) > 1
        THEN ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY starttime, uniqueid)
        ELSE CASE WHEN mosqnum ~ '^-?[0-9]+$' THEN mosqnum::integer END
    END::integer AS mosquito_number
FROM silver_havi.ento_mosquito;
