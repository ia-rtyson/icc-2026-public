"""Alarm-flood detection support and data collection.

This project library captures the alarms that make up a detected alarm flood
and persists them, plus the configuration of every source tag involved, into a
set of custom PostgreSQL tables so the event can later be visualised and
analysed (including by an LLM).

Tables (created by ``setupTables``):

* ``ex_icc_alarm_flood_event`` -- one row per detected flood (parent). Carries JSONB
  columns ``summary_json`` / ``dashboard_json`` / ``analysis_json`` so the
  structure stays dynamic -- a dashboard definition or analysis result can be
  attached to the event after the fact.
* ``ex_icc_alarm_flood_alarm`` -- one row per journal event belonging to the flood.
* ``ex_icc_alarm_flood_tag``   -- one row per DISTINCT source tag, with its full
  ``system.tag.getConfiguration`` output and whether it has history.

The detector (a 5-second gateway timer) calls :func:`countRecentEvents` to
decide when a flood is happening, then calls :func:`collectFlood` with the
flood window once the storm subsides. :func:`collectFlood` is deliberately
standalone so it can be called from anywhere -- a script console, a button, a
message handler, or the timer.
"""

import sys

DB = "postgres"
PROJECT = "icc-2026"
NQ_COUNT = "Exchange/AlarmFlood/CountActiveEvents"
NQ_WINDOW = "Exchange/AlarmFlood/SelectEventsInWindow"
NQ_INSERT_EVENT = "Exchange/AlarmFlood/InsertFloodEvent"
NQ_INSERT_ALARMS = "Exchange/AlarmFlood/InsertFloodAlarms"
NQ_INSERT_TAGS = "Exchange/AlarmFlood/InsertFloodTags"
NQ_UPDATE_DASHBOARD = "Exchange/AlarmFlood/UpdateFloodDashboard"
NQ_UPDATE_ANALYSIS = "Exchange/AlarmFlood/UpdateFloodAnalysis"
NQ_EVENT = "Exchange/AlarmFlood/SelectFloodEvent"
NQ_EVENT_ALARMS = "Exchange/AlarmFlood/SelectFloodEventAlarms"
NQ_EVENT_TAGS = "Exchange/AlarmFlood/SelectFloodEventTags"

_PRIORITY_LABELS = {0: "Diagnostic", 1: "Low", 2: "Medium", 3: "High", 4: "Critical"}

logger = system.util.getLogger("exchange.alarmFlood.Data")


# ---------------------------------------------------------------------------
# Source-path parsing
# ---------------------------------------------------------------------------

def parseAlarmSource(source):
	"""Parse a journal ``source`` qualified path into its parts.

	A journal source looks like::

	    prov:default:/tag:Exchange/Alarm Flood/Site1/Area1/Line1/Kitting/BinLevel:/alm:Kitting Bin Level High

	Args:
		source (str): The raw ``alarm_events.source`` value.

	Returns:
		dict: ``{"provider", "tagPath", "alarmName", "fullPath"}``. ``fullPath``
		is the ``[provider]tagPath`` form usable by ``system.tag.getConfiguration``;
		any part that could not be parsed is ``None``.
	"""
	provider = None
	tagPath = None
	alarmName = None
	if source:
		for seg in str(source).split(":/"):
			if seg.startswith("prov:"):
				provider = seg[len("prov:"):]
			elif seg.startswith("tag:"):
				tagPath = seg[len("tag:"):]
			elif seg.startswith("alm:"):
				alarmName = seg[len("alm:"):]
	fullPath = None
	if provider is not None and tagPath is not None:
		fullPath = "[%s]%s" % (provider, tagPath)
	return {"provider": provider, "tagPath": tagPath, "alarmName": alarmName, "fullPath": fullPath}


def _areaOf(tagPath):
	"""Best-effort area label from a tag path (first three folders, e.g. Site/Area/Line)."""
	if not tagPath:
		return "(unknown)"
	parts = str(tagPath).split("/")
	if len(parts) >= 4:
		return "/".join(parts[0:4])
	if len(parts) > 1:
		return "/".join(parts[0:-1])
	return tagPath


