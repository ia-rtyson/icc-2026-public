-- Every saved dashboard for the Manage popup, demo rows first, then newest
-- touched, without the widgets payload. Bounded at 500 -- non-demo rows are
-- purged nightly, so a real list is a handful.
SELECT
    id,
    name,
    is_demo,
    updated_at,
    jsonb_array_length(widgets_json) AS widget_count
FROM ex_icc_dashboard_config
ORDER BY is_demo DESC, updated_at DESC
LIMIT 500
