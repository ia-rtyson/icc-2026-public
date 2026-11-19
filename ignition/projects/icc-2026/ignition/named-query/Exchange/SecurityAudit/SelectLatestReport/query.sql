-- Headline figures of the most recent stored security audit.
SELECT
    id,
    generated_at,
    project,
    score,
    finding_count,
    critical,
    high,
    medium,
    low
FROM ex_icc_security_audit_report
ORDER BY id DESC
LIMIT 1
