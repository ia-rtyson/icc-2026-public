-- Close an ex_icc_agent_activity row: final status, optional summary/detail (NULL
-- keeps what is there), finish time and whole-second duration.
UPDATE ex_icc_agent_activity
SET status        = :status,
    summary       = COALESCE(CAST(:summary AS text), summary),
    detail        = COALESCE(CAST(:detail AS text), detail),
    finished_at   = now(),
    duration_secs = GREATEST(0, CAST(EXTRACT(EPOCH FROM (now() - started_at)) AS integer))
WHERE id = :id
