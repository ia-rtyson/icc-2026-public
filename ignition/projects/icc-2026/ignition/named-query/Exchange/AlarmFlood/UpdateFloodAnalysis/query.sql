-- Attach or replace the LLM analysis stored against a flood event.
-- markAnalyzed arrives as 0/1 (named-query parameters have no boolean sqlType);
-- non-zero also moves the event to status 'analyzed'.
UPDATE ex_icc_alarm_flood_event
SET analysis_json = CAST(:analysisJson AS jsonb),
    status        = CASE WHEN CAST(:markAnalyzed AS integer) <> 0 THEN 'analyzed' ELSE status END,
    updated_at    = now()
WHERE id = :eventId
