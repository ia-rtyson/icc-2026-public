-- Acknowledge the oldest still-unacknowledged events older than cutoff, at
-- most maxRows of them, so the Ack column keeps changing as time passes.
UPDATE ex_icc_demo_equipment_events
SET acknowledged = 1
WHERE id IN (
    SELECT id
    FROM ex_icc_demo_equipment_events
    WHERE acknowledged = 0
      AND event_time < :cutoff
    ORDER BY event_time ASC
    LIMIT :maxRows
)