def _eventValue(ds, row):
	"""Pull the ``eventValue`` property out of a SelectEventsInWindow row as a string."""
	dtype = ds.getValueAt(row, "event_value_dtype")
	if dtype is None:
		return None
	try:
		if dtype == 0:
			v = ds.getValueAt(row, "event_value_int")
		elif dtype == 1:
			v = ds.getValueAt(row, "event_value_float")
		else:
			v = ds.getValueAt(row, "event_value_str")
	except:
		e = sys.exc_info()[1]
		logger.warn("eventValue extract failed: %s" % str(e))
		return None
	if v is None:
		return None
	return unicode(v)


# ---------------------------------------------------------------------------
# Schema setup
# ---------------------------------------------------------------------------

def setupTables():
	"""Create the alarm-flood tables if they do not exist. Idempotent."""
	stmts = []
	stmts.append("""
		CREATE TABLE IF NOT EXISTS ex_icc_alarm_flood_event (
			id                    BIGSERIAL    NOT NULL,
			status                VARCHAR(32)  NOT NULL DEFAULT 'collecting',
			detected_at           TIMESTAMP    NOT NULL,
			window_start_at       TIMESTAMP    NOT NULL,
			window_end_at         TIMESTAMP,
			alarm_count           INTEGER      NOT NULL DEFAULT 0,
			distinct_source_count INTEGER      NOT NULL DEFAULT 0,
			peak_rate             INTEGER,
			threshold_count       INTEGER,
			threshold_window_secs INTEGER,
			summary_json          JSONB,
			dashboard_json        JSONB,
			analysis_json         JSONB,
			created_at            TIMESTAMP    NOT NULL DEFAULT now(),
			updated_at            TIMESTAMP    NOT NULL DEFAULT now(),
			CONSTRAINT ex_icc_alarm_flood_event_pkey PRIMARY KEY (id)
		)""")
	stmts.append("""
		CREATE TABLE IF NOT EXISTS ex_icc_alarm_flood_alarm (
			id                   BIGSERIAL    NOT NULL,
			alarm_flood_event_id BIGINT       NOT NULL,
			journal_id      INTEGER,
			journal_eventid VARCHAR(255),
			source          VARCHAR(512),
			provider        VARCHAR(128),
			tag_path        VARCHAR(512),
			alarm_name      VARCHAR(255),
			display_path    VARCHAR(255),
			priority        INTEGER,
			event_type      INTEGER,
			event_flags     INTEGER,
			event_value     TEXT,
			event_time      TIMESTAMP,
			CONSTRAINT ex_icc_alarm_flood_alarm_pkey PRIMARY KEY (id),
			CONSTRAINT ex_icc_alarm_flood_alarm_event_fkey FOREIGN KEY (alarm_flood_event_id)
				REFERENCES ex_icc_alarm_flood_event (id) ON DELETE CASCADE
		)""")
	stmts.append("CREATE INDEX IF NOT EXISTS ex_icc_alarm_flood_alarm_event_idx "
				 "ON ex_icc_alarm_flood_alarm (alarm_flood_event_id)")
	stmts.append("""
		CREATE TABLE IF NOT EXISTS ex_icc_alarm_flood_tag (
			id                   BIGSERIAL   NOT NULL,
			alarm_flood_event_id BIGINT      NOT NULL,
			provider         VARCHAR(128),
			tag_path         VARCHAR(512),
			data_type        VARCHAR(64),
			history_enabled  BOOLEAN     NOT NULL DEFAULT FALSE,
			history_provider VARCHAR(128),
			alarm_count      INTEGER     NOT NULL DEFAULT 0,
			config_json      JSONB,
			CONSTRAINT ex_icc_alarm_flood_tag_pkey PRIMARY KEY (id),
			CONSTRAINT ex_icc_alarm_flood_tag_event_fkey FOREIGN KEY (alarm_flood_event_id)
				REFERENCES ex_icc_alarm_flood_event (id) ON DELETE CASCADE
		)""")
	stmts.append("CREATE INDEX IF NOT EXISTS ex_icc_alarm_flood_tag_event_idx "
				 "ON ex_icc_alarm_flood_tag (alarm_flood_event_id)")
	for sql in stmts:
		system.db.runUpdateQuery(sql, database=DB)
	logger.info("Alarm-flood tables verified/created")
	return True


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def countRecentEvents(windowSecs=30):
	"""Return the number of *active* alarm-journal events in the trailing window.

	Args:
		windowSecs (int): Size of the trailing window, in seconds.

	Returns:
		int: Count of ``eventtype = 0`` events since ``now - windowSecs``.
	"""
	since = system.date.addSeconds(system.date.now(), -int(windowSecs))
	ds = system.db.runNamedQuery(PROJECT, NQ_COUNT, {"since": since})
	if ds.getRowCount() == 0:
		return 0
	return int(ds.getValueAt(0, "active_count"))


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

