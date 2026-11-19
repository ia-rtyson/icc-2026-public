-- Tag Import Agent — staging tables.
--
-- The AI Chat component cannot hand structured data to a Perspective Tree, and the
-- agent cannot read an uploaded file on its own. These three tables are the seam:
--
--   reference export read --> ex_icc_tag_import_upload   --> save_proposal keys to it
--   agent analysis        --> ex_icc_tag_import_proposal --> Tree component binding
--   create_proposed_structure --> ex_icc_tag_import_result --> what was created
--
-- Idempotent DDL, replayed on every `docker compose up` by postgres-init.
-- 000_exchange_rename.sql brings an older volume's tag_import_* tables
-- (upload_id / proposal_id / result_id keys) up to these names first.

CREATE TABLE IF NOT EXISTS ex_icc_tag_import_upload (
    id            SERIAL      NOT NULL,
    filename      TEXT        NOT NULL,
    csv_text      TEXT        NOT NULL,
    row_count     INTEGER,
    uploaded_by   TEXT,
    uploaded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ex_icc_tag_import_upload_pkey PRIMARY KEY (id)
);

COMMENT ON TABLE ex_icc_tag_import_upload IS
    'Raw PLC tag-export CSV the agent read from the hosted reference folder. save_proposal keys a proposal to one of these rows.';

CREATE INDEX IF NOT EXISTS ex_icc_tag_import_upload_time_idx
    ON ex_icc_tag_import_upload (uploaded_at DESC);


-- One row per proposal the agent produces. status drives the UI:
--   proposed  — agent has analyzed, user has not decided
--   accepted  — user said to go ahead; agent is cleared to create it
--   executed  — creation finished
--   rejected  — user declined
--   archived  — on file when the page was opened; not the one on screen
CREATE TABLE IF NOT EXISTS ex_icc_tag_import_proposal (
    id                   SERIAL      NOT NULL,
    tag_import_upload_id INTEGER     NOT NULL,
    proposal_json        JSONB       NOT NULL,
    rationale            TEXT,
    status               TEXT        NOT NULL DEFAULT 'proposed',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    accepted_at          TIMESTAMPTZ,
    executed_at          TIMESTAMPTZ,
    CONSTRAINT ex_icc_tag_import_proposal_pkey PRIMARY KEY (id),
    CONSTRAINT ex_icc_tag_import_proposal_upload_fkey FOREIGN KEY (tag_import_upload_id)
        REFERENCES ex_icc_tag_import_upload (id) ON DELETE CASCADE
);

COMMENT ON TABLE ex_icc_tag_import_proposal IS
    'Structured UDT/instance/standalone-tag proposal written by the agent save_proposal tool. Bound to the Perspective Tree.';
COMMENT ON COLUMN ex_icc_tag_import_proposal.proposal_json IS
    'Shape: {udt_definitions:[{name,folder,members:[{name,datatype,source_tag}],rationale}], udt_instances:[{udt_name,instance_name,folder,overrides}], standalone_tags:[{name,datatype,folder,value_source,rationale}], unresolved:[{tag,reason}]}';

CREATE INDEX IF NOT EXISTS ex_icc_tag_import_proposal_upload_idx
    ON ex_icc_tag_import_proposal (tag_import_upload_id, created_at DESC);


-- Audit trail of what the agent actually created. Every row must be a path under
-- 'Exchange/Tag Import Agent/' — the tools enforce it, this table records it.
CREATE TABLE IF NOT EXISTS ex_icc_tag_import_result (
    id                     SERIAL      NOT NULL,
    tag_import_proposal_id INTEGER,
    object_type            TEXT        NOT NULL,   -- udt_definition | udt_instance | tag
    object_name            TEXT        NOT NULL,
    tag_path               TEXT        NOT NULL,
    succeeded              BOOLEAN     NOT NULL DEFAULT TRUE,
    message                TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ex_icc_tag_import_result_pkey PRIMARY KEY (id),
    CONSTRAINT ex_icc_tag_import_result_proposal_fkey FOREIGN KEY (tag_import_proposal_id)
        REFERENCES ex_icc_tag_import_proposal (id) ON DELETE CASCADE
);

COMMENT ON TABLE ex_icc_tag_import_result IS
    'What the agent created, one row per object. tag_path is always under the Exchange/Tag Import Agent folder.';

CREATE INDEX IF NOT EXISTS ex_icc_tag_import_result_proposal_idx
    ON ex_icc_tag_import_result (tag_import_proposal_id, created_at);
