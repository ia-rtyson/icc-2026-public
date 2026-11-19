-- The Report Issue pipeline's run log, which used to exist only as Jython DDL.
--
-- ex_icc_agent_activity -- exchange.issueReport.pipeline's run log behind the
--                          Pipeline Status dock. Mirrors
--                          exchange.issueReport.pipeline.setupActivityTable().
--
-- The Jython function used to run its DDL on every call, and the Pipeline
-- Status dock (runWhileHidden) polls every 2 s per session -- five DDL
-- statements per poll. It now runs at most once per script lifetime; this
-- migration is what makes the table exist before the first call at all.
--
-- dashboard_widget_catalog used to be created here too. Nothing has written it
-- since the AlarmFloodWidgets module was deleted, so 000_exchange_rename.sql
-- drops it.
--
-- Replayed on every `docker compose up` by the postgres-init service, so
-- everything here is IF NOT EXISTS with no seed.

CREATE TABLE IF NOT EXISTS ex_icc_agent_activity (
	id            BIGSERIAL    NOT NULL,
	agent         VARCHAR(128) NOT NULL,
	stage         VARCHAR(32),
	issue         VARCHAR(32),
	event         VARCHAR(32)  NOT NULL DEFAULT 'run',
	status        VARCHAR(32)  NOT NULL DEFAULT 'running',
	started_at    TIMESTAMP    NOT NULL DEFAULT now(),
	finished_at   TIMESTAMP,
	duration_secs INTEGER,
	summary       TEXT,
	detail        TEXT,
	prompt        TEXT,
	CONSTRAINT ex_icc_agent_activity_pkey PRIMARY KEY (id)
);

-- Added after the first version shipped; a no-op on a table created above.
ALTER TABLE ex_icc_agent_activity ADD COLUMN IF NOT EXISTS prompt TEXT;

CREATE INDEX IF NOT EXISTS ex_icc_agent_activity_agent_idx   ON ex_icc_agent_activity (agent);
CREATE INDEX IF NOT EXISTS ex_icc_agent_activity_started_idx ON ex_icc_agent_activity (started_at DESC);
CREATE INDEX IF NOT EXISTS ex_icc_agent_activity_issue_idx   ON ex_icc_agent_activity (issue);
