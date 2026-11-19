-- Once-a-day bookkeeping for demo reset jobs.
--
-- Gateway event scripts have no cron, so the timers poll and the job function
-- owns the "have I run today" decision. That flag cannot live in a module
-- global: a project scan reloads the script module and wipes module state,
-- which is the same thing that cost the agent activity log its history before
-- it became a table.
--
-- job is the natural key (Exchange/Demo/StampRun upserts ON CONFLICT (job)),
-- so it carries a UNIQUE constraint; id is the style guide's surrogate key.
-- 000_exchange_rename.sql rebuilds an older volume's demo_housekeeping (whose
-- primary key was job) into this shape.
--
-- Replayed on every `docker compose up` by the postgres-init service, so it is
-- CREATE ... IF NOT EXISTS with no seed -- re-running it never disturbs a
-- recorded run.
CREATE TABLE IF NOT EXISTS ex_icc_demo_housekeeping (
    id            SERIAL      NOT NULL,
    job           VARCHAR(64) NOT NULL,
    last_run_date DATE,
    last_run_at   TIMESTAMP,
    last_result   TEXT,
    CONSTRAINT ex_icc_demo_housekeeping_pkey PRIMARY KEY (id),
    CONSTRAINT ex_icc_demo_housekeeping_job_key UNIQUE (job)
);
