-- Event count per station, for exchange.demo.downtime.status. Bounded at 50: there
-- are five stations, so the bound only matters if bad data creeps in.
SELECT
    equipment,
    count(*) AS n
FROM ex_icc_equipment_downtime_events
GROUP BY equipment
ORDER BY equipment
LIMIT 50
