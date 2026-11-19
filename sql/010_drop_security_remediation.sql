-- Drop the Security Audit remediation store.
--
-- The Security Audit Agent became report-only on 2026-09-30: it recommends
-- fixes in prose and has no tool that applies them. The propose/apply tools,
-- the exchange.securityAudit.remediate module and the Accept/Reject bar on the page
-- were all removed, which leaves security_remediation with no reader or writer.
--
-- Idempotent, like every file here: postgres-init replays it on every
-- `docker compose up`, and on a volume that never had the table it is a no-op.
DROP TABLE IF EXISTS security_remediation;
