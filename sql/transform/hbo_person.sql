-- gold_havi.hbo_person
-- Gold adds typed analytics fields while preserving raw CRF columns.
SELECT
    *,
    CASE
        WHEN dateofobservation ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
        THEN left(dateofobservation, 10)::date
    END AS observation_date,
    -- Use field individualnum when it is unique within the session (valid field data).
    -- Fall back to starttime ordering when duplicates exist (broken device data).
    CASE
        WHEN COUNT(*) OVER (PARTITION BY session_id, individualnum) > 1
        THEN ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY starttime, uniqueid)
        ELSE CASE WHEN individualnum ~ '^-?[0-9]+$' THEN individualnum::integer END
    END::integer AS individual_number,
    CASE WHEN age ~ '^-?[0-9]+([.][0-9]+)?$' THEN age::double precision END AS age_years
FROM silver_havi.hbo_person;
