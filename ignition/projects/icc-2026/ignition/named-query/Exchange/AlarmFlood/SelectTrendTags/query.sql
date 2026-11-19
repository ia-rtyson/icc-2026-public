-- The most useful tags to trend for a flood event: the earliest-firing source
-- tags that have history enabled, first alarm first. maxTags bounds the list
-- (exchange.alarmFlood.trend.suggestTags passes its own limit).
SELECT
    a.tag_path,
    min(a.event_time) AS first_ts
FROM ex_icc_alarm_flood_alarm a
JOIN ex_icc_alarm_flood_tag t
  ON t.alarm_flood_event_id = a.alarm_flood_event_id
 AND t.tag_path = a.tag_path
WHERE a.alarm_flood_event_id = :eventId
  AND t.history_enabled = TRUE
  AND a.tag_path IS NOT NULL
GROUP BY a.tag_path
ORDER BY first_ts ASC
LIMIT :maxTags
