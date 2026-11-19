-- Every agent that has logged activity, for the Pipeline Status filter.
-- Parameterless and polled by every open dock, so cached for 2 s. Bounded at
-- 50 -- the pipeline has a handful of agents.
SELECT DISTINCT agent
FROM ex_icc_agent_activity
ORDER BY agent
LIMIT 50
