-- Insert downtime events in one statement. eventsJson is a JSON array of
-- objects keyed by the column names below -- zero to two for a feeder tick,
-- ~875 for exchange.demo.downtime.backfill. start_time is text in the gateway
-- time zone, the zone JDBC would have bound a Date in.
INSERT INTO ex_icc_equipment_downtime_events
    (equipment, reason, start_time, duration_minutes)
SELECT
    r.equipment,
    r.reason,
    CAST(r.start_time AS timestamp),
    r.duration_minutes
FROM jsonb_to_recordset(CAST(:eventsJson AS jsonb)) AS r(
    equipment        text,
    reason           text,
    start_time       text,
    duration_minutes numeric(6,1)
)
