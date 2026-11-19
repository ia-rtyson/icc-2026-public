-- Every stored alarm row of one flood event, in time order, all columns.
-- Feeds exchange.alarmFlood.data.getFloodEvent (and so the query_alarm_flood_events
-- agent tool). Bounded by maxRows, which defaults to 5000 when null -- a flood
-- is ~30 alarms, so the bound only ever bites on a runaway capture.
SELECT
    id,
    alarm_flood_event_id,
    journal_id,
    journal_eventid,
    source,
    provider,
    tag_path,
    alarm_name,
    display_path,
    priority,
    event_type,
    event_flags,
    event_value,
    event_time
FROM ex_icc_alarm_flood_alarm
WHERE alarm_flood_event_id = :eventId
ORDER BY event_time ASC, id ASC
LIMIT COALESCE(CAST(:maxRows AS integer), 5000)
