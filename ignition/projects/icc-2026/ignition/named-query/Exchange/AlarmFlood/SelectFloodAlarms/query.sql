SELECT
    event_time,
    tag_path,
    alarm_name,
    priority,
    CASE priority
        WHEN 0 THEN 'Diagnostic'
        WHEN 1 THEN 'Low'
        WHEN 2 THEN 'Medium'
        WHEN 3 THEN 'High'
        WHEN 4 THEN 'Critical'
        ELSE 'P' || priority
    END AS priority_label,
    event_value,
    display_path
FROM ex_icc_alarm_flood_alarm
WHERE alarm_flood_event_id = :eventId
ORDER BY event_time ASC
