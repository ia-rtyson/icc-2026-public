SELECT
    tag_path,
    count(*) AS alarm_count
FROM ex_icc_alarm_flood_alarm
WHERE alarm_flood_event_id = :eventId
GROUP BY tag_path
ORDER BY alarm_count DESC, tag_path ASC
LIMIT 10
