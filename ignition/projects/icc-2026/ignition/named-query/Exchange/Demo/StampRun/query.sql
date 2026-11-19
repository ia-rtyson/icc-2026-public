-- Record that a once-a-day demo reset job ran today, with a one-line result.
INSERT INTO ex_icc_demo_housekeeping (job, last_run_date, last_run_at, last_result)
VALUES (:job, CURRENT_DATE, now(), :result)
ON CONFLICT (job) DO UPDATE
SET last_run_date = CURRENT_DATE,
    last_run_at   = now(),
    last_result   = EXCLUDED.last_result
