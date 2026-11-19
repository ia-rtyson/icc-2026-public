-- Empty the activity log for a fresh demo cycle, keeping any run still
-- marked running unless it started more than graceSecs ago (a crashed
-- dispatch whose finish never came, not live work).
DELETE FROM ex_icc_agent_activity
WHERE status <> 'running'
   OR started_at < now() - CAST(:graceSecs AS integer) * INTERVAL '1 second'
