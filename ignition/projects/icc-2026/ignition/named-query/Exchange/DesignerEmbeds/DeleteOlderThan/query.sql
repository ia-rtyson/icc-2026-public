-- Retention purge: delete every demo equipment event older than cutoff.
DELETE FROM ex_icc_demo_equipment_events
WHERE event_time < :cutoff
