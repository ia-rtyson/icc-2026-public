"""Renders tag-history trends as standalone SVG charts.

The Alarm Flood Agent replies in Markdown inside a Perspective chat. Markdown can
embed an image but cannot draw a chart, and a table of history rows is unreadable as
*evidence* -- you cannot see an onset in a column of numbers. So this module renders
a real chart, server-side, as SVG:

* one stacked panel per tag (small multiples), because torque in %, vibration in
  mm/s and buffer level in % share no sensible axis;
* the tag's own **alarm setpoints** drawn as dashed threshold lines, pulled from
  :mod:`exchange.alarmFlood.model` so they can never disagree with the configured alarms;
* a marker line at **onset** -- the first sample that leaves the baseline by more
  than :data:`ONSET_SIGMA` standard deviations -- and at the **trip** (the first
  Critical alarm in the event), which is what makes cause-before-effect visible at
  a glance;
* the value axis padded to always include the setpoint, so a threshold never falls
  off the top of its panel.

SVG is generated as plain text -- no imaging library, no fonts to install, scales
crisply at any size, and stays a few KB. It is served by the ``trend`` WebDev
endpoint and referenced from the agent's report as an ordinary Markdown image.
"""

import math

import exchange.alarmFlood.model as M

logger = system.util.getLogger("exchange.alarmFlood.Trend")

PROJECT = "icc-2026"

ONSET_SIGMA = 5.0
"""How many baseline standard deviations a sample must exceed to count as onset.
High enough that measurement noise never registers as a deviation."""

BASELINE_FRACTION = 0.2
"""Fraction of the window (from the left) treated as the undisturbed baseline."""

PALETTE = ["#2E86C1", "#E08A1E", "#7D3C98", "#1E8449", "#117A8B", "#5D6D7E",
		   "#8E44AD", "#2C3E50"]
"""Trace colours. Deliberately excludes the alarm reds used for setpoint lines and
the trip marker -- a normal trace in alarm-red reads as "this signal is in alarm"."""

MAX_PLOT_POINTS = 400
"""Points per trace actually drawn. As-stored 1 Hz history over a ten-minute window
is more samples than the panel has pixels, and every extra point is dead weight in
the SVG text -- the raw query stays as stored, only the drawing is thinned."""

MAX_WINDOW_SECS = 1800
"""Longest event window, in seconds, that is ever queried. A stored event is
pre-roll + cascade + hold -- normally ten minutes -- but an event whose
``window_end_at`` is NULL (still open, or never closed) would otherwise run to
*now*, which can be days of raw 1 Hz As Stored history in one request. Over the
cap the window keeps its start, because that is where the onset is, and loses
its tail."""

MAX_TAGS = 8
"""Most tags one chart or summary will query. The chart stacks one panel per tag,
so past this it is unreadable anyway, and each tag is another full-rate series."""

TAG_ROOT = "[default]Exchange/Alarm Flood/"
"""The only subtree a trend may read. The endpoint is unauthenticated, so the tag
list must not be a way to read arbitrary history off any provider."""


def _thin(points, limit=MAX_PLOT_POINTS):
	"""Evenly thin a point list for drawing, always keeping the first and last."""
	n = len(points)
	if n <= limit:
		return points
	step = float(n - 1) / (limit - 1)
	out = [points[int(round(i * step))] for i in range(limit)]
	if out[-1] != points[-1]:
		out[-1] = points[-1]
	return out

# Layout, in SVG user units.
# Default SVG width. The only consumer is render_trend_chart, whose output is an
# <img> in the ia.ai.chat report; an SVG carries an intrinsic width, so the
# browser lays the image out at this size regardless of the chat's own width.
# 720 fits the message column inside the 800px agent dock without downscaling,
# which keeps the 8.5-9px axis labels legible. The stylesheet also clamps chat
# images to max-width:100%, so a narrower dock scales rather than scrolling --
# but a chart wider than the column would still be rendered smaller than it was
# drawn, so keep this at or under the dock's content width.
_DEFAULT_WIDTH = 720

_MARGIN_LEFT = 52
_MARGIN_RIGHT = 18
_MARGIN_TOP = 40
_PANEL_HEIGHT = 96
_PANEL_GAP = 12
_AXIS_HEIGHT = 30


def _esc(text):
	"""Escape a string for inclusion in XML text or an attribute."""
	s = unicode(text) if text is not None else u""
	return (s.replace(u"&", u"&amp;").replace(u"<", u"&lt;").replace(u">", u"&gt;")
			 .replace(u'"', u"&quot;"))


