-- Store the agent's structured proposal and hand back its id.
INSERT INTO ex_icc_tag_import_proposal (tag_import_upload_id, proposal_json, rationale, status)
VALUES (:uploadId, CAST(:proposalJson AS jsonb), :rationale, 'proposed')
RETURNING id
