-- One upload by id.
SELECT id, filename, csv_text, row_count, uploaded_by, uploaded_at
FROM ex_icc_tag_import_upload
WHERE id = :uploadId
