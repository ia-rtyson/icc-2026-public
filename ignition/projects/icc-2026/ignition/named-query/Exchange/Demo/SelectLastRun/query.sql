-- When a once-a-day demo reset job last ran. Zero rows means never. Used by
-- exchange.issueReport.pipeline.purgeTickets, keyed by job.
SELECT
    last_run_date,
    last_run_at,
    last_result
FROM ex_icc_demo_housekeeping
WHERE job = :job
