-- Store an uploaded PLC tag-export CSV and hand back its id.
INSERT INTO ex_icc_tag_import_upload (filename, csv_text, row_count, uploaded_by)
VALUES (:filename, :csvText, :rowCount, :uploadedBy)
RETURNING id
