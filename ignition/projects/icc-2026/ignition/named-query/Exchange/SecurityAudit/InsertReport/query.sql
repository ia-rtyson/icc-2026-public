-- Store one security audit run so two runs can be diffed. Run with
-- getKey=True: id is the first column of ex_icc_security_audit_report, so it
-- is the generated key returned. findingsJson / inventoryJson are JSON text.
INSERT INTO ex_icc_security_audit_report
    (project, score, finding_count, critical, high, medium, low,
     findings_json, inventory_json, markdown)
VALUES
    (:project, :score, :findingCount, :critical, :high, :medium, :low,
     CAST(:findingsJson AS jsonb), CAST(:inventoryJson AS jsonb), :markdown)
