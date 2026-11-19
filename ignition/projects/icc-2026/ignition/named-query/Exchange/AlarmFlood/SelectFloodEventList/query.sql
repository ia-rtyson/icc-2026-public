-- Flood events for a picker or the query_alarm_flood_events agent tool, newest
-- first. Bounded to the 200 most recent: the table only grows (one row per
-- demo run) and every caller wants the recent end. The bound is a literal, not
-- a parameter, because the agent tool calls this with an empty parameter map.
SELECT
    id AS value,
    '#' || id
        || ' · ' || to_char(detected_at, 'YYYY-MM-DD HH24:MI')
        || ' · ' || alarm_count || ' alarms'
        || ' · ' || status                                    AS label,
    detected_at,
    alarm_count,
    distinct_source_count,
    status,
    (dashboard_json IS NOT NULL)                              AS has_dashboard
FROM ex_icc_alarm_flood_event
ORDER BY detected_at DESC
LIMIT 200
