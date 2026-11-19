-- Designer Embeds Example page -- equipment event log.
--
-- Ported from Matt's ICC_AI_DEMO, where this table lived in the launchpad_oee
-- SQLite database. It is Postgres here so the whole stack has one database
-- (the SQLite connection is the OEE demo's, not ours) and so the query can be
-- written in the same dialect as everything else in sql/.
--
-- Idempotent, and safe to run on EVERY stack start: the seed block only fires
-- when the table is empty. It used to DELETE and re-insert unconditionally,
-- which was fine as a hand-run command but is destructive now that the
-- postgres-init service replays this file on every `docker compose up` --
-- it would wipe whatever the DemoEventsFeeder timer has accumulated.
--
-- To deliberately RE-STAMP the demo data (the page's default filter is "last
-- 24 hours", so a clone seeded months ago shows an empty table), use the
-- script library rather than this file:
--   exchange.designerEmbeds.events.backfill()
-- which repopulates relative to now() and is what the feeder maintains.

CREATE TABLE IF NOT EXISTS ex_icc_demo_equipment_events (
    id             SERIAL      NOT NULL,
    equipment_name TEXT        NOT NULL,
    area           TEXT        NOT NULL,
    event_type     TEXT        NOT NULL,
    event_time     TIMESTAMP   NOT NULL,
    severity       INTEGER     NOT NULL DEFAULT 0,
    -- 0/1 rather than boolean: the ported view passes 1/0 from a checkbox and
    -- the query compares against a list of truthy spellings.
    acknowledged   INTEGER     NOT NULL DEFAULT 0,
    notes          TEXT,
    CONSTRAINT ex_icc_demo_equipment_events_pkey PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ex_icc_demo_equipment_events_time_idx
    ON ex_icc_demo_equipment_events (event_time DESC);
CREATE INDEX IF NOT EXISTS ex_icc_demo_equipment_events_area_idx
    ON ex_icc_demo_equipment_events (area);

-- Seed 600 events across the last 14 days, but only into an empty table --
-- see the note at the top of this file.
--
-- The equipment and event type are picked by INDEX ARITHMETIC, not by
-- `ORDER BY random() LIMIT 1` in a lateral subquery. The obvious-looking
-- lateral version is wrong and wrong in a quiet way: Postgres saw the subquery
-- as uncorrelated, evaluated it once, and gave all 600 rows the same equipment
-- and the same event type. Coprime strides over the two arrays (7 over 12 and
-- 5 over 12) walk every combination instead, and are reproducible across
-- deployments for free -- no setseed needed.
INSERT INTO ex_icc_demo_equipment_events
    (equipment_name, area, event_type, event_time, severity, acknowledged, notes)
SELECT
    eq.names[1 + (g.n * 7) % 12],
    eq.areas[1 + (g.n * 7) % 12],
    ev.types[1 + (g.n * 5) % 12],
    -- spread over 14 days, denser towards now; 20161 minutes = 14 days
    now() - ((g.n * 33 % 20161) * INTERVAL '1 minute'),
    ev.sevs[1 + (g.n * 5) % 12],
    -- roughly two thirds acknowledged, and the unacknowledged ones cluster in
    -- the recent rows, which is what an operator screen actually looks like
    CASE WHEN (g.n % 3) = 0 THEN 0 ELSE 1 END,
    ev.types[1 + (g.n * 5) % 12] || ' on ' || eq.names[1 + (g.n * 7) % 12]
        || ' (' || eq.areas[1 + (g.n * 7) % 12] || ')'
FROM generate_series(1, 600) AS g(n)
CROSS JOIN (
    SELECT ARRAY['Feeder 1', 'Roaster 1', 'Roaster 2', 'Cooler 1',
                 'Destoner 1', 'Bagger 1', 'Bagger 2', 'Sealer 1',
                 'Palletizer', 'Boiler 1', 'Chiller 1', 'Compressor'] AS names,
           ARRAY['Roasting', 'Roasting', 'Roasting', 'Roasting',
                 'Cleaning', 'Packaging', 'Packaging', 'Packaging',
                 'Packaging', 'Utilities', 'Utilities', 'Utilities'] AS areas
) AS eq
CROSS JOIN (
    SELECT ARRAY['Motor overload', 'Bearing temperature', 'Vibration high',
                 'Feed jam', 'Setpoint deviation', 'Door interlock',
                 'Filter differential', 'Lubrication low', 'Comms timeout',
                 'Maintenance due', 'Operator note', 'Recipe change'] AS types,
           ARRAY[4, 3, 3, 4, 2, 5, 2, 3, 4, 1, 1, 1] AS sevs
) AS ev
WHERE NOT EXISTS (SELECT 1 FROM ex_icc_demo_equipment_events);
