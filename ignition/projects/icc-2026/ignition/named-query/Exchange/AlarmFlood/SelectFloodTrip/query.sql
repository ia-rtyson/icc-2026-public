-- The trip of a flood event: its first Critical (priority 4) alarm. Everything
-- before it on a trend is candidate cause. Zero rows when the event has none.
SELECT
    event_time,
    alarm_name
FROM ex_icc_alarm_flood_alarm
WHERE alarm_flood_event_id = :eventId
  AND priority = 4
ORDER BY event_time ASC
LIMIT 1
