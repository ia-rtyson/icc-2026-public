-- Every stored source-tag row of one flood event, all columns, by tag path.
-- One row per distinct source tag, so the bound (maxRows, default 1000 when
-- null) is far above any real flood.
SELECT
    id,
    alarm_flood_event_id,
    provider,
    tag_path,
    data_type,
    history_enabled,
    history_provider,
    alarm_count,
    config_json
FROM ex_icc_alarm_flood_tag
WHERE alarm_flood_event_id = :eventId
ORDER BY tag_path ASC
LIMIT COALESCE(CAST(:maxRows AS integer), 1000)
