-- Attach or replace the dashboard definition stored against a flood event.
UPDATE ex_icc_alarm_flood_event
SET dashboard_json = CAST(:dashboardJson AS jsonb),
    updated_at     = now()
WHERE id = :eventId
