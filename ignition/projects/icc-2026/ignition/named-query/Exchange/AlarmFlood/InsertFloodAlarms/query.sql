-- Every sequence-of-events row for one flood, in a single statement.
--
-- alarmsJson is a JSON array of objects, one per journal event, keyed by the
-- column names below. One round trip instead of one INSERT per alarm, and it
-- runs inside the collectFlood transaction with the parent row. event_time
-- arrives as ISO-style text (see exchange.alarmFlood.data._sqlTs) in the gateway's own
-- time zone, which is the zone JDBC writes a TIMESTAMP in, so the stored value
-- is identical to what a per-row prepared insert produced. The format string is
-- deliberately not written here: its time separators would read as parameters.
INSERT INTO ex_icc_alarm_flood_alarm
    (alarm_flood_event_id, journal_id, journal_eventid, source, provider, tag_path, alarm_name,
     display_path, priority, event_type, event_flags, event_value, event_time)
SELECT
    CAST(:eventId AS bigint),
    r.journal_id,
    r.journal_eventid,
    r.source,
    r.provider,
    r.tag_path,
    r.alarm_name,
    r.display_path,
    r.priority,
    r.event_type,
    r.event_flags,
    r.event_value,
    CAST(r.event_time AS timestamp)
FROM jsonb_to_recordset(CAST(:alarmsJson AS jsonb)) AS r(
    journal_id      integer,
    journal_eventid varchar(255),
    source          varchar(512),
    provider        varchar(128),
    tag_path        varchar(512),
    alarm_name      varchar(255),
    display_path    varchar(255),
    priority        integer,
    event_type      integer,
    event_flags     integer,
    event_value     text,
    event_time      text
)
