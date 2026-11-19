SELECT
    CASE priority
        WHEN 0 THEN 'Diagnostic'
        WHEN 1 THEN 'Low'
        WHEN 2 THEN 'Medium'
        WHEN 3 THEN 'High'
        WHEN 4 THEN 'Critical'
        ELSE 'P' || priority
    END AS priority_label,
    priority,
    count(*) AS alarm_count
FROM ex_icc_alarm_flood_alarm
WHERE alarm_flood_event_id = :eventId
GROUP BY priority
ORDER BY priority ASC
