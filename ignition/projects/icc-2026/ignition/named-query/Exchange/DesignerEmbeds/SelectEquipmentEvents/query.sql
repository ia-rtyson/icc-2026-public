-- Ported from Matt's `aitest` query (SQLite -> Postgres).
--
-- Two changes beyond the dialect. First, SQLite's julianday() arithmetic on an
-- epoch-millis number is gone: startTime and endTime are declared as DateTime
-- parameters, so they are compared to event_time directly, the same way
-- Exchange/AlarmFlood/SelectEventsInWindow does it. Dividing them by 1000 was the bug --
-- Ignition had already converted the value to a timestamp by the time Postgres
-- saw it, which failed with "invalid input syntax for type numeric".
-- Second, the acknowledged comparison drops the original's list of truthy
-- spellings ('1','true','YES', ...). That existed because SQLite is loosely
-- typed; here the parameter is declared as an integer and the page sends 1 or 0
-- from a checkbox, so a direct comparison is both correct and honest about what
-- the page can actually send.
--
-- NOTE: do not write a parameter reference with its leading colon anywhere in
-- these comments. Ignition's named-query parser scans the raw text for those
-- tokens and turns each one into a JDBC placeholder, but Postgres ignores
-- anything inside a `--` comment. The counts then disagree and every execution
-- dies with "The column index is out of range: 9, number of columns: 8".
SELECT id,
       equipment_name,
       area,
       event_type,
       event_time,
       severity,
       acknowledged,
       notes
FROM ex_icc_demo_equipment_events
WHERE (:area IS NULL OR :area = '' OR area = :area)
  AND event_time >= :startTime
  AND event_time <  :endTime
  AND severity >= :minSeverity
  AND acknowledged = :acknowledged
ORDER BY event_time DESC
LIMIT :rowLimit
