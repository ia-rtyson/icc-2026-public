-- Retention purge: delete every downtime event that started before cutoff.
DELETE FROM ex_icc_equipment_downtime_events
WHERE start_time < :cutoff
