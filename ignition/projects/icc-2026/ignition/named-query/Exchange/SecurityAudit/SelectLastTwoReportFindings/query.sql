-- The findings of the two most recent stored audits, newest first, for
-- exchange.securityAudit.report.compareToPrevious.
SELECT
    id,
    generated_at,
    findings_json
FROM ex_icc_security_audit_report
ORDER BY id DESC
LIMIT 2
