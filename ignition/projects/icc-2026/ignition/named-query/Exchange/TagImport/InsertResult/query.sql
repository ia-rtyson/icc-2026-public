-- Audit row for one object the agent created.
-- succeeded arrives as 0/1: named-query parameters have no boolean sqlType.
INSERT INTO ex_icc_tag_import_result
    (tag_import_proposal_id, object_type, object_name, tag_path, succeeded, message)
VALUES
    (:proposalId, :objectType, :objectName, :tagPath, CAST(:succeeded AS integer) <> 0, :message)
