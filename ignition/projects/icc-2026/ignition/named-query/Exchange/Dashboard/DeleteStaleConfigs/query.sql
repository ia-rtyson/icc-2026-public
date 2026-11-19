-- Nightly purge: every non-demo dashboard last touched before today (the
-- database's today). Keyed on updated_at so a layout saved late last night and
-- still being edited this morning survives. Demo rows are never touched.
DELETE FROM ex_icc_dashboard_config
WHERE is_demo = FALSE
  AND updated_at < date_trunc('day', now())
