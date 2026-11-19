SELECT count(*) AS active_count
FROM alarm_events
WHERE eventtype = 0
  AND eventtime > :since
