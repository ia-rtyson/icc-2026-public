-- ============================================================================
-- Alarm Flood Agent — Postgres schema
-- Target: Postgres 15 (docker-compose service `postgres`, Ignition DB conn `postgres`)
-- Idempotent: safe to re-run. Apply with psql or the Ignition script console.
--
-- Mirrors exchange.alarmFlood.data.setupTables() in
-- ignition/projects/icc-2026/ignition/script-python/exchange/alarmFlood/data/code.py.
-- Kept in sync by hand — that function is idempotent and safe to also run
-- manually from the script console if a table needs to be reconciled later.
--
-- Tables, keys and index names follow the Exchange style (ex_icc_ prefix, id
-- PK, <table>_id FK, _at timestamps). 000_exchange_rename.sql brings an older
-- volume's alarm_flood_* tables up to these names before this file runs.
-- ============================================================================

CREATE TABLE IF NOT EXISTS ex_icc_alarm_flood_event (
    id                    BIGSERIAL    NOT NULL,
    status                VARCHAR(32)  NOT NULL DEFAULT 'collecting',
    detected_at           TIMESTAMP    NOT NULL,
    window_start_at       TIMESTAMP    NOT NULL,
    window_end_at         TIMESTAMP,
    alarm_count           INTEGER      NOT NULL DEFAULT 0,
    distinct_source_count INTEGER      NOT NULL DEFAULT 0,
    peak_rate             INTEGER,
    threshold_count       INTEGER,
    threshold_window_secs INTEGER,
    summary_json          JSONB,
    dashboard_json        JSONB,
    analysis_json         JSONB,
    created_at            TIMESTAMP    NOT NULL DEFAULT now(),
    updated_at            TIMESTAMP    NOT NULL DEFAULT now(),
    CONSTRAINT ex_icc_alarm_flood_event_pkey PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS ex_icc_alarm_flood_alarm (
    id                   BIGSERIAL    NOT NULL,
    alarm_flood_event_id BIGINT       NOT NULL,
    journal_id           INTEGER,
    journal_eventid      VARCHAR(255),
    source               VARCHAR(512),
    provider             VARCHAR(128),
    tag_path             VARCHAR(512),
    alarm_name           VARCHAR(255),
    display_path         VARCHAR(255),
    priority             INTEGER,
    event_type           INTEGER,
    event_flags          INTEGER,
    event_value          TEXT,
    event_time           TIMESTAMP,
    CONSTRAINT ex_icc_alarm_flood_alarm_pkey PRIMARY KEY (id),
    CONSTRAINT ex_icc_alarm_flood_alarm_event_fkey FOREIGN KEY (alarm_flood_event_id)
        REFERENCES ex_icc_alarm_flood_event (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ex_icc_alarm_flood_alarm_event_idx
    ON ex_icc_alarm_flood_alarm (alarm_flood_event_id);

CREATE TABLE IF NOT EXISTS ex_icc_alarm_flood_tag (
    id                   BIGSERIAL    NOT NULL,
    alarm_flood_event_id BIGINT       NOT NULL,
    provider             VARCHAR(128),
    tag_path             VARCHAR(512),
    data_type            VARCHAR(64),
    history_enabled      BOOLEAN      NOT NULL DEFAULT FALSE,
    history_provider     VARCHAR(128),
    alarm_count          INTEGER      NOT NULL DEFAULT 0,
    config_json          JSONB,
    CONSTRAINT ex_icc_alarm_flood_tag_pkey PRIMARY KEY (id),
    CONSTRAINT ex_icc_alarm_flood_tag_event_fkey FOREIGN KEY (alarm_flood_event_id)
        REFERENCES ex_icc_alarm_flood_event (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ex_icc_alarm_flood_tag_event_idx
    ON ex_icc_alarm_flood_tag (alarm_flood_event_id);
