-- Pre-stage health check: how many dashboards are saved, how many are demo
-- rows, and how many tonight's purge would take right now.
SELECT
    count(*) AS total,
    count(*) FILTER (WHERE is_demo) AS demo,
    count(*) FILTER (WHERE NOT is_demo AND updated_at < date_trunc('day', now())) AS stale
FROM ex_icc_dashboard_config
