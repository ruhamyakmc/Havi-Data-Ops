-- gold_havi.hbo_person
-- Gold adds typed analytics fields while preserving raw CRF columns.
-- Observation hours outside the 6 pm – 6 am collection window are set to -6
-- (not observed / not applicable) since collections are never conducted outside
-- that window. Affected columns: obs_4_5pm, obs_5_6pm (pre-6pm) and
-- obs_6_7am, obs_7_8am, obs_8_9am, obs_9_10am (post-6am).
SELECT
    session_id, hhid, dateofobservation, individualnum, age, gender,
    CASE WHEN dateofobservation <= '2026-05-31' THEN -6 ELSE obs_4_5pm::integer END AS obs_4_5pm,
    CASE WHEN dateofobservation <= '2026-05-31' THEN -6 ELSE obs_5_6pm::integer END AS obs_5_6pm,
    obs_6_7pm, obs_7_8pm, obs_8_9pm, obs_9_10pm,
    obs_10_11pm, obs_11pm_12am, obs_12_1am, obs_1_2am,
    obs_2_3am, obs_3_4am, obs_4_5am, obs_5_6am,
    CASE WHEN dateofobservation <= '2026-05-31' THEN -6 ELSE obs_6_7am::integer END AS obs_6_7am,
    CASE WHEN dateofobservation <= '2026-05-31' THEN -6 ELSE obs_7_8am::integer END AS obs_7_8am,
    CASE WHEN dateofobservation <= '2026-05-31' THEN -6 ELSE obs_8_9am::integer END AS obs_8_9am,
    CASE WHEN dateofobservation <= '2026-05-31' THEN -6 ELSE obs_9_10am::integer END AS obs_9_10am,
    uniqueid, swver, survey_id, starttime, stoptime, lastmod,
    run_uuid, file_name, file_path, country, community, extracted_at,
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