def _toPlain(obj, depth=0):
	"""Convert an arbitrary (possibly Java, possibly self-referential) tag-config
	object into a JSON-safe structure of plain dicts/lists/primitives.

	``system.util.jsonEncode`` cannot be used directly on a 8.3 tag configuration
	object -- it contains circular references and overflows the stack. This walks
	the structure with a hard depth cap and stringifies anything it does not
	recognise, so serialisation always terminates.
	"""
	if depth > 15:
		return unicode(obj)
	if obj is None or isinstance(obj, (bool, int, long, float)):
		return obj
	if isinstance(obj, basestring):
		return obj
	# java.util.Map (getConfiguration returns Map-backed objects)
	if hasattr(obj, "keySet"):
		out = {}
		try:
			for k in obj.keySet():
				out[unicode(k)] = _toPlain(obj.get(k), depth + 1)
			return out
		except:
			return unicode(obj)
	if isinstance(obj, dict):
		out = {}
		for k, v in obj.items():
			out[unicode(k)] = _toPlain(v, depth + 1)
		return out
	if isinstance(obj, (list, tuple)):
		return [_toPlain(x, depth + 1) for x in obj]
	# java.util.List / other iterables
	if hasattr(obj, "iterator") or hasattr(obj, "__iter__"):
		try:
			return [_toPlain(x, depth + 1) for x in obj]
		except:
			return unicode(obj)
	return unicode(obj)


def _tagConfig(fullPath):
	"""Return (configDict, dataType, historyEnabled, historyProvider) for a tag path.

	Uses ``system.tag.getConfiguration`` and normalises the result to a plain,
	JSON-safe dict via :func:`_toPlain` (a direct ``jsonEncode`` overflows on the
	config object's circular references).
	"""
	cfgDict = {}
	if not fullPath:
		return cfgDict, None, False, None
	try:
		cfgList = system.tag.getConfiguration(fullPath, False)
	except:
		e = sys.exc_info()[1]
		logger.warn("getConfiguration failed for %s: %s" % (fullPath, str(e)))
		return cfgDict, None, False, None
	if not cfgList:
		return cfgDict, None, False, None
	try:
		cfgDict = _toPlain(cfgList[0])
		if not isinstance(cfgDict, dict):
			cfgDict = {"_raw": cfgDict}
	except:
		e = sys.exc_info()[1]
		logger.warn("config convert failed for %s: %s" % (fullPath, str(e)))
		cfgDict = {}
	dataType = cfgDict.get("dataType")
	historyEnabled = bool(cfgDict.get("historyEnabled", False))
	historyProvider = cfgDict.get("historyProvider")
	return cfgDict, dataType, historyEnabled, historyProvider


