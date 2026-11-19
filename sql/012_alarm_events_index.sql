-- Index for the alarm journal's alarm_events table.
--
-- Exchange/AlarmFlood/CountActiveEvents runs every 5 s filtering
--   eventtype = 0 AND eventtime > :since
-- on alarm_events. That table is created by Ignition's alarm journal, not by
-- anything in sql/, so on a brand-new stack postgres-init runs before the
-- gateway has created it. The DO block therefore only builds the index when the
-- table already exists; the next `docker compose up` after the gateway has
-- journalled once picks it up.
--
-- Replayed on every `docker compose up` by the postgres-init service, so it is
-- guarded and IF NOT EXISTS.

DO $$
BEGIN
	IF to_regclass('public.alarm_events') IS NOT NULL THEN
		CREATE INDEX IF NOT EXISTS alarm_events_eventtime_eventtype_idx
			ON alarm_events (eventtime, eventtype);
	END IF;
END
$$;
