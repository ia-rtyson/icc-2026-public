-- ============================================================================
-- 009 — drop the Golden Batch demo (removed 2026-09-30)
-- ============================================================================
-- The Golden Batch Coffee Roast demo was removed from the project, along with
-- the migrations that created its tables (001_schema.sql, 002_recipes.sql,
-- 006_golden_batch_output_targets.sql -- numbers from before the 2026-09-30
-- renumber around 000_exchange_rename.sql). postgres-init replays sql/*.sql on
-- every `docker compose up`, so this file is what cleans the tables out of an
-- existing postgres-data volume (the demo laptop and the AI server alike).
--
-- Idempotent: IF EXISTS makes every replay after the first a no-op. CASCADE
-- takes the indexes, constraints and the trials -> runs foreign key with them.
-- ============================================================================

DROP TABLE IF EXISTS golden_batch_chat_messages CASCADE;
DROP TABLE IF EXISTS golden_batch_trials        CASCADE;
DROP TABLE IF EXISTS golden_batch_recipes       CASCADE;
DROP TABLE IF EXISTS golden_batch_runs          CASCADE;
