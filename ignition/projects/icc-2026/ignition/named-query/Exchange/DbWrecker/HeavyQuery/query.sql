-- Deliberately expensive query, for demonstrating long-running-query
-- diagnostics (and giving the AI Diagnostic Digest something to find).
--
-- Ported from Matt's `dbwrecker`. Three changes:
--   * reads ex_icc_dbwrecker_load (sql/005_dbwrecker.sql) instead of
--     sqlt_data_1_2026_06, a monthly historian partition that does not exist on
--     this gateway -- and which the alarm-flood sim would be writing to;
--   * every Postgres double-colon cast is written CAST(x AS type). The
--     double-colon form collides with named-query parameter parsing, and this
--     project has been bitten by that before (see CLAUDE.md). Never write a
--     colon-prefixed word in a comment here either: the parser does not skip
--     comments, so it becomes a bound placeholder;
--   * the fan-out is sized down from 50,000 rows x 8 to 200 x 6. The original
--     shape would have been ~1.6e11 pair comparisons against this table --
--     not "slow", but effectively unbounded, on the same Postgres that serves
--     the alarm-flood historian. 200 x 6 gives ~1.4M pairs: a few seconds of
--     real CPU on top of the 10 s sleep, still plainly a slow query, and safe
--     to fire 20 of concurrently from the page.
--
-- To make it heavier for a bigger stage moment, raise LIMIT 200 first (cost
-- grows with its square), then generate_series(1, 6), then the pg_sleep.
WITH delay AS MATERIALIZED (
    SELECT pg_sleep(10)
), sampled AS MATERIALIZED (
    SELECT
        d.tagid,
        d.t_stamp,
        COALESCE(d.floatvalue, CAST(d.intvalue AS double precision), 0.0) AS numeric_value,
        COALESCE(d.dataintegrity, 0) AS quality,
        md5(COALESCE(d.stringvalue, '') || ':' || CAST(d.t_stamp AS text) || ':' || CAST(d.tagid AS text)) AS payload_hash
    FROM ex_icc_dbwrecker_load d
    CROSS JOIN delay
    ORDER BY md5(CAST(d.t_stamp AS text) || ':' || CAST(d.tagid AS text)), d.t_stamp DESC
    LIMIT 200
), expanded AS MATERIALIZED (
    SELECT
        s.tagid,
        s.t_stamp,
        s.numeric_value,
        s.quality,
        s.payload_hash,
        g.n,
        md5(s.payload_hash || ':' || CAST(g.n AS text)) AS expanded_hash
    FROM sampled s
    CROSS JOIN generate_series(1, 6) AS g(n)
), workload AS MATERIALIZED (
    SELECT
        a.tagid,
        COUNT(*) AS comparisons,
        SUM(ABS((a.numeric_value + a.n) - (b.numeric_value + b.n))) AS total_delta,
        SUM(((a.t_stamp - b.t_stamp) % 97) * ((a.quality + b.quality) % 31)) AS checksum,
        SUM(length(md5(a.expanded_hash || b.expanded_hash))) AS hash_work
    FROM expanded a
    JOIN expanded b
        ON a.tagid = b.tagid
        OR ((a.t_stamp + a.n) % 1009) = ((b.t_stamp + b.n) % 1009)
        OR substring(a.expanded_hash, 1, 2) = substring(b.expanded_hash, 1, 2)
    GROUP BY a.tagid
)
SELECT
    tagid,
    comparisons,
    total_delta,
    checksum,
    hash_work
FROM workload
ORDER BY comparisons DESC, hash_work DESC
LIMIT 25
