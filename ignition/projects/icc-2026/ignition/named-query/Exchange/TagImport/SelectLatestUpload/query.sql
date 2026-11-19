-- The most recently uploaded tag export.
SELECT id, filename, csv_text, row_count, uploaded_by, uploaded_at
FROM ex_icc_tag_import_upload
ORDER BY uploaded_at DESC, id DESC
LIMIT 1
