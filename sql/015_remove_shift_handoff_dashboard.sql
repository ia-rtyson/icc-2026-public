-- One-time removal of the saved "Shift Handoff" dashboard (2026-10-22).
--
-- It existed only on the AI server, opened to nothing from the Saved list, and
-- was flagged as a demo row, so the nightly purge never took it. Line Overview
-- -- the page's default -- is the only dashboard meant to ship.
--
-- postgres-init replays this file on every `up`, so it runs ONCE: the
-- ex_icc_demo_housekeeping row it writes is the "already done" flag, and a
-- dashboard someone later saves under that name is left alone. Both tables are
-- created by earlier files (006, 007); the to_regclass guard covers a volume
-- where they do not exist yet.

DO $$
DECLARE
    removed integer;
BEGIN
    IF to_regclass('ex_icc_dashboard_config') IS NULL
       OR to_regclass('ex_icc_demo_housekeeping') IS NULL THEN
        RETURN;
    END IF;
    IF EXISTS (SELECT 1 FROM ex_icc_demo_housekeeping
               WHERE job = 'remove_shift_handoff_dashboard') THEN
        RETURN;
    END IF;

    DELETE FROM ex_icc_dashboard_config
    WHERE name ~* '^shift\s*hand-?\s*off'
      AND name <> 'Line Overview';
    GET DIAGNOSTICS removed = ROW_COUNT;

    INSERT INTO ex_icc_demo_housekeeping (job, last_run_date, last_run_at, last_result)
    VALUES ('remove_shift_handoff_dashboard', CURRENT_DATE, now(),
            removed || ' dashboard(s) removed');
    RAISE NOTICE 'Removed % Shift Handoff dashboard(s)', removed;
END $$;