def _relPathOf(fullPath):
	"""Reduce a historian column name to ``Station/Tag`` so the model can be consulted.

	Column names come back as ``Exchange/Alarm Flood/Site1/Area1/Line1/Packaging/MotorTorque``
	(or with a ``[provider]`` prefix); the model is keyed on the last two segments.
	"""
	if not fullPath:
		return None
	parts = unicode(fullPath).replace("\\", "/").split("/")
	if len(parts) < 2:
		return None
	return parts[-2] + "/" + parts[-1]


def _specFor(fullPath):
	return M.tagSpec(_relPathOf(fullPath))


def _shortLabel(fullPath):
	rel = _relPathOf(fullPath)
	return rel if rel else unicode(fullPath)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def fetchSeries(tagPaths, startDate, endDate):
	"""Return ``[{"path", "label", "unit", "points": [(epochMs, value)], ...}]``.

	Queries as stored (``returnSize=-1``) -- averaging is exactly what destroys an
	onset, so a trend meant as root-cause evidence must use raw recorded values.
	"""
	full = []
	for p in tagPaths:
		p = unicode(p).strip()
		if not p:
			continue
		p = p if p.startswith("[") else "[default]" + p
		# Contain reads to the Alarm Flood tree; anything else is dropped, not queried.
		if not p.startswith(TAG_ROOT):
			logger.warn("Trend ignored tag outside %s: %s" % (TAG_ROOT, p))
			continue
		if p not in full:
			full.append(p)
	if len(full) > MAX_TAGS:
		logger.info("Trend capped at %d tags (%d requested)" % (MAX_TAGS, len(full)))
		full = full[:MAX_TAGS]
	if not full:
		return []

	ds = system.tag.queryTagHistory(paths=full, startDate=startDate, endDate=endDate,
									returnSize=-1, returnFormat="Wide")
	colCount = ds.getColumnCount()
	names = [ds.getColumnName(c) for c in range(colCount)]
	tsCol = 0
	for i, n in enumerate(names):
		if unicode(n).lower() in ("t_stamp", "timestamp"):
			tsCol = i
			break

	series = []
	for c in range(colCount):
		if c == tsCol:
			continue
		spec = _specFor(names[c])
		series.append({
			"path": names[c],
			"label": _shortLabel(names[c]),
			"unit": (spec.get("engUnit") if spec else "") or "",
			"alarms": (spec.get("alarms") if spec else []) or [],
			"isBool": bool(spec and spec.get("kind") == "bool"),
			"points": [],
		})

	for r in range(ds.getRowCount()):
		ts = ds.getValueAt(r, tsCol)
		if ts is None:
			continue
		ms = system.date.toMillis(ts)
		si = 0
		for c in range(colCount):
			if c == tsCol:
				continue
			v = ds.getValueAt(r, c)
			if v is not None:
				try:
					series[si]["points"].append((ms, float(v)))
				except Exception:
					pass
			si += 1
	return series


def _stats(points):
	"""Baseline mean/stddev, min/max, and the detected onset for one series."""
	vals = [v for _, v in points]
	if not vals:
		return None
	n = max(3, int(len(vals) * BASELINE_FRACTION))
	base = vals[:n]
	mean = sum(base) / float(len(base))
	var = sum([(v - mean) ** 2 for v in base]) / float(len(base))
	sd = math.sqrt(var)
	# A perfectly flat baseline would make any wobble "significant"; floor the
	# threshold at 1% of the baseline so a dead-steady signal is not over-sensitive.
	threshold = max(ONSET_SIGMA * sd, abs(mean) * 0.01, 1e-6)
	onset = None
	for ms, v in points[n:]:
		if abs(v - mean) > threshold:
			onset = ms
			break
	return {"baseline": mean, "sd": sd, "min": min(vals), "max": max(vals),
			"onset": onset, "first": vals[0], "last": vals[-1]}


