"""Bounded tag-history reads for the query_tag_history agent tool.

History here is recorded at 1 Hz and the historian's Wide format emits one row
per recorded sample *per tag*, so an uncapped 5-tag / 30-minute As Stored query
returned 6,959 rows and 3.16 MB of JSON. That is roughly 800k tokens against the
agent's 382k context budget, so the AI module evicted the whole conversation to
make it fit -- including the alarm event the agent was investigating -- and the
agent's final answer was to ask which alarm it was looking at. A system prompt
asking the model to keep windows small is a request; the limits in this module
are the enforcement.
"""
import sys

import exchange.aiTools.serialize
import exchange.aiTools.tagPaths
import exchange.aiTools.toolArgs

logger = system.util.getLogger("exchange.aiTools.TagHistory")

PROJECT = "icc-2026"
EVENT_QUERY = "Exchange/AlarmFlood/SelectFloodEvent"

# A trailing window only ever goes this far back; see resolveWindow
MAX_SECONDS_BACK = 60

# 100k characters is ~25k tokens against a 382k budget, so several calls in one
# investigation still fit comfortably. It is set this high on purpose: at 60k a
# 5-tag event_id query had to thin 1 Hz data to one sample every 6 seconds,
# which would erase a 10 s degradation ramp -- the exact thing the Flood Agent
# is looking for.
MAX_RESULT_CHARS = 100000

# The stored event window is capped before it is queried, because the
# character cap above only applies once the full As Stored result is already
# in gateway heap. Matches exchange.alarmFlood.trend.MAX_WINDOW_SECS so the chart and the
# table can never disagree about how much of an event exists.
MAX_EVENT_WINDOW_SECS = 1800

# Pad either side of a stored event so the pre-fault baseline and the post-fault
# settle are both on the trend, not clipped at the edges
EVENT_PADDING_SECS = 60

# Tags per call. Each tag multiplies the rows the historian loads into heap
MAX_TAGS = 10

DEFAULT_RETURN_SIZE = 300

_TS_COLS = ("t_stamp", "timestamp")
_AS_STORED_NAMES = ("asstored", "raw", "stored", "none", "default")
_EVENT_ID_ABSENT = ("", "0", "none", "null")

_FORMAT_NOTE = ("Column keys are the last segment of each tag path -- see column_paths for "
	"the full path of each. A tag is omitted from a row when it had no recorded "
	"sample at that timestamp, so rows carry varying keys; that is raw historian "
	"output, not missing data.")


def parseEventId(rawEventId):
	"""Coerce the event_id argument, treating 0 and blanks as "not supplied".

	Models sometimes fill a non-null default of 0 for an optional id, so 0 and
	negative values mean the same as None.

	Args:
		rawEventId (object): The raw tool argument.

	Returns:
		int: The event id, or None when not supplied.

	Raises:
		exchange.aiTools.toolArgs.ArgumentError: If a value is supplied but is not an integer.
	"""
	if rawEventId is None or unicode(rawEventId).strip().lower() in _EVENT_ID_ABSENT:
		return None
	eventId = exchange.aiTools.toolArgs.optionalInt(rawEventId, "event_id")
	if eventId is None or eventId <= 0:
		return None
	return eventId


def eventWindow(eventId):
	"""Return the padded, capped history window for a stored flood event.

	Reads the stored window through the Exchange/AlarmFlood/SelectFloodEvent named query.
	An open event (no end yet) runs to now. The stored length is capped at
	MAX_EVENT_WINDOW_SECS from the start -- the start is kept because that is
	where the onset lives -- and then EVENT_PADDING_SECS is added either side.

	Args:
		eventId (int): The ``ex_icc_alarm_flood_event.id``.

	Returns:
		tuple: (startDate, endDate, notice). notice is None unless the window
			was capped.

	Raises:
		ValueError: If there is no event with that id.
	"""
	ds = system.db.runNamedQuery(PROJECT, EVENT_QUERY, {"eventId": eventId})
	if ds.getRowCount() == 0:
		raise ValueError("No stored flood event with event_id=%s" % str(eventId))
	startDate = ds.getValueAt(0, "window_start_at")
	endDate = ds.getValueAt(0, "window_end_at")
	if endDate is None:
		endDate = system.date.now()

	notice = None
	storedSecs = system.date.secondsBetween(startDate, endDate)
	if storedSecs > MAX_EVENT_WINDOW_SECS:
		endDate = system.date.addSeconds(startDate, MAX_EVENT_WINDOW_SECS)
		notice = ("Event %d's stored window is %d seconds long; only the first %d seconds "
			"(plus %d s padding either side) were queried, because the onset is at the "
			"start of the window. The table is bounded before querying so a long event "
			"cannot load an unbounded history result into the gateway."
			% (eventId, storedSecs, MAX_EVENT_WINDOW_SECS, EVENT_PADDING_SECS))
		logger.info("Event %d window clamped from %d s to %d s" % (eventId, storedSecs, MAX_EVENT_WINDOW_SECS))

	startDate = system.date.addSeconds(startDate, -EVENT_PADDING_SECS)
	endDate = system.date.addSeconds(endDate, EVENT_PADDING_SECS)
	return startDate, endDate, notice


