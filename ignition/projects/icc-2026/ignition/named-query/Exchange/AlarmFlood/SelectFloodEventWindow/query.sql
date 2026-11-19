-- The time window of one stored flood event. window_end_at may be NULL for an
-- event that was never closed; callers clamp it (exchange.alarmFlood.trend.MAX_WINDOW_SECS).
-- Used by exchange.alarmFlood.trend.eventWindow; the query_tag_history tool reads the
-- same two columns and can switch to this query.
SELECT
    window_start_at,
    window_end_at,
    detected_at
FROM ex_icc_alarm_flood_event
WHERE id = :eventId
