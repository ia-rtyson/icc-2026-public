-- Parent row for one captured alarm flood. Run with getKey=True: id is
-- the first column of ex_icc_alarm_flood_event, so it is the generated key returned.
-- Called inside the collectFlood transaction, ahead of the alarm and tag rows.
INSERT INTO ex_icc_alarm_flood_event
    (status, detected_at, window_start_at, window_end_at, alarm_count,
     distinct_source_count, peak_rate, threshold_count, threshold_window_secs, summary_json)
VALUES
    (:status, :detectedTs, :windowStart, :windowEnd, :alarmCount,
     :distinctSourceCount, :peakRate, :thresholdCount, :thresholdWindowSecs,
     CAST(:summaryJson AS jsonb))
