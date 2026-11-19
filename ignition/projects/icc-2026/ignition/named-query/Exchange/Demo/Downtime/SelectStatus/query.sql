-- Pre-stage health check for the downtime feeder: row count, time span and
-- how many stations have events.
SELECT
    count(*)                  AS total,
    min(start_time)           AS oldest,
    max(start_time)           AS newest,
    count(DISTINCT equipment) AS equipment_count
FROM ex_icc_equipment_downtime_events