def eventWindow(eventId):
	"""Return ``(startDate, endDate, tripTs, label)`` for a stored flood event."""
	ds = system.db.runNamedQuery(PROJECT, "Exchange/AlarmFlood/SelectFloodEventWindow",
								 {"eventId": int(eventId)})
	if ds.getRowCount() == 0:
		raise ValueError("No stored flood event with event_id=%s" % str(eventId))
	start = ds.getValueAt(0, "window_start_at")
	end = ds.getValueAt(0, "window_end_at") or system.date.now()
	# Cap the length before padding; keep the start, where the onset lives.
	if system.date.secondsBetween(start, end) > MAX_WINDOW_SECS:
		logger.info("Event %s window clamped to %d s" % (str(eventId), MAX_WINDOW_SECS))
		end = system.date.addSeconds(start, MAX_WINDOW_SECS)
	# The trip is the first Critical alarm -- the moment effect starts, so everything
	# left of the marker is candidate cause.
	trip = None
	tds = system.db.runNamedQuery(PROJECT, "Exchange/AlarmFlood/SelectFloodTrip", {"eventId": int(eventId)})
	label = None
	if tds.getRowCount():
		trip = tds.getValueAt(0, "event_time")
		label = tds.getValueAt(0, "alarm_name")
	return (system.date.addSeconds(start, -60), system.date.addSeconds(end, 60), trip, label)


def suggestTags(eventId, limit=6):
	"""Pick the most useful tags to trend for an event: earliest-firing, history on."""
	ds = system.db.runNamedQuery(PROJECT, "Exchange/AlarmFlood/SelectTrendTags",
								 {"eventId": int(eventId), "maxTags": int(limit)})
	return [ds.getValueAt(r, "tag_path") for r in range(ds.getRowCount())]


# ---------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------

def _niceTicks(lo, hi, count=3):
	"""A few round-ish tick values spanning lo..hi."""
	if hi <= lo:
		return [lo]
	step = (hi - lo) / float(count)
	mag = 10.0 ** math.floor(math.log10(step)) if step > 0 else 1.0
	for mult in (1.0, 2.0, 2.5, 5.0, 10.0):
		if mag * mult >= step:
			step = mag * mult
			break
	start = math.ceil(lo / step) * step
	ticks = []
	v = start
	while v <= hi + step * 0.001 and len(ticks) < count + 2:
		ticks.append(v)
		v += step
	return ticks or [lo, hi]


def _fmt(v):
	if abs(v) < 0.005:
		return "0"
	av = abs(v)
	if av >= 100:
		return "%.0f" % v
	if av >= 10:
		return "%.1f" % v
	return "%.2f" % v


