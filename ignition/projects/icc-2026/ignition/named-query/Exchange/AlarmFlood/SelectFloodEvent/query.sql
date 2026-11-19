-- One stored flood event, parent columns only.
-- id is returned as event_id because this row goes straight to the Alarm
-- Flood Agent, whose tools all name the flood's id event_id.
SELECT
    id AS event_id,
    status,
    detected_at,
    window_start_at,
    window_end_at,
    alarm_count,
    distinct_source_count,
    peak_rate,
    threshold_count,
    threshold_window_secs,
    CAST(round(extract(epoch from (window_end_at - window_start_at))) AS integer) AS duration_secs,
    summary_json,
    dashboard_json,
    analysis_json
FROM ex_icc_alarm_flood_event
WHERE id = :eventId
