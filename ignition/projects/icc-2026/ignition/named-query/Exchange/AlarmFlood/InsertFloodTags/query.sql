-- One row per distinct source tag of a flood, in a single statement.
--
-- tagsJson is a JSON array of objects keyed by the column names below;
-- config_json is the tag's full configuration as a nested JSON object, so it
-- lands in the JSONB column without a second encode. Runs inside the
-- collectFlood transaction with the parent row and the alarm rows.
INSERT INTO ex_icc_alarm_flood_tag
    (alarm_flood_event_id, provider, tag_path, data_type, history_enabled, history_provider,
     alarm_count, config_json)
SELECT
    CAST(:eventId AS bigint),
    r.provider,
    r.tag_path,
    r.data_type,
    COALESCE(r.history_enabled, FALSE),
    r.history_provider,
    COALESCE(r.alarm_count, 0),
    r.config_json
FROM jsonb_to_recordset(CAST(:tagsJson AS jsonb)) AS r(
    provider         varchar(128),
    tag_path         varchar(512),
    data_type        varchar(64),
    history_enabled  boolean,
    history_provider varchar(128),
    alarm_count      integer,
    config_json      jsonb
)