def collectFlood(windowStart, windowEnd, detectedTs=None, thresholdCount=None,
				 thresholdWindowSecs=None, peakRate=None, preRollSecs=None):
	"""Capture every alarm in a flood window and persist it.

	Pulls all active journal events between ``windowStart`` and ``windowEnd``,
	writes a parent ``ex_icc_alarm_flood_event`` row, one ``ex_icc_alarm_flood_alarm`` row per
	event, and one ``ex_icc_alarm_flood_tag`` row per distinct source tag (with full
	tag configuration and history info). Safe to call from anywhere.

	Args:
		windowStart (Date): Start of the flood window (inclusive).
		windowEnd (Date): End of the flood window (inclusive).
		detectedTs (Date): When the flood was first detected. Defaults to now.
		thresholdCount (int): Threshold count that triggered detection (stored for reproducibility).
		thresholdWindowSecs (int): Threshold window in seconds (stored for reproducibility).
		peakRate (int): Peak active-event count observed during detection.
		preRollSecs (int): Seconds of lead-in to collect *before* ``windowStart``, so
			the stored sequence includes the precursor alarms that built up to the
			flood. Defaults to :data:`PRE_ROLL_SECS`; pass 0 to disable.

	Returns:
		long: The new ``event_id``, or ``None`` if the window contained no events.
	"""
	if detectedTs is None:
		detectedTs = system.date.now()

	detectWindowStart = windowStart
	preRoll = PRE_ROLL_SECS if preRollSecs is None else int(preRollSecs)
	if preRoll > 0:
		windowStart = system.date.addSeconds(windowStart, -preRoll)

	ds = system.db.runNamedQuery(PROJECT, NQ_WINDOW, {"windowStart": windowStart, "windowEnd": windowEnd})
	rowCount = ds.getRowCount()
	if rowCount == 0:
		logger.info("collectFlood: no events in window %s -> %s; nothing collected"
					% (str(windowStart), str(windowEnd)))
		return None

	# Build in-memory event list and per-tag aggregation.
	events = []
	tagOrder = []          # preserve first-seen order of distinct full paths
	tagAlarmCount = {}     # fullPath -> count
	tagParts = {}          # fullPath -> {"provider", "tagPath"}
	byPriority = {}
	byArea = {}
	byTag = {}

	for row in range(rowCount):
		parsed = parseAlarmSource(ds.getValueAt(row, "source"))
		priority = ds.getValueAt(row, "priority")
		ev = {
			"journal_id": ds.getValueAt(row, "id"),
			"journal_eventid": ds.getValueAt(row, "eventid"),
			"source": ds.getValueAt(row, "source"),
			"provider": parsed["provider"],
			"tag_path": parsed["tagPath"],
			"alarm_name": parsed["alarmName"],
			"display_path": ds.getValueAt(row, "displaypath"),
			"priority": priority,
			"event_type": ds.getValueAt(row, "eventtype"),
			"event_flags": ds.getValueAt(row, "eventflags"),
			"event_value": _eventValue(ds, row),
			"event_time": ds.getValueAt(row, "eventtime"),
			"full_path": parsed["fullPath"],
		}
		events.append(ev)

		fp = parsed["fullPath"]
		if fp is not None:
			if fp not in tagAlarmCount:
				tagOrder.append(fp)
				tagAlarmCount[fp] = 0
				tagParts[fp] = {"provider": parsed["provider"], "tagPath": parsed["tagPath"]}
			tagAlarmCount[fp] += 1

		pLabel = _PRIORITY_LABELS.get(priority, "P%s" % str(priority))
		byPriority[pLabel] = byPriority.get(pLabel, 0) + 1
		area = _areaOf(parsed["tagPath"])
		byArea[area] = byArea.get(area, 0) + 1
		tp = parsed["tagPath"] or ev["source"]
		byTag[tp] = byTag.get(tp, 0) + 1

	distinctCount = len(tagOrder)
	summary = {
		"alarm_count": rowCount,
		"distinct_source_count": distinctCount,
		"by_priority": byPriority,
		"by_area": byArea,
		"by_tag": byTag,
		"window_start": str(windowStart),
		"window_end": str(windowEnd),
		"detect_window_start": str(detectWindowStart),
		"pre_roll_secs": preRoll,
		"first_alarm": (str(events[0]["event_time"]) if events else None),
		"first_alarm_tag": (events[0]["tag_path"] if events else None),
		"first_alarm_name": (events[0]["alarm_name"] if events else None),
	}
	summaryJson = system.util.jsonEncode(summary)

	# Child rows are built before the transaction opens: _tagConfig reads tag
	# configuration, and that work has no business holding a DB connection
	alarmRows = []
	for ev in events:
		alarmRows.append({
			"journal_id": ev["journal_id"],
			"journal_eventid": ev["journal_eventid"],
			"source": ev["source"],
			"provider": ev["provider"],
			"tag_path": ev["tag_path"],
			"alarm_name": ev["alarm_name"],
			"display_path": ev["display_path"],
			"priority": ev["priority"],
			"event_type": ev["event_type"],
			"event_flags": ev["event_flags"],
			"event_value": ev["event_value"],
			"event_time": _sqlTs(ev["event_time"]),
		})
	tagRows = []
	for fp in tagOrder:
		cfgDict, dataType, historyEnabled, historyProvider = _tagConfig(fp)
		parts = tagParts.get(fp, {"provider": None, "tagPath": fp})
		tagRows.append({
			"provider": parts.get("provider"),
			"tag_path": parts.get("tagPath"),
			"data_type": (str(dataType) if dataType is not None else None),
			"history_enabled": bool(historyEnabled),
			"history_provider": historyProvider,
			"alarm_count": tagAlarmCount.get(fp, 0),
			"config_json": (cfgDict if cfgDict else None),
		})

	eventId = _storeFlood(
		{
			"status": "complete",
			"detectedTs": detectedTs,
			"windowStart": windowStart,
			"windowEnd": windowEnd,
			"alarmCount": rowCount,
			"distinctSourceCount": distinctCount,
			"peakRate": peakRate,
			"thresholdCount": thresholdCount,
			"thresholdWindowSecs": thresholdWindowSecs,
			"summaryJson": summaryJson,
		},
		alarmRows, tagRows)

	logger.info("collectFlood: stored event_id=%s (%d alarms, %d distinct tags)"
				% (str(eventId), rowCount, distinctCount))
	return eventId


