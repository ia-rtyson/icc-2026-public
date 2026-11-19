SELECT
    ae.id,
    ae.eventid,
    ae.source,
    ae.displaypath,
    ae.priority,
    ae.eventtype,
    ae.eventflags,
    ae.eventtime,
    ed.dtype       AS event_value_dtype,
    ed.intvalue    AS event_value_int,
    ed.floatvalue  AS event_value_float,
    ed.strvalue    AS event_value_str
FROM alarm_events ae
LEFT JOIN alarm_event_data ed
    ON ed.id = ae.id AND ed.propname = 'eventValue'
WHERE ae.eventtype = 0
  AND ae.eventtime >= :windowStart
  AND ae.eventtime <= :windowEnd
ORDER BY ae.eventtime ASC
