-- gold_havi.hbo_person
-- Gold adds typed analytics fields while preserving raw CRF columns.
SELECT
    *,
    CASE
        WHEN dateofobservation ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
        THEN left(dateofobservation, 10)::date
    END AS observation_date,
    CASE WHEN individualnum ~ '^-?[0-9]+$' THEN individualnum::integer END AS individual_number,
    CASE WHEN age ~ '^-?[0-9]+([.][0-9]+)?$' THEN age::double precision END AS age_years
FROM silver_havi.hbo_person;
