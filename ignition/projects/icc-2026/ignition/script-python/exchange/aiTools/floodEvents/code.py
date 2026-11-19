"""Alarm-flood event reads and trend charts for the Alarm Flood Agent's tools.

Backs query_alarm_flood_events and render_trend_chart. The data comes from the
Exchange/AlarmFlood/* named queries, exchange.alarmFlood.data.getFloodEvent and exchange.alarmFlood.trend;
this module only shapes it for a model.
"""
import sys

import exchange.alarmFlood.data
import exchange.alarmFlood.trend
import exchange.aiTools.serialize
import exchange.aiTools.tagPaths
import exchange.aiTools.toolArgs

logger = system.util.getLogger("exchange.aiTools.FloodEvents")

PROJECT = "icc-2026"
EVENT_LIST_QUERY = "Exchange/AlarmFlood/SelectFloodEventList"

# Relative URL of the trend WebDev endpoint: it resolves against whatever host
# the session is served from, so the same report works on localhost and on the
# demo server
TREND_URL = "/system/webdev/%s/exchange/alarm-flood/trend" % PROJECT

DEFAULT_CHART_WIDTH = 720
MIN_CHART_WIDTH = 480
MAX_CHART_WIDTH = 1600

_CHART_INSTRUCTIONS = ("Embed chart_markdown verbatim in the report under a Trend "
	"Evidence heading. Do NOT also print a table of raw history "
	"samples -- cite the numbers in tag_facts in prose instead. "
	"The chart already draws each tag's alarm setpoints, the first "
	"deviation marker and the trip marker.")


def listEvents():
	"""Return every stored flood event, most recent first.

	Returns:
		dict: {mode: "list", count, events}. Each event is one row of the
			Exchange/AlarmFlood/SelectFloodEventList named query, JSON-safe.
	"""
	ds = system.db.runNamedQuery(PROJECT, EVENT_LIST_QUERY, {})
	events = []
	for row in range(ds.getRowCount()):
		event = {}
		for col in range(ds.getColumnCount()):
			event[ds.getColumnName(col)] = exchange.aiTools.serialize.jsonSafe(ds.getValueAt(row, col))
		events.append(event)
	return {"mode": "list", "count": len(events), "events": events}


def eventDetail(eventId, includeAlarms=True):
	"""Return one flood event in full: summary, tag inventory, optional SOE alarms.

	Args:
		eventId (int): The ``ex_icc_alarm_flood_event.id``.
		includeAlarms (bool): False replaces the sequence-of-events list with a
			count, for a lighter payload.

	Returns:
		dict: {mode: "detail", found: True, event} or, when there is no such
			event, {mode: "detail", event_id, found: False, message}.
	"""
	event = exchange.alarmFlood.data.getFloodEvent(eventId, includeChildren=True)
	if event is None:
		return {"mode": "detail", "event_id": eventId, "found": False,
			"message": "No stored flood event with that event_id."}
	if not includeAlarms and "alarms" in event:
		event["alarms_omitted"] = len(event.get("alarms") or [])
		del event["alarms"]
	return {"mode": "detail", "found": True, "event": exchange.aiTools.serialize.jsonSafe(event)}


def queryEvents(eventId=None, includeAlarms=None):
	"""Entry point for query_alarm_flood_events: list, or one event in detail.

	Args:
		eventId (object): Raw event_id argument. None, 0 or negative lists every
			event -- models sometimes fill a non-null 0 for the optional id.
		includeAlarms (object): Raw include_alarms argument. Defaults to True.

	Returns:
		dict: The listEvents() or eventDetail() payload, or
			{status: "invalid_argument", ...} for a non-integer event_id.
	"""
	try:
		resolvedId = exchange.aiTools.toolArgs.optionalInt(eventId, "event_id")
	except exchange.aiTools.toolArgs.ArgumentError, error:
		return exchange.aiTools.toolArgs.invalidArgument(error, "query_alarm_flood_events")
	if resolvedId is None or resolvedId <= 0:
		return listEvents()
	wantAlarms = True if includeAlarms is None else bool(includeAlarms)
	return eventDetail(resolvedId, wantAlarms)


def _chartWidth(width):
	"""Clamp a requested chart width, falling back to the default."""
	if width is None:
		return DEFAULT_CHART_WIDTH
	try:
		return max(MIN_CHART_WIDTH, min(MAX_CHART_WIDTH, int(width)))
	except:
		return DEFAULT_CHART_WIDTH


def trendChart(eventId, tagPaths=None, fullWindow=None, width=None):
	"""Build the Markdown chart reference and per-tag facts for a flood event.

	The chart itself is rendered by the project's trend WebDev endpoint, so the
	returned markdown is an ordinary image reference that renders in the chat.

	Args:
		eventId (object): Raw event_id argument (required).
		tagPaths (object): Comma-separated or JSON-array paths. Defaults to the
			earliest-firing historised tags in the event.
		fullWindow (object): True plots the whole stored window; the default
			auto-focuses on the measured ramp.
		width (object): Chart width in px, clamped to 480-1600. Default 720.

	Returns:
		dict: The render_trend_chart payload, or {status: "invalid_argument", ...}
			for a non-integer event_id.

	Raises:
		ValueError: If event_id is missing or names no stored event.
	"""
	if eventId is None or unicode(eventId).strip() in ("", "0", "None", "null"):
		raise ValueError("event_id is required -- get it from query_alarm_flood_events first")
	try:
		resolvedId = exchange.aiTools.toolArgs.optionalInt(eventId, "event_id")
	except exchange.aiTools.toolArgs.ArgumentError, error:
		return exchange.aiTools.toolArgs.invalidArgument(error, "render_trend_chart")

	paths = None
	if tagPaths is not None and unicode(tagPaths).strip():
		paths = exchange.aiTools.tagPaths.parseTagPaths(tagPaths) or None

	chartWidth = _chartWidth(width)
	isFull = False
	if fullWindow is not None:
		isFull = exchange.aiTools.toolArgs.isTrue(fullWindow)

	try:
		summary = exchange.alarmFlood.trend.onsetSummary(resolvedId, tagPaths=paths)
	except:
		logger.warn("onsetSummary failed for event %s: %s" % (resolvedId, sys.exc_info()[1]))
		raise
	plotted = paths or [row["tag"] for row in summary["tags"]]

	url = "%s?event_id=%d&width=%d" % (TREND_URL, resolvedId, chartWidth)
	if paths:
		url += "&tags=" + "%2C".join([unicode(p).replace(" ", "%20") for p in paths])
	if isFull:
		url += "&full=1"

	return {
		"event_id": resolvedId,
		"chart_markdown": "![Trend evidence - flood event %d](%s)" % (resolvedId, url),
		"chart_url": url,
		"window": summary["window"],
		"focused": (not isFull),
		"trip": summary["trip"],
		"trip_alarm": summary["trip_alarm"],
		"tags_plotted": plotted,
		"tag_facts": summary["tags"],
		"instructions": _CHART_INSTRUCTIONS
	}