def trailingWindow(secondsBack):
	"""Return a trailing window ending now, capped at MAX_SECONDS_BACK.

	Anything longer arrives at the model decimated anyway (see MAX_RESULT_CHARS),
	and the investigation that matters -- how fast a value is moving right now --
	is entirely contained in the last minute. The cap is reported, not applied
	silently, so a caller that asked for more knows what it got.

	Args:
		secondsBack (int): Requested window length. None means MAX_SECONDS_BACK.

	Returns:
		tuple: (startDate, endDate, notice). notice is None unless capped.
	"""
	requested = MAX_SECONDS_BACK if secondsBack is None else int(secondsBack)
	notice = None
	if requested > MAX_SECONDS_BACK:
		notice = ("Requested seconds_back=%d was capped to %d. A trailing window "
			"cannot go further back than %d seconds; to read a full flood "
			"window instead, pass that flood's event_id."
			% (requested, MAX_SECONDS_BACK, MAX_SECONDS_BACK))
		requested = MAX_SECONDS_BACK
	elif requested < 1:
		requested = 1
	endDate = system.date.now()
	return system.date.addSeconds(endDate, -requested), endDate, notice


def resolveAggregation(aggregationMode, returnSize):
	"""Resolve the historian aggregation mode and return size.

	"As Stored" is not an aggregationMode -- it is expressed by asking the
	historian for every recorded point (returnSize -1) with no aggregation.

	Args:
		aggregationMode (str): Requested mode; blank or an As Stored alias means raw.
		returnSize (object): Requested row count; ignored in As Stored mode.

	Returns:
		tuple: (aggregationMode or None, returnSize).
	"""
	mode = None
	if aggregationMode is not None:
		candidate = unicode(aggregationMode).strip()
		if candidate and candidate.lower().replace(" ", "").replace("_", "") not in _AS_STORED_NAMES:
			mode = candidate

	size = None
	if returnSize is not None:
		try:
			size = int(returnSize)
		except:
			size = None
	if mode is None:
		size = -1
	elif size is None or size <= 0:
		size = DEFAULT_RETURN_SIZE
	return mode, size


def _shortNames(columns):
	"""Map each column to its last path segment, de-duplicated.

	The historian names each value column with the full tag path, and that path
	is then repeated as a dict key in every row -- on a 6,959-row query the
	repeated paths were most of the payload. The legend is emitted once, in
	column_paths.
	"""
	shortFor = {}
	taken = {}
	for column in columns:
		if column in _TS_COLS:
			shortFor[column] = column
			continue
		base = column.split("/")[-1].strip() or column
		name = base
		suffix = 2
		while name in taken:
			name = "%s_%d" % (base, suffix)
			suffix += 1
		taken[name] = column
		shortFor[column] = name
	return shortFor


def _compactRows(ds, columns, shortFor):
	"""Build rows with null cells omitted, and count samples per column.

	In As Stored mode each row carries a sample for exactly one tag, so with N
	tags the table is (N-1)/N nulls -- dropping them is lossless, and it is the
	single biggest saving here.
	"""
	rows = []
	counts = {}
	for column in columns:
		if column not in _TS_COLS:
			counts[shortFor[column]] = 0
	for rowIndex in range(ds.getRowCount()):
		row = {}
		values = 0
		for colIndex in range(len(columns)):
			column = columns[colIndex]
			value = ds.getValueAt(rowIndex, colIndex)
			if value is None:
				continue
			if exchange.aiTools.serialize.isDate(value):
				value = system.date.format(value, exchange.aiTools.serialize.ISO_FORMAT)
			name = shortFor[column]
			row[name] = value
			if column not in _TS_COLS:
				values += 1
				counts[name] = counts[name] + 1
		# A row whose every value cell was null carried no information at all
		if values:
			rows.append(row)
	return rows, counts


def _enforceBudget(rows):
	"""Thin rows by a uniform stride until the JSON fits MAX_RESULT_CHARS.

	First and last sample are always kept. Striding an interleaved As Stored
	table thins every tag by roughly the same factor, so the shape of each trend
	survives. Averaging instead would hide the onset, which is the one thing
	this tool exists to find.

	Returns:
		tuple: (rows, stride). stride is 1 when nothing was dropped.
	"""
	stride = 1
	body = system.util.jsonEncode(rows)
	attempts = 0
	while len(body) > MAX_RESULT_CHARS and len(rows) > 2 and attempts < 8:
		factor = len(body) // MAX_RESULT_CHARS + 1
		kept = rows[::factor]
		if kept[-1] is not rows[-1]:
			kept.append(rows[-1])
		rows = kept
		stride = stride * factor
		body = system.util.jsonEncode(rows)
		attempts += 1
	return rows, stride


