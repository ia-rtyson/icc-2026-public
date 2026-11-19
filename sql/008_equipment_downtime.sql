-- Equipment downtime events -- one row per synthetic downtime occurrence on
-- one of the five Alarm Flood stations (Kitting, Mixing, Forming, Cooking,
-- Packaging). Feeds a "top five downtime reasons per equipment" report.
--
-- Table only, no seed -- see exchange.demo.downtime.backfill() in
-- ignition/script-python/exchange/demo/downtime for how to pre-stage history.
-- That logic needs weighted-random selection per equipment, which belongs in
-- Jython, not a SQL seed block.
--
-- Populated by the EquipmentDowntimeFeeder gateway timer (every 1 minute),
-- which also purges anything older than exchange.demo.downtime.RETENTION_DAYS (7)
-- on every tick -- see that module for the generation logic.

CREATE TABLE IF NOT EXISTS ex_icc_equipment_downtime_events (
    id               SERIAL      NOT NULL,
    equipment        TEXT        NOT NULL,
    reason           TEXT        NOT NULL,
    start_time       TIMESTAMP   NOT NULL,
    duration_minutes NUMERIC(6,1) NOT NULL,
    created_at       TIMESTAMP   NOT NULL DEFAULT now(),
    CONSTRAINT ex_icc_equipment_downtime_events_pkey PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ex_icc_equipment_downtime_events_time_idx
    ON ex_icc_equipment_downtime_events (start_time DESC);
CREATE INDEX IF NOT EXISTS ex_icc_equipment_downtime_events_equipment_idx
    ON ex_icc_equipment_downtime_events (equipment);
CREATE INDEX IF NOT EXISTS ex_icc_equipment_downtime_events_equipment_reason_idx
    ON ex_icc_equipment_downtime_events (equipment, reason);