def buildSvg(series, startMs, endMs, title=None, tripMs=None, tripLabel=None, width=_DEFAULT_WIDTH):
	"""Render stacked trend panels as an SVG document string.

	Args:
		series (list): Output of :func:`fetchSeries`.
		startMs / endMs (long): Window bounds in epoch milliseconds.
		title (str): Heading drawn at the top left.
		tripMs (long): Optional epoch ms of the trip event, drawn as a red marker.
		tripLabel (str): Label for that marker.
		width (int): Overall SVG width in user units.

	Returns:
		unicode: A complete ``<svg>`` document.
	"""
	series = [s for s in series if s["points"]]
	if not series:
		return (u'<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="60">'
				u'<text x="12" y="34" font-family="sans-serif" font-size="13" fill="#B02020">'
				u'No history in this window for the requested tags.</text></svg>' % width)

	plotW = width - _MARGIN_LEFT - _MARGIN_RIGHT
	height = _MARGIN_TOP + len(series) * (_PANEL_HEIGHT + _PANEL_GAP) + _AXIS_HEIGHT
	span = float(endMs - startMs) or 1.0

	def xOf(ms):
		return _MARGIN_LEFT + (float(ms) - startMs) / span * plotW

	out = []
	out.append(u'<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
			   u'viewBox="0 0 %d %d" font-family="Inter, Helvetica, Arial, sans-serif">'
			   % (width, height, width, height))
	out.append(u'<rect width="%d" height="%d" fill="#FFFFFF"/>' % (width, height))
	if title:
		out.append(u'<text x="%d" y="24" font-size="15" font-weight="600" fill="#212529">%s</text>'
				   % (_MARGIN_LEFT - 4, _esc(title)))

	onsets = []
	for idx, s in enumerate(series):
		top = _MARGIN_TOP + idx * (_PANEL_HEIGHT + _PANEL_GAP)
		bottom = top + _PANEL_HEIGHT
		colour = PALETTE[idx % len(PALETTE)]
		st = _stats(s["points"])
		if st and st["onset"] and not s.get("isBool"):
			onsets.append((st["onset"], s["label"], colour))

		# Booleans are a state, not a measurement: fixed 0..1 scale, stepped edges,
		# and no baseline/peak annotation (the mean of a state is meaningless).
		isBool = bool(s.get("isBool"))

		# Value scale, padded and always inclusive of every setpoint.
		lo = st["min"]
		hi = st["max"]
		setpoints = []
		for a in s["alarms"]:
			sp = a.get("setpointA")
			if isinstance(sp, bool) or sp is None:
				continue
			try:
				sp = float(sp)
			except Exception:
				continue
			setpoints.append((sp, a.get("priority", ""), a.get("name", "")))
			lo = min(lo, sp)
			hi = max(hi, sp)
		if isBool:
			lo, hi = -0.15, 1.15
			setpoints = []
		else:
			pad = (hi - lo) * 0.12 or (abs(hi) * 0.1 or 1.0)
			lo -= pad
			hi += pad

		def yOf(v, top=top, lo=lo, hi=hi):
			return bottom - (float(v) - lo) / float(hi - lo) * _PANEL_HEIGHT

		out.append(u'<rect x="%d" y="%.1f" width="%.1f" height="%d" fill="#FAFBFC" '
				   u'stroke="#E3E6E8"/>' % (_MARGIN_LEFT, top, plotW, _PANEL_HEIGHT))

		# Horizontal gridlines + value labels.
		for tv in ([0.0, 1.0] if isBool else _niceTicks(lo, hi, 3)):
			ty = yOf(tv)
			if ty < top or ty > bottom:
				continue
			out.append(u'<line x1="%d" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#EDF0F2"/>'
					   % (_MARGIN_LEFT, ty, _MARGIN_LEFT + plotW, ty))
			label = (u"true" if tv > 0.5 else u"false") if isBool else _fmt(tv)
			out.append(u'<text x="%d" y="%.1f" font-size="9" fill="#8A9099" '
					   u'text-anchor="end">%s</text>' % (_MARGIN_LEFT - 6, ty + 3, _esc(label)))

		# Alarm setpoints.
		for sp, priority, name in setpoints:
			sy = yOf(sp)
			if sy < top - 1 or sy > bottom + 1:
				continue
			spColour = "#B02020" if priority in ("High", "Critical") else "#E08A1E"
			out.append(u'<line x1="%d" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" '
					   u'stroke-width="1" stroke-dasharray="5 3" opacity="0.85"/>'
					   % (_MARGIN_LEFT, sy, _MARGIN_LEFT + plotW, sy, spColour))
			out.append(u'<text x="%.1f" y="%.1f" font-size="8.5" fill="%s" '
					   u'text-anchor="end">%s %s</text>'
					   % (_MARGIN_LEFT + plotW - 3, sy - 3, spColour, _esc(_fmt(sp)),
						  _esc(priority or "")))

		# The trace, plus a soft fill beneath it.
		raw = _thin(s["points"])
		pts = [(xOf(ms), yOf(v)) for ms, v in raw]
		if isBool:
			# Square edges: a discrete tag holds its value until it changes.
			stepped = []
			for i, (x, y) in enumerate(pts):
				if i:
					stepped.append((x, pts[i - 1][1]))
				stepped.append((x, y))
			if stepped:
				stepped.append((_MARGIN_LEFT + plotW, stepped[-1][1]))
			pts = stepped
		poly = u" ".join([u"%.1f,%.1f" % (x, y) for x, y in pts])
		out.append(u'<polygon points="%.1f,%.1f %s %.1f,%.1f" fill="%s" opacity="0.10"/>'
				   % (pts[0][0], bottom, poly, pts[-1][0], bottom, colour))
		out.append(u'<polyline points="%s" fill="none" stroke="%s" stroke-width="1.6" '
				   u'stroke-linejoin="round"/>' % (poly, colour))

		# Panel label block.
		station = s["label"].split("/")[0]
		name = s["label"].split("/")[-1]
		# Opaque backing so setpoint lines and the trace do not run through the text.
		labelWidth = 8 + 6.2 * max(len(name), len(station) + 4, 18)
		out.append(u'<rect x="%d" y="%.1f" width="%.1f" height="%d" fill="#FFFFFF" '
				   u'opacity="0.86"/>' % (_MARGIN_LEFT + 2, top + 3, labelWidth, 40))
		out.append(u'<text x="%d" y="%.1f" font-size="11" font-weight="600" fill="#212529">%s</text>'
				   % (_MARGIN_LEFT + 7, top + 14, _esc(name)))
		out.append(u'<text x="%d" y="%.1f" font-size="8.5" fill="#8A9099">%s</text>'
				   % (_MARGIN_LEFT + 7, top + 26,
					  _esc(station + (u"   " + s["unit"] if s["unit"] else u""))))
		if st and not isBool:
			out.append(u'<text x="%d" y="%.1f" font-size="8.5" fill="#6C757D">'
					   u'base %s   peak %s</text>'
					   % (_MARGIN_LEFT + 7, top + 38,
						  _esc(_fmt(st["baseline"])), _esc(_fmt(st["max"]))))

	plotTop = _MARGIN_TOP
	plotBottom = _MARGIN_TOP + len(series) * (_PANEL_HEIGHT + _PANEL_GAP) - _PANEL_GAP

	# Onset marker: earliest deviation across all panels -- the cause candidate.
	if onsets:
		onsets.sort()
		oms, olabel, _ = onsets[0]
		ox = xOf(oms)
		out.append(u'<line x1="%.1f" y1="%d" x2="%.1f" y2="%.1f" stroke="#1E8449" '
				   u'stroke-width="1.2" stroke-dasharray="4 3"/>'
				   % (ox, plotTop, ox, plotBottom))
		out.append(u'<text x="%.1f" y="%d" font-size="9" font-weight="600" fill="#1E8449">'
				   u'first deviation %s  %s</text>'
				   % (min(ox + 4, width - 200), plotTop - 6,
					  _esc(system.date.format(system.date.fromMillis(long(oms)), "HH:mm:ss")),
					  _esc(olabel.split("/")[-1])))

	# Trip marker: first Critical alarm.
	if tripMs:
		tx = xOf(tripMs)
		out.append(u'<line x1="%.1f" y1="%d" x2="%.1f" y2="%.1f" stroke="#B02020" '
				   u'stroke-width="1.6"/>' % (tx, plotTop, tx, plotBottom))
		out.append(u'<text x="%.1f" y="%.1f" font-size="9" font-weight="600" fill="#B02020" '
				   u'text-anchor="end">%s  %s</text>'
				   % (tx - 4, plotBottom + 12,
					  _esc(system.date.format(system.date.fromMillis(long(tripMs)), "HH:mm:ss")),
					  _esc(tripLabel or "TRIP")))

	# Shared time axis.
	axisY = plotBottom + _AXIS_HEIGHT - 8
	out.append(u'<line x1="%d" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#C6CBD1"/>'
			   % (_MARGIN_LEFT, plotBottom + 4, _MARGIN_LEFT + plotW, plotBottom + 4))
	for i in range(5):
		frac = i / 4.0
		ms = startMs + span * frac
		x = _MARGIN_LEFT + plotW * frac
		anchor = "start" if i == 0 else ("end" if i == 4 else "middle")
		out.append(u'<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#C6CBD1"/>'
				   % (x, plotBottom + 4, x, plotBottom + 8))
		out.append(u'<text x="%.1f" y="%.1f" font-size="9" fill="#6C757D" text-anchor="%s">%s</text>'
				   % (x, axisY, anchor,
					  _esc(system.date.format(system.date.fromMillis(long(ms)), "HH:mm:ss"))))

	out.append(u'</svg>')
	return u"".join(out)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

