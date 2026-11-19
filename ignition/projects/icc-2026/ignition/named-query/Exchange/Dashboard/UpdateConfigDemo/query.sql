-- Set or clear a saved dashboard's demo flag (0/1). A demo row survives the
-- nightly purge. Deliberately leaves updated_at alone.
UPDATE ex_icc_dashboard_config
SET is_demo = CAST(:isDemo AS integer) <> 0
WHERE id = :id
