-- Upload history for the page's dropdown. csv_text deliberately omitted.
SELECT id, filename, row_count, uploaded_by, uploaded_at
FROM ex_icc_tag_import_upload
ORDER BY uploaded_at DESC, id DESC
LIMIT 50
