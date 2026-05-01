DROP TABLE IF EXISTS gold_havi.ds_qc_summary;
CREATE TABLE gold_havi.ds_qc_summary AS
SELECT
    CURRENT_DATE AS run_date,
    severity,
    COUNT(*) AS issue_count
FROM gold_havi.ds_validation_report
GROUP BY severity
ORDER BY severity;
