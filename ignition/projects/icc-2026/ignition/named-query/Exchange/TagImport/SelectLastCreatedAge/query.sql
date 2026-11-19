-- Seconds since the Tag Import Agent last created something, or NULL if it
-- never has. Drives exchange.tagImport.core.purgeDemoFolder, which empties the
-- demo folder 10 minutes after a create. Computed here so the age is measured
-- on one clock.
SELECT EXTRACT(EPOCH FROM (now() - MAX(created_at))) AS age_secs
FROM ex_icc_tag_import_result
WHERE succeeded
