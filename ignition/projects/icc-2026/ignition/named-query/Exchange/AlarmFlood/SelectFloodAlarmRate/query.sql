SELECT
    date_bin(make_interval(secs => 5), event_time, TIMESTAMP '2000-01-01') AS bucket,
    count(*) AS alarm_count
FROM ex_icc_alarm_flood_alarm
WHERE alarm_flood_event_id = :eventId
GROUP BY bucket
ORDER BY bucket ASC