def _sqlTs(value):
	"""Format a date as text a Postgres TIMESTAMP cast accepts, or None.

	Written in the gateway's own time zone, which is the zone JDBC uses when it
	binds a Date to a TIMESTAMP column, so a row stored through the JSON batch
	insert carries exactly the value a per-row prepared insert would have.

	Args:
		value (Date): The timestamp to format. None passes through.

	Returns:
		str: ``yyyy-MM-dd HH:mm:ss.SSS``, or None.
	"""
	if value is None:
		return None
	return system.date.format(value, "yyyy-MM-dd HH:mm:ss.SSS")


def _storeFlood(eventParams, alarmRows, tagRows):
	"""Write one flood event and all its child rows in a single transaction.

	Three statements: the parent row (for its generated ``event_id``), then every
	alarm row and every tag row as one JSON-batched insert each. Either all of it
	commits or none of it does, so a failure part-way can no longer leave an
	event row with a partial sequence of events.

	Args:
		eventParams (dict): Parameters for the ``Exchange/AlarmFlood/InsertFloodEvent``
			named query.
		alarmRows (list): One dict per journal event, keyed by column name.
		tagRows (list): One dict per distinct source tag, keyed by column name.

	Returns:
		long: The new ``event_id``.

	Raises:
		Exception: Whatever the database raised; the transaction is rolled back
			first.
	"""
	tx = system.db.beginNamedQueryTransaction(PROJECT, DB, system.db.READ_COMMITTED, 30000)
	try:
		eventId = system.db.runNamedQuery(PROJECT, NQ_INSERT_EVENT, eventParams,
										  tx=tx, getKey=True)
		if alarmRows:
			system.db.runNamedQuery(PROJECT, NQ_INSERT_ALARMS,
									{"eventId": eventId, "alarmsJson": system.util.jsonEncode(alarmRows)},
									tx=tx)
		if tagRows:
			system.db.runNamedQuery(PROJECT, NQ_INSERT_TAGS,
									{"eventId": eventId, "tagsJson": system.util.jsonEncode(tagRows)},
									tx=tx)
		system.db.commitTransaction(tx)
		return eventId
	except:
		# Bare except: a JDBC failure arrives as a Java exception, which
		# `except Exception` does not catch in Jython
		err = sys.exc_info()[1]
		logger.error("collectFlood: flood not stored, rolling back: %s" % str(err))
		system.db.rollbackTransaction(tx)
		raise
	finally:
		system.db.closeTransaction(tx)


def collectRecent(secondsBack=120):
	"""Ad-hoc: collect a flood covering the last ``secondsBack`` seconds.

	Convenience wrapper around :func:`collectFlood` for manual collection from a
	button, script console, or the runtime-test harness (which cannot pass Date
	objects). Returns the new ``event_id`` or ``None``.
	"""
	now = system.date.now()
	start = system.date.addSeconds(now, -int(secondsBack))
	return collectFlood(start, now, detectedTs=now,
						thresholdCount=THRESHOLD_COUNT, thresholdWindowSecs=WINDOW_SECS)


# ---------------------------------------------------------------------------
# Dynamic attachments (dashboard definition + LLM analysis)
# ---------------------------------------------------------------------------

def updateDashboard(eventId, dashboard):
	"""Attach or replace the dashboard definition for a flood event.

	Args:
		eventId (long): Target ``ex_icc_alarm_flood_event.id``.
		dashboard: A dict/list (JSON-encoded automatically) or a pre-encoded JSON string.

	Returns:
		int: Rows updated (1 on success, 0 if the event_id does not exist).
	"""
	if not isinstance(dashboard, basestring):
		dashboard = system.util.jsonEncode(dashboard)
	rows = system.db.runNamedQuery(PROJECT, NQ_UPDATE_DASHBOARD,
								   {"eventId": eventId, "dashboardJson": dashboard})
	logger.info("updateDashboard: event_id=%s rows=%s" % (str(eventId), str(rows)))
	return rows