FOCUS_LEAD_RAMPS = 2.5
FOCUS_TRAIL_RAMPS = 3.0
FOCUS_MIN_SECS = 60


def _focusWindow(series, startMs, endMs, tripMs):
	"""Narrow the window to the interesting part: the ramp, plus context either side.

	A flood event's stored window spans the pre-roll, the cascade and the hold --
	often ten minutes or more. The *cause* can occupy a fraction of that: the drive
	can bind and part the belt in 10 seconds. Plotted across the full window that
	ramp is a vertical line one pixel wide, which is useless as evidence.

	So scale the view to the ramp actually measured -- from the earliest onset to the
	trip -- and show a few ramp-lengths either side. A 10 s ramp yields a ~90 s view;
	a 150 s ramp yields the best part of ten minutes. Self-tuning, so it reads well
	whatever ``Simulator/DegradeSecs`` is set to.

	Returns ``(startMs, endMs, focused)``.
	"""
	onsets = [_stats(s["points"])["onset"] for s in series
			  if s["points"] and not s.get("isBool") and _stats(s["points"])["onset"]]
	if not onsets or not tripMs:
		return startMs, endMs, False
	onsetMs = min(onsets)
	rampMs = max(float(tripMs) - float(onsetMs), 4000.0)
	lead = rampMs * FOCUS_LEAD_RAMPS
	trail = rampMs * FOCUS_TRAIL_RAMPS
	fStart = max(startMs, onsetMs - lead)
	fEnd = min(endMs, tripMs + trail)
	if fEnd - fStart < FOCUS_MIN_SECS * 1000:
		grow = (FOCUS_MIN_SECS * 1000 - (fEnd - fStart)) / 2.0
		fStart = max(startMs, fStart - grow)
		fEnd = min(endMs, fEnd + grow)
	if fEnd <= fStart:
		return startMs, endMs, False
	return fStart, fEnd, True


