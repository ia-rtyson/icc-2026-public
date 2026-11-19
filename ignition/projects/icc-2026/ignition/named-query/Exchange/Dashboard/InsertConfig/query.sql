-- Save a new dashboard. Run with getKey=True: id is the first column of
-- ex_icc_dashboard_config, so it is the generated key returned. isDemo arrives as
-- 0/1 (named-query parameters have no boolean sqlType).
INSERT INTO ex_icc_dashboard_config (name, widgets_json, is_demo)
VALUES (:name, CAST(:widgetsJson AS jsonb), CAST(:isDemo AS integer) <> 0)