def updateAnalysis(eventId, analysis, markAnalyzed=True):
	"""Attach or replace the LLM analysis for a flood event.

	Args:
		eventId (long): Target ``ex_icc_alarm_flood_event.id``.
		analysis: A dict/list (JSON-encoded automatically) or a pre-encoded JSON string.
		markAnalyzed (bool): When True, also set ``status = 'analyzed'``.

	Returns:
		int: Rows updated.
	"""
	if not isinstance(analysis, basestring):
		analysis = system.util.jsonEncode(analysis)
	# Passed as 0/1 and cast in SQL -- named-query parameters have no boolean sqlType
	rows = system.db.runNamedQuery(PROJECT, NQ_UPDATE_ANALYSIS,
								   {"eventId": eventId, "analysisJson": analysis,
									"markAnalyzed": 1 if markAnalyzed else 0})
	logger.info("updateAnalysis: event_id=%s rows=%s markAnalyzed=%s"
				% (str(eventId), str(rows), str(markAnalyzed)))
	return rows


def getFloodEvent(eventId, includeChildren=False):
	"""Return a flood event as a plain dict (JSON columns decoded).

	Args:
		eventId (long): Target ``ex_icc_alarm_flood_event.id``.
		includeChildren (bool): When True, also attach ``alarms`` and ``tags`` lists.

	Returns:
		dict or None: The event, or None if not found.
	"""
	ds = system.db.runNamedQuery(PROJECT, NQ_EVENT, {"eventId": eventId})
	if ds.getRowCount() == 0:
		return None
	event = {}
	for col in range(ds.getColumnCount()):
		name = ds.getColumnName(col)
		val = ds.getValueAt(0, col)
		if name in ("summary_json", "dashboard_json", "analysis_json") and val is not None:
			try:
				val = system.util.jsonDecode(unicode(val))
			except:
				pass
		event[name] = val
	if includeChildren:
		# maxRows None lets each query apply its own default bound
		childParams = {"eventId": eventId, "maxRows": None}
		event["alarms"] = _rowsToDicts(system.db.runNamedQuery(PROJECT, NQ_EVENT_ALARMS, childParams))
		event["tags"] = _rowsToDicts(system.db.runNamedQuery(PROJECT, NQ_EVENT_TAGS, childParams))
	return event


def _rowsToDicts(ds):
	out = []
	for row in range(ds.getRowCount()):
		d = {}
		for col in range(ds.getColumnCount()):
			d[ds.getColumnName(col)] = ds.getValueAt(row, col)
		out.append(d)
	return out


# ---------------------------------------------------------------------------
# Detector state machine (driven by the 5s gateway timer)
# ---------------------------------------------------------------------------

STATE_BASE = "[default]Exchange/Alarm Flood/Detector State"

# Defaults -- overridable by the timer / caller.
THRESHOLD_COUNT = 8        # active events within the window that constitutes a flood
WINDOW_SECS = 30           # trailing detection window
TICK_SECS = 5              # timer interval; used to convert the subside period to ticks
SUBSIDE_SECS = 30          # flood is "over" after this long below threshold
PRE_ROLL_SECS = 300        # extra lead-in captured before the detection window

# PRE_ROLL_SECS matters for root-cause work. A cascading upset is *preceded* by
# low-rate precursor alarms (rising drive torque, then vibration, then current)
# that never reach flood rate on their own, so they sit outside the 30s detection
# window. Collecting 5 minutes ahead of the window puts that lead-in into the
# stored sequence of events, which is the evidence the analysis actually needs.


ENSURE_CHECK_SECS = 60
"""How often :func:`_ensureStateTags` may probe/reconfigure -- see the matching
constant in ``exchange.alarmFlood.sim``. A Bad read does not mean the tags are gone; a
faulted tag provider reports Bad for tags that exist, so an unthrottled
probe-then-configure loop floods the gateway log without ever repairing it."""

_ENSURE_STATE = {"lastTs": 0.0}


_STATE_TAGS = [
	("FloodActive", "Boolean", False),
	("DetectedTs", "DateTime", None),
	("WindowStart", "DateTime", None),
	("PeakRate", "Int4", 0),
	("LowStreak", "Int4", 0),
	("LastEventId", "Int8", 0),
]
"""The detector's ``Detector State`` tags: name, datatype, initial value."""

