-- Pre-stage health check for the Designer Embeds demo table: row count, time
-- span, unacknowledged total, and unacknowledged events since the given time
-- (exchange.designerEmbeds.events.status passes now minus 24 hours -- the page's default filter).
SELECT
    count(*)                                                    AS total,
    min(event_time)                                             AS oldest,
    max(event_time)                                             AS newest,
    count(*) FILTER (WHERE acknowledged = 0)                    AS unacknowledged,
    count(*) FILTER (WHERE acknowledged = 0 AND event_time >= :since) AS unacknowledged_last_24h
FROM ex_icc_demo_equipment_events