def _clip(series, startMs, endMs):
	"""Restrict every series to a sub-window, keeping one point either side so the
	trace still enters and leaves the panel rather than starting mid-air."""
	out = []
	for s in series:
		pts = s["points"]
		kept = [(ms, v) for ms, v in pts if startMs <= ms <= endMs]
		if not kept and pts:
			kept = pts[-1:]
		before = [p for p in pts if p[0] < startMs]
		after = [p for p in pts if p[0] > endMs]
		if before:
			kept = [(startMs, before[-1][1])] + kept
		if after:
			kept = kept + [(endMs, after[0][1])]
		clone = dict(s)
		clone["points"] = kept
		out.append(clone)
	return out


def svgForEvent(eventId, tagPaths=None, width=_DEFAULT_WIDTH, focus=True):
	"""Render the trend chart for a stored flood event.

	Args:
		eventId (int): ``ex_icc_alarm_flood_event.id``.
		tagPaths (list): Tags to plot. Defaults to the earliest-firing historised
			tags in the event, which is what root-cause work wants.
		width (int): SVG width.
		focus (bool): When True (default) the view auto-narrows around the measured
			ramp so a fast fault is legible. Pass False for the whole stored window.

	Returns:
		unicode: SVG document.
	"""
	start, end, trip, tripLabel = eventWindow(eventId)
	paths = tagPaths or suggestTags(eventId)
	series = fetchSeries(paths, start, end)
	startMs = system.date.toMillis(start)
	endMs = system.date.toMillis(end)
	tripMs = system.date.toMillis(trip) if trip else None

	focused = False
	if focus:
		fStart, fEnd, focused = _focusWindow(series, startMs, endMs, tripMs)
		if focused:
			series = _clip(series, fStart, fEnd)
			startMs, endMs = fStart, fEnd

	title = "Flood event %s  |  %s  ->  %s%s" % (
		str(eventId),
		system.date.format(system.date.fromMillis(long(startMs)), "HH:mm:ss"),
		system.date.format(system.date.fromMillis(long(endMs)), "HH:mm:ss"),
		("   (focused on fault onset)" if focused else ""))
	return buildSvg(series, startMs, endMs, title=title,
					tripMs=tripMs, tripLabel=tripLabel, width=width)


def onsetSummary(eventId, tagPaths=None):
	"""Return per-tag baseline / peak / onset facts, ordered earliest onset first.

	The agent quotes these numbers in prose next to the chart, so the report stays
	specific without reprinting a table of raw samples.
	"""
	start, end, trip, tripLabel = eventWindow(eventId)
	paths = tagPaths or suggestTags(eventId)
	rows = []
	for s in fetchSeries(paths, start, end):
		st = _stats(s["points"])
		if not st:
			continue
		rows.append({
			"tag": s["label"],
			"unit": s["unit"],
			"baseline": round(st["baseline"], 2),
			"peak": round(st["max"], 2),
			"min": round(st["min"], 2),
			"samples": len(s["points"]),
			"onset": (system.date.format(system.date.fromMillis(long(st["onset"])),
										"yyyy-MM-dd HH:mm:ss") if st["onset"] else None),
		})
	rows.sort(key=lambda r: (r["onset"] is None, r["onset"]))
	return {"event_id": int(eventId),
			"window": {"start": system.date.format(start, "yyyy-MM-dd HH:mm:ss"),
					   "end": system.date.format(end, "yyyy-MM-dd HH:mm:ss")},
			"trip": (system.date.format(trip, "yyyy-MM-dd HH:mm:ss") if trip else None),
			"trip_alarm": tripLabel,
			"tags": rows}