STATE_PERSISTENCE = "Database"
"""Where the ``Detector State`` tags keep their value.

All six are detector runtime state, so none of them belong in the tracked config
files the ``default`` provider now persists values into. See the matching constant
in ``exchange.alarmFlood.sim``, which carries the full note -- including that this cannot be
set by editing ``Detector State/tags.json``, only through ``system.tag.configure``."""


def _stateTag(name, dtype, value):
	"""One ``Detector State`` tag config, pinned to :data:`STATE_PERSISTENCE`."""
	cfg = {"name": name, "tagType": "AtomicTag", "valueSource": "memory",
		   "dataType": dtype, "valuePersistence": STATE_PERSISTENCE}
	if value is not None:
		cfg["value"] = value
	return cfg


def applyStatePersistence():
	"""Push :data:`STATE_PERSISTENCE` onto ``Detector State`` tags that already exist.

	:func:`_ensureStateTags` returns early when the tags read Good, so it never
	reaches a folder that is already there. Idempotent; writes no values.
	"""
	configs = []
	for name, dtype, _ in _STATE_TAGS:
		configs.append({"name": name, "tagType": "AtomicTag", "valueSource": "memory",
						"dataType": dtype, "valuePersistence": STATE_PERSISTENCE})
	system.tag.configure("[default]Exchange/Alarm Flood",
						 [{"name": "Detector State", "tagType": "Folder", "tags": configs}], "m")
	logger.info("Applied Detector State value persistence: %d tags -> %s"
				% (len(configs), STATE_PERSISTENCE))
	return {"stateTags": [n for n, _, _ in _STATE_TAGS], "persistence": STATE_PERSISTENCE}


def _ensureStateTags():
	"""Create the detector state memory tags under ``Detector State`` if missing. Idempotent."""
	now = system.date.toMillis(system.date.now()) / 1000.0
	sinceLast = now - _ENSURE_STATE["lastTs"]
	# 0 <= sinceLast guards a backwards clock step (NTP correction) -- see the
	# matching comment in exchange.alarmFlood.sim.ensureSimTags.
	if _ENSURE_STATE["lastTs"] and 0 <= sinceLast < ENSURE_CHECK_SECS:
		return
	_ENSURE_STATE["lastTs"] = now

	existing = system.tag.readBlocking([STATE_BASE + "/FloodActive"])[0]
	if existing.quality.isGood():
		return
	folder = {
		"name": "Detector State",
		"tagType": "Folder",
		"tags": [_stateTag(*t) for t in _STATE_TAGS],
	}
	system.tag.configure("[default]Exchange/Alarm Flood", [folder], "m")
	verify = system.tag.readBlocking([STATE_BASE + "/FloodActive"])[0]
	if not verify.quality.isGood():
		logger.warn("Detector state tags still read %s after configure -- the tag "
					"provider is likely faulted, not the tags missing. Retrying in %ds."
					% (verify.quality, ENSURE_CHECK_SECS))
		return
	logger.info("Created alarm-flood detector state tags")


def _readState():
	paths = [STATE_BASE + "/" + n for n in
			 ["FloodActive", "DetectedTs", "WindowStart", "PeakRate", "LowStreak"]]
	qv = system.tag.readBlocking(paths)
	return {
		"floodActive": bool(qv[0].value) if qv[0].quality.isGood() and qv[0].value is not None else False,
		"detectedTs": qv[1].value,
		"windowStart": qv[2].value,
		"peakRate": int(qv[3].value) if qv[3].quality.isGood() and qv[3].value is not None else 0,
		"lowStreak": int(qv[4].value) if qv[4].quality.isGood() and qv[4].value is not None else 0,
	}


def _writeState(**kwargs):
	paths = []
	values = []
	for name, val in kwargs.items():
		paths.append(STATE_BASE + "/" + name)
		values.append(val)
	if paths:
		system.tag.writeBlocking(paths, values)


# Whether the detector is currently in a faulted state, so a fault that repeats
# every 5 s tick is logged once when it starts and once when it clears, rather
# than sixty times a minute.
_TICK_FAULT = {"active": False}


def _noteTickFault(where, exc):
	"""Log a detector fault once per fault episode.

	Args:
		where (str): Which step failed, for the log line.
		exc (object): The Python or Java exception that was caught.
	"""
	if not _TICK_FAULT["active"]:
		_TICK_FAULT["active"] = True
		logger.warn("Flood detector tick failed in %s: %s -- skipping ticks until it "
					"recovers (usually a faulted tag provider; further failures are "
					"not logged)." % (where, exc))


