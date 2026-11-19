-- Security Audit Agent storage.
--
-- Mirrors exchange.securityAudit.report._ensureTable() in
-- ignition/projects/icc-2026/ignition/script-python/exchange/securityAudit/. Kept in
-- sync by hand; that function stays in place as the idempotent manual
-- fallback for a stack whose postgres volume predates this file.
--
-- Replayed on every `docker compose up` by postgres-init, so it must stay
-- idempotent.
--
-- The security_remediation table that used to live here is gone: the audit
-- became report-only on 2026-09-30. 010_drop_security_remediation.sql drops it
-- from existing volumes. 000_exchange_rename.sql renames an older volume's
-- security_audit_report (report_id) to the names below.

-- One row per saved audit run. findings_json and inventory_json are stored so
-- two runs can be diffed -- "what changed since last week" is the second
-- question a security report gets asked, and it cannot be answered from a chat
-- transcript. markdown holds the report the user actually read, so the stored
-- record and the conversation cannot drift apart.
CREATE TABLE IF NOT EXISTS ex_icc_security_audit_report (
	id             SERIAL      NOT NULL,
	generated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
	project        TEXT        NOT NULL,
	score          INTEGER     NOT NULL,
	finding_count  INTEGER     NOT NULL,
	critical       INTEGER     NOT NULL DEFAULT 0,
	high           INTEGER     NOT NULL DEFAULT 0,
	medium         INTEGER     NOT NULL DEFAULT 0,
	low            INTEGER     NOT NULL DEFAULT 0,
	findings_json  JSONB,
	inventory_json JSONB,
	markdown       TEXT,
	CONSTRAINT ex_icc_security_audit_report_pkey PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ex_icc_security_audit_report_generated_idx
	ON ex_icc_security_audit_report (generated_at DESC);
