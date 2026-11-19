-- One saved dashboard by id, with its widgets array as JSON text.
SELECT
    id,
    name,
    is_demo,
    CAST(widgets_json AS text) AS widgets_text
FROM ex_icc_dashboard_config
WHERE id = :id
