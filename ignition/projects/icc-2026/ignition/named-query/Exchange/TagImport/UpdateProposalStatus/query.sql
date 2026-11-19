-- Move a proposal through proposed -> accepted -> executed (or rejected).
UPDATE ex_icc_tag_import_proposal
SET status      = :status,
    accepted_at = CASE WHEN :status = 'accepted' THEN now() ELSE accepted_at END,
    executed_at = CASE WHEN :status = 'executed' THEN now() ELSE executed_at END
WHERE id = :proposalId
