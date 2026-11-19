-- Overwrite a saved dashboard's widgets (and name, to pick up a change of
-- case). isDemo is 0/1 to set the demo flag, or NULL to leave it as it is --
-- a NULL comparison yields NULL, and COALESCE falls back to the stored value.
UPDATE ex_icc_dashboard_config
SET widgets_json = CAST(:widgetsJson AS jsonb),
    name         = :name,
    is_demo      = COALESCE(CAST(:isDemo AS integer) <> 0, is_demo),
    updated_at   = now()
WHERE id = :id
