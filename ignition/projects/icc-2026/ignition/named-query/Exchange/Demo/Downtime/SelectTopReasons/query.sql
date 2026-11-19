-- Top downtime reasons by occurrence count, then total minutes. equipment
-- restricts to one station; an empty string (or NULL) means every station.
-- maxRows bounds the result (exchange.demo.downtime.topReasons caps it at 100).
SELECT
    equipment,
    reason,
    count(*)                        AS occurrences,
    round(sum(duration_minutes), 1) AS total_minutes
FROM ex_icc_equipment_downtime_events
WHERE COALESCE(CAST(:equipment AS text), '') = ''
   OR equipment = CAST(:equipment AS text)
GROUP BY equipment, reason
ORDER BY occurrences DESC, total_minutes DESC
LIMIT :maxRows
