-- Everything created for a proposal, for the results view.
SELECT id, object_type, object_name, tag_path, succeeded, message, created_at
FROM ex_icc_tag_import_result
WHERE tag_import_proposal_id = :proposalId
ORDER BY id
