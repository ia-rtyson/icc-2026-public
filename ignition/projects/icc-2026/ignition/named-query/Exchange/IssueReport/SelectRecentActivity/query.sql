-- Activity rows for the Pipeline Status dock, newest first. agent restricts
-- to one agent; an empty string (or NULL) means every agent. maxRows is
-- clamped to 1..500 by exchange.issueReport.pipeline.recentActivity.
--
-- Cached for 1 s: the dock runs while hidden and polls every 2 s per session,
-- and every session asks with the same parameters (all agents, 100 rows), so
-- concurrent viewers share one execution. A finished run shows at most a
-- second late.
SELECT
    id,
    agent,
    stage,
    issue,
    event,
    status,
    started_at,
    finished_at,
    duration_secs,
    summary,
    prompt,
    detail
FROM ex_icc_agent_activity
WHERE COALESCE(CAST(:agent AS text), '') = ''
   OR agent = CAST(:agent AS text)
ORDER BY started_at DESC, id DESC
LIMIT :maxRows
