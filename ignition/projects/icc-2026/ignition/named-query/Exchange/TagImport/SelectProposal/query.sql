-- One proposal by id.
SELECT id, tag_import_upload_id, CAST(proposal_json AS text) AS proposal_json, rationale,
       status, created_at, accepted_at, executed_at
FROM ex_icc_tag_import_proposal
WHERE id = :proposalId
