-- Insert demo equipment events in one statement. eventsJson is a JSON array
-- of objects keyed by the column names below -- one element for a feeder
-- tick, a few hundred for exchange.designerEmbeds.events.backfill. event_time is text in the
-- gateway time zone, the zone JDBC would have bound a Date in.
INSERT INTO ex_icc_demo_equipment_events
    (equipment_name, area, event_type, event_time, severity, acknowledged, notes)
SELECT
    r.equipment_name,
    r.area,
    r.event_type,
    CAST(r.event_time AS timestamp),
    COALESCE(r.severity, 0),
    COALESCE(r.acknowledged, 0),
    r.notes
FROM jsonb_to_recordset(CAST(:eventsJson AS jsonb)) AS r(
    equipment_name text,
    area           text,
    event_type     text,
    event_time     text,
    severity       integer,
    acknowledged   integer,
    notes          text
)