def queryHistory(tagPaths, eventId=None, secondsBack=None, returnSize=None, aggregationMode=None):
	"""Query the historian for one or more tags, bounded for an agent's context.

	Args:
		tagPaths (object): Comma-separated paths or a JSON array string. Paths
			without a [provider] prefix are assumed to be in [default].
		eventId (object): ``ex_icc_alarm_flood_event.id``. When supplied the window comes
			from that event's stored window instead of a trailing window.
		secondsBack (object): Trailing window size, used only without eventId.
		returnSize (object): Max sample rows for an aggregated query.
		aggregationMode (str): Historian aggregation. Default As Stored.

	Returns:
		dict: The wide-format result the query_tag_history tool returns, or
			{status: "invalid_argument", ...} for an argument that could not be
			coerced.

		Example: {tags: [...], window: {start, end, source}, rows: [...]}

	Raises:
		ValueError: If tagPaths is empty or eventId names no stored event.
	"""
	if tagPaths is None or not unicode(tagPaths).strip():
		raise ValueError("tag_paths is required (comma-separated paths or a JSON array string)")
	paths = exchange.aiTools.tagPaths.parseTagPaths(tagPaths, defaultProvider="default")

	try:
		resolvedEventId = parseEventId(eventId)
		resolvedSecondsBack = None
		if resolvedEventId is None:
			resolvedSecondsBack = exchange.aiTools.toolArgs.optionalInt(secondsBack, "seconds_back")
	except exchange.aiTools.toolArgs.ArgumentError, error:
		return exchange.aiTools.toolArgs.invalidArgument(error, "query_tag_history")

	# Bound the tag count before querying, not after -- every extra tag
	# multiplies the rows the historian loads
	droppedTags = []
	if len(paths) > MAX_TAGS:
		droppedTags = paths[MAX_TAGS:]
		paths = paths[:MAX_TAGS]

	if resolvedEventId is not None:
		startDate, endDate, windowNotice = eventWindow(resolvedEventId)
		windowSource = "event %s" % str(resolvedEventId)
	else:
		startDate, endDate, windowNotice = trailingWindow(resolvedSecondsBack)
		windowSource = "trailing"

	mode, size = resolveAggregation(aggregationMode, returnSize)
	kwargs = {"paths": paths, "startDate": startDate, "endDate": endDate,
		"returnSize": size, "returnFormat": "Wide"}
	if mode is not None:
		kwargs["aggregationMode"] = mode
	try:
		ds = system.tag.queryTagHistory(**kwargs)
	except:
		# Bare except: a historian fault is a Java exception, which
		# "except Exception" does not catch in Jython
		logger.warn("queryTagHistory failed for %s (%s): %s" % (paths, windowSource, sys.exc_info()[1]))
		raise

	columns = [ds.getColumnName(c) for c in range(ds.getColumnCount())]
	shortFor = _shortNames(columns)
	rows, counts = _compactRows(ds, columns, shortFor)

	# A column with no samples must be called out, rather than returning a table
	# of nulls that reads like "the process did nothing". Counted before any
	# sampling, so a thinned result can never invent an empty column.
	empty = [name for name in counts if counts[name] == 0]

	available = len(rows)
	rows, stride = _enforceBudget(rows)

	result = {
		"tags": paths,
		"window": {
			"start": system.date.format(startDate, exchange.aiTools.serialize.ISO_FORMAT),
			"end": system.date.format(endDate, exchange.aiTools.serialize.ISO_FORMAT),
			"source": windowSource
		},
		"aggregation_mode": (mode if mode is not None else "As Stored"),
		"columns": [shortFor[c] for c in columns],
		"column_paths": dict([(shortFor[c], c) for c in columns if c not in _TS_COLS]),
		"samples_per_column": counts,
		"format": _FORMAT_NOTE,
		"row_count": len(rows),
		"rows_available": available,
		"rows": rows
	}
	if windowNotice:
		result["window"]["notice"] = windowNotice
	if droppedTags:
		result["tags_notice"] = ("Only the first %d tag paths were queried; %d more were dropped: %s. "
			"Split them across several calls." % (MAX_TAGS, len(droppedTags), ", ".join(droppedTags)))
	if stride > 1:
		result["sampling"] = {
			"sampled": True,
			"stride": stride,
			"reason": ("The full result exceeded the %d-character response limit, so every "
				"%dth row is returned (first and last always kept). Trends are intact "
				"but individual samples are missing, and samples_per_column counts "
				"what was recorded in the window rather than what is in rows below. "
				"For full fidelity, query fewer tags per call or use a shorter window."
				% (MAX_RESULT_CHARS, stride))
		}
	if empty:
		# Booleans and status strings are historised OnChange, so on a short
		# window the innocent cause is the common one -- point at
		# read_tag_values rather than blaming the path
		result["warning"] = ("No samples recorded in this window for: %s. Booleans and status "
			"strings are historised OnChange, so a tag that has not changed "
			"during the window has no samples and this is expected -- call "
			"read_tag_values to get its current value. If a continuously "
			"varying analog tag is listed here, then the path is wrong or "
			"history is not enabled on it."
			% ", ".join(sorted(empty)))
	return result
