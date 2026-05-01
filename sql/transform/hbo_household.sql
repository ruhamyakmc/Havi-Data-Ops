-- gold_havi.hbo_household
-- Gold adds typed analytics fields while preserving raw CRF columns.
SELECT
    *,
    CASE
        WHEN dateofobservation ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
        THEN left(dateofobservation, 10)::date
    END AS observation_date,
    CASE WHEN numsleeprooms ~ '^-?[0-9]+$' THEN numsleeprooms::integer END AS sleeping_rooms_count,
    CASE WHEN numsleepareas ~ '^-?[0-9]+$' THEN numsleepareas::integer END AS sleeping_areas_count,
    CASE WHEN numhangbednets ~ '^-?[0-9]+$' THEN numhangbednets::integer END AS hanging_bednets_count,
    CASE WHEN numpeople ~ '^-?[0-9]+$' THEN numpeople::integer END AS people_count
FROM silver_havi.hbo_household;