def detectorTick(thresholdCount=THRESHOLD_COUNT, windowSecs=WINDOW_SECS,
				 tickSecs=TICK_SECS, subsideSecs=SUBSIDE_SECS):
	"""One iteration of the flood detector. Call every ``tickSecs`` from the timer.

	Implements: detect (count >= threshold) -> stay active while the storm
	continues -> once the active count stays below threshold for ``subsideSecs``,
	capture the whole flood window via :func:`collectFlood` and reset.

	Never raises. When the tag provider is faulted, ``system.tag.configure``
	inside :func:`_ensureStateTags` throws a Java ``NullPointerException``
	(``getSecurityContext`` -> ``TagReferencePath.addPath``); that is caught
	with a bare ``except`` (``except Exception`` does not catch Java errors in
	Jython), logged once, and the tick is skipped.

	Args:
		thresholdCount (int): Active-event count that constitutes a flood.
		windowSecs (int): Trailing window the count is taken over.
		tickSecs (int): Timer period, used to convert ``subsideSecs`` to ticks.
		subsideSecs (int): How long the count must stay low before capture.

	Returns:
		dict: A small status dict describing what happened this tick (useful for
		runtime testing): ``{"count", "floodActive", "action", "eventId"}``.
		``action`` is ``"fault"`` when the tick was skipped, ``"timer_disabled"``
		when the timer's enable switch is off.
	"""
	# Timer enable switch, [default]Exchange/Demo/Control/Timers/AlarmFloodDetectorEnabled
	if not exchange.demo.control.timerEnabled("AlarmFloodDetector"):
		return {"count": None, "floodActive": None, "action": "timer_disabled", "eventId": None}
	try:
		_ensureStateTags()
		result = _detectorStep(thresholdCount, windowSecs, tickSecs, subsideSecs)
	except:
		_noteTickFault("detectorTick", sys.exc_info()[1])
		return {"count": None, "floodActive": None, "action": "fault", "eventId": None}
	if _TICK_FAULT["active"]:
		_TICK_FAULT["active"] = False
		logger.info("Flood detector recovered; ticking normally again.")
	return result


def _detectorStep(thresholdCount, windowSecs, tickSecs, subsideSecs):
	"""The body of :func:`detectorTick`, without its fault handling.

	Args:
		thresholdCount (int): Active-event count that constitutes a flood.
		windowSecs (int): Trailing window the count is taken over.
		tickSecs (int): Timer period in seconds.
		subsideSecs (int): How long the count must stay low before capture.

	Returns:
		dict: See :func:`detectorTick`.
	"""
	count = countRecentEvents(windowSecs)
	st = _readState()
	now = system.date.now()
	action = "idle"
	eventId = None

	subsideTicks = max(1, int(round(float(subsideSecs) / float(tickSecs))))

	if not st["floodActive"]:
		if count >= thresholdCount:
			windowStart = system.date.addSeconds(now, -int(windowSecs))
			_writeState(FloodActive=True, DetectedTs=now, WindowStart=windowStart,
						PeakRate=count, LowStreak=0)
			action = "flood_started"
			logger.info("Flood STARTED: %d active events in %ds window" % (count, windowSecs))
	else:
		peak = max(st["peakRate"], count)
		if count >= thresholdCount:
			_writeState(PeakRate=peak, LowStreak=0)
			action = "flood_ongoing"
		else:
			lowStreak = st["lowStreak"] + 1
			if lowStreak >= subsideTicks:
				windowEnd = now
				eventId = collectFlood(st["windowStart"], windowEnd,
									   detectedTs=st["detectedTs"],
									   thresholdCount=thresholdCount,
									   thresholdWindowSecs=windowSecs,
									   peakRate=peak)
				_writeState(FloodActive=False, PeakRate=0, LowStreak=0,
							LastEventId=(eventId if eventId is not None else 0))
				action = "flood_collected"
				logger.info("Flood ENDED: collected event_id=%s (peak=%d)" % (str(eventId), peak))
			else:
				_writeState(PeakRate=peak, LowStreak=lowStreak)
				action = "flood_subsiding"

	return {"count": count, "floodActive": (action not in ("idle", "flood_collected")),
			"action": action, "eventId": eventId}
