-- DB Wrecker page -- a table whose only job is to be expensive to query.
--
-- Matt's version of the heavy query read `sqlt_data_1_2026_06`, a MONTHLY
-- historian partition from his gateway. This stack's historian partitions
-- daily (sqlt_data_1_20260908), so that table does not exist here -- and
-- pointing a deliberately abusive self-join at the live historian partition
-- that the Alarm Flood sim is writing to at 1 Hz would be a poor idea anyway.
-- So the load gets its own fixed table, seeded once, with the same column
-- shape the original query expected.
--
-- Sizing is deliberate. The query samples 200 of these rows and fans each out
-- 6x, then self-joins on three OR'd predicates: 1,200 x 1,200 = ~1.4M pairs of
-- md5 work, a few seconds of CPU on top of a 10 s pg_sleep. That is long
-- enough to be unmistakably a long-running query in Gateway diagnostics while
-- staying dominated by the sleep rather than by CPU burn -- this Postgres also
-- serves the alarm-flood historian at 1 Hz, and the page can fire 20 of these
-- concurrently. Turn the knobs in Exchange/DbWrecker/HeavyQuery, not here.
--
-- Idempotent: creates and seeds only if empty.
--
-- The columns deliberately keep the historian's names (tagid, t_stamp,
-- floatvalue, ...) rather than the style guide's word_per_underscore form
-- (tag_id, float_value): the heavy query was written against a real sqlt_data
-- partition and this table stands in for one. A documented exception, not an
-- oversight -- only the table name follows the ex_icc_ convention.

CREATE TABLE IF NOT EXISTS ex_icc_dbwrecker_load (
    id            SERIAL           NOT NULL,
    tagid         INTEGER          NOT NULL,
    t_stamp       BIGINT           NOT NULL,
    floatvalue    DOUBLE PRECISION,
    intvalue      INTEGER,
    stringvalue   TEXT,
    dataintegrity INTEGER          NOT NULL DEFAULT 192,
    CONSTRAINT ex_icc_dbwrecker_load_pkey PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ex_icc_dbwrecker_load_tagid_idx
    ON ex_icc_dbwrecker_load (tagid, t_stamp DESC);

INSERT INTO ex_icc_dbwrecker_load (tagid, t_stamp, floatvalue, intvalue, stringvalue, dataintegrity)
SELECT
    1 + (g.n % 25),
    CAST(EXTRACT(EPOCH FROM now()) * 1000 AS BIGINT) - (g.n * 1000),
    CASE WHEN g.n % 4 = 0 THEN NULL ELSE 40 + 30 * sin(g.n / 45.0) END,
    CASE WHEN g.n % 4 = 0 THEN g.n % 500 ELSE NULL END,
    CASE WHEN g.n % 7 = 0 THEN 'batch-' || CAST(g.n / 7 AS TEXT) ELSE NULL END,
    CASE WHEN g.n % 199 = 0 THEN 0 ELSE 192 END
FROM generate_series(1, 2000) AS g(n)
WHERE NOT EXISTS (SELECT 1 FROM ex_icc_dbwrecker_load);
