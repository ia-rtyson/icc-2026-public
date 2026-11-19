"""Data shaping for the Dashboard Agent's chart widgets.

Every function here returns a value already in the exact shape one
``ia.canvas-charts.*`` component wants for its ``props.data``, so a widget
template is a binding plus a one-line call rather than a script transform of its
own. Twelve inline transforms was the alternative and it does not survive a
schema change.

**Source of truth is `exchange.alarmFlood.model`.** Station order, tag names, engineering
ranges and nominal operating values are read from it rather than restated, so
`exchange.alarmFlood.control.applyModel()` and these widgets cannot drift apart. The only things
declared locally are presentation choices -- which tag stands for a station's
*rate* and which for its *buffer* -- and `verify()` asserts those against the
model.

**Flow values are % of nominal, not units/min.** The five stations measure
throughput in four different units (picks/min, cyc/min, ft/min, pkg/min) and
Mixing has no rate tag at all, so a shared axis in physical units would need
invented conversion factors. Percent of each station's own nominal is honest,
comparable across stations, and reads correctly during a jam: the blocked
station collapses first and the rest follow upstream, which is the story these
charts exist to tell.
"""

import sys

import exchange.alarmFlood.model

logger = system.util.getLogger("exchange.dashboard.Widgets")

MAX_TAGS = 12
"""Ceiling on tags per multi-tag widget -- a chart legend stops being readable
well before this, and it bounds the readBlocking."""

JOURNAL = "Alarm Journal"
"""Configured alarm journal (ignition/config/.../alarm-journal/Alarm Journal)."""

_RATE = {
	"Kitting": "PickRate",
	"Mixing": None,
	"Forming": "FormerCycleRate",
	"Cooking": "OvenBeltSpeed",
	"Packaging": "PackagesPerMinute",
}
"""The tag that stands for each station's throughput.

Mixing is ``None`` on purpose: it is a batch operation and the model gives it no
rate tag. Rather than invent one, its flow is taken as the *lower* of the
stations either side, which is what a buffer between two continuous stages
actually passes."""

_BUFFER = {
	"Kitting": "BinLevel",
	"Mixing": "TankLevel",
	"Forming": "BufferLevel",
	"Cooking": "ExitBufferLevel",
	"Packaging": "InfeedBufferLevel",
}
"""The tag that stands for each station's accumulation. These are what fill, in
order, when the line backs up."""

_HELD_BACK_PTS = 8.0
"""How far above the downstream constraint a station must run before
`throughputFunnel` annotates it. Below this it is measurement noise, not a
backup -- see that function."""

HELD = "held"
"""Sankey sink suffix for material a station is accumulating rather than
passing on. Without these branches the diagram is a single unbranched chain and
shows nothing during a backup.

Kept short on purpose: the label sits outside the node at the right-hand edge of
the plot, so "Kitting Held in buffer" was clipped by the tile in every layout
the agent chose. "Kitting held" fits."""


# --------------------------------------------------------------------------
# internals

def _stations():
	"""Station instance names in process order, straight from the model."""
	return [s["instance"] for s in sorted(exchange.alarmFlood.model.STATIONS,
										  key=lambda s: s["order"])]


def _line(linePath):
	return linePath or exchange.alarmFlood.model.DEFAULT_LINE


def _nominal(rel):
	"""Nominal operating value for a station-relative tag, from the model's sim."""
	spec = exchange.alarmFlood.model.tagSpec(rel)
	if not spec:
		return None
	base = (spec.get("sim") or {}).get("base")
	if isinstance(base, bool):
		return None
	return float(base) if isinstance(base, (int, long, float)) else None


def _readMap(rels, linePath):
	"""Read station-relative paths, returning ``{rel: value-or-None}``.

	One readBlocking for the whole widget. Bad quality and non-numerics come
	back as None rather than 0 -- a stopped station and a station reading zero
	are the same number but not the same fact, and only the caller knows which
	of those matters.
	"""
	rels = [r for r in rels if r]
	if not rels:
		return {}
	line = _line(linePath)
	paths = [exchange.alarmFlood.model.fullPath(line, r) for r in rels]
	qvs = system.tag.readBlocking(paths)
	out = {}
	for i in range(len(rels)):
		qv = qvs[i]
		v = qv.value
		if not qv.quality.isGood():
			out[rels[i]] = None
		elif isinstance(v, bool):
			out[rels[i]] = v
		elif isinstance(v, (int, long, float)):
			out[rels[i]] = float(v)
		else:
			out[rels[i]] = v if isinstance(v, basestring) else None
	return out


def _pct(value, nominal):
	"""Value as a percentage of nominal, clamped to 0-150 and rounded.

	The cap matters: ``MixerMotorCurrent`` genuinely runs above nominal when the
	mixer works against a held batch, and an uncapped percentage there flattens
	every other bar in the chart.
	"""
	if value is None or not nominal:
		return 0.0
	return round(max(0.0, min(150.0, 100.0 * value / nominal)), 1)


def _label(tagPath):
	name = unicode(tagPath).split("/")[-1]
	return name.split("]")[-1] if "]" in name else name


def _qualify(tagPath):
	return tagPath if unicode(tagPath).startswith("[") else "[default]" + tagPath


def _ratePct(linePath):
	"""``{station: % of nominal throughput}`` for all five stations."""
	names = _stations()
	rels = [n + "/" + _RATE[n] for n in names if _RATE.get(n)]
	vals = _readMap(rels, linePath)

	pct = {}
	for n in names:
		tag = _RATE.get(n)
		if tag:
			rel = n + "/" + tag
			pct[n] = _pct(vals.get(rel), _nominal(rel))
		else:
			pct[n] = None

	# Fill a rate-less station from its neighbours -- see _RATE.
	for i, n in enumerate(names):
		if pct[n] is None:
			sides = []
			if i > 0 and pct.get(names[i - 1]) is not None:
				sides.append(pct[names[i - 1]])
			if i + 1 < len(names) and pct.get(names[i + 1]) is not None:
				sides.append(pct[names[i + 1]])
			pct[n] = round(min(sides), 1) if sides else 0.0
	return pct


def _bufferPct(linePath):
	"""``{station: buffer level %}``. These tags are already %, so no scaling."""
	names = _stations()
	rels = [n + "/" + _BUFFER[n] for n in names if _BUFFER.get(n)]
	vals = _readMap(rels, linePath)
	out = {}
	for n in names:
		tag = _BUFFER.get(n)
		v = vals.get(n + "/" + tag) if tag else None
		out[n] = round(v, 1) if v is not None else 0.0
	return out


def _statusMap(linePath):
	"""``{station: Status string}`` -- 'Running', 'Fault', 'Stopped', ..."""
	names = _stations()
	vals = _readMap([n + "/Status" for n in names], linePath)
	out = {}
	for n in names:
		v = vals.get(n + "/Status")
		out[n] = unicode(v) if isinstance(v, basestring) else u"Unknown"
	return out


def _activeAlarmsByStation(linePath):
	"""``{station: active alarm count}`` for one line.

	Counted off the live alarm status rather than the journal, because this
	drives node sizing and colour and needs to match what the alarm table on
	screen is showing at that instant.
	"""
	line = _line(linePath)
	counts = {}
	for n in _stations():
		counts[n] = 0
	try:
		results = system.alarm.queryStatus(
			path=["*" + line + "*"], state=["ActiveUnacked", "ActiveAcked"])
	except:
		# Bare except so a Java fault in the alarm system is caught too; the
		# widget degrades to zero counts rather than a broken binding.
		logger.warn("Active alarm query failed for %s: %s" % (line, sys.exc_info()[1]))
		return counts
	for evt in results:
		src = unicode(evt.getSource())
		for n in counts:
			if "/" + n + "/" in src or src.endswith("/" + n):
				counts[n] += 1
				break
	return counts


# --------------------------------------------------------------------------
# generic widgets

def tagsToChartData(tagPaths):
	"""Read a bounded list of tag paths and shape them for a pie/bar chart.

	Args:
		tagPaths (list or str): Tag paths, or a single comma-separated string.

	Returns:
		list[dict]: ``[{"label": <tag name>, "value": <numeric value or 0>}, ...]``
	"""
	if tagPaths is None:
		return []
	if isinstance(tagPaths, basestring):
		paths = [p.strip() for p in tagPaths.split(",") if p.strip()]
	else:
		paths = [unicode(p).strip() for p in tagPaths if unicode(p).strip()]

	paths = paths[:MAX_TAGS]
	if not paths:
		return []

	qvs = system.tag.readBlocking(paths)
	out = []
	for i in range(len(paths)):
		qv = qvs[i]
		value = qv.value if qv.quality.isGood() and isinstance(qv.value, (int, long, float)) else 0
		out.append({"label": _label(paths[i]), "value": value})
	return out


def ringValue(tagPath, engHigh=None):
	"""``ia.canvas-charts.ring`` -- one tag as a 0-100 dial.

	Args:
		tagPath (str): Full or provider-relative tag path.
		engHigh (float): Full-scale value. Defaults to 100, which is already
			correct for every ``%`` tag in the model.

	Returns:
		dict: ``{"value": <0-100>}``
	"""
	if not tagPath:
		return {"value": 0}
	qv = system.tag.readBlocking([_qualify(tagPath)])[0]
	if not qv.quality.isGood() or not isinstance(qv.value, (int, long, float)):
		return {"value": 0}
	full = float(engHigh) if engHigh else 100.0
	if not full:
		return {"value": 0}
	return {"value": round(max(0.0, min(100.0, 100.0 * float(qv.value) / full)), 1)}


def sparkValues(tagPath, minutesBack=15, points=60):
	"""``ia.canvas-charts.sparkline`` / ``.sparkline-bar`` -- a bare value series.

	Caps the sample count so the component is not handed nine hundred 1 Hz rows
	to draw into eighty pixels.

	The sparklines take **a flat list of numbers**, not a list of row objects --
	unlike every other chart in the family. A list of ``{"value": n}`` dicts is
	accepted without complaint and draws nothing at all.

	Returns:
		list[float]
	"""
	if not tagPath:
		return []
	end = system.date.now()
	start = system.date.addMinutes(end, -abs(int(minutesBack or 15)))
	ds = system.tag.queryTagHistory(paths=[_qualify(tagPath)], startDate=start,
									endDate=end, returnSize=int(points or 60),
									returnFormat="Wide")
	out = []
	for r in range(ds.getRowCount()):
		v = ds.getValueAt(r, 1)
		if isinstance(v, (int, long, float)) and not isinstance(v, bool):
			out.append(round(float(v), 3))
	return out


def historySeries(tagPaths, minutesBack=30, points=180):
	"""``ia.canvas-charts.area`` / ``.line`` -- multi-tag trend.

	Returns:
		dict: ``{"data": [{"t": <label>, "<tag>": <v>, ...}], "series": [...]}``
			ready to splat onto ``props.data`` and ``props.series``.
	"""
	if isinstance(tagPaths, basestring):
		paths = [p.strip() for p in tagPaths.split(",") if p.strip()]
	else:
		paths = [unicode(p).strip() for p in (tagPaths or []) if unicode(p).strip()]
	paths = [_qualify(p) for p in paths[:MAX_TAGS]]
	if not paths:
		return {"data": [], "series": []}

	end = system.date.now()
	start = system.date.addMinutes(end, -abs(int(minutesBack or 30)))
	ds = system.tag.queryTagHistory(paths=paths, startDate=start, endDate=end,
									returnSize=int(points or 180),
									returnFormat="Wide")
	names = [ds.getColumnName(c) for c in range(ds.getColumnCount())]
	tsCol = 0
	for i, n in enumerate(names):
		if unicode(n).lower() in ("t_stamp", "timestamp"):
			tsCol = i
			break

	fields = []
	for c in range(ds.getColumnCount()):
		if c != tsCol:
			fields.append((c, _label(names[c])))

	# Two things about the x value, both of which produce the same silent
	# failure -- legend and auto-scaled y-axis render, zero points plotted:
	#   * The key must be `timestamp`. area/line carry no xAxis prop and no
	#     `category` field on their series, so the component finds x by name.
	#     ("t" was the first attempt.)
	#   * The value must be a **parseable ISO-8601 datetime**. The x axis is a
	#     time axis, so a bare "HH:mm:ss" cannot be positioned on it.
	rows = []
	for r in range(ds.getRowCount()):
		row = {"timestamp": system.date.format(ds.getValueAt(r, tsCol),
											   "yyyy-MM-dd'T'HH:mm:ss")}
		for c, name in fields:
			v = ds.getValueAt(r, c)
			row[name] = round(float(v), 3) if isinstance(v, (int, long, float)) and not isinstance(v, bool) else None
		rows.append(row)

	# `value` names the field to plot -- it is not the value itself. Radar uses
	# `valueField` for the same job; area/line/bar use `value`. They are
	# different schemas in the same component family.
	series = [{"label": name, "value": name, "visible": True}
			  for _, name in fields]
	return {"data": rows, "series": series}


# --------------------------------------------------------------------------
# line-shaped widgets -- the Alarm Flood line as a process, not as a tag list

def flowSankey(linePath=None):
	"""``ia.canvas-charts.sankey`` -- material flow down the line.

	Each station emits two links: what it passes to the next station, and what
	it is accumulating in its own buffer. During normal operation the held
	branch is a hairline and the chain runs full width; during a jam the held
	branches fatten from the downstream end backwards, which is the cascade
	made visible in a single frame.

	Sankey requires an acyclic graph, so the chain runs strictly downstream and
	every held branch terminates in its own sink node. Sharing one `HELD` node
	would merge five independent backups into one meaningless bar.

	Returns:
		dict: ``{"nodes": [{"name"}], "links": [{"source","target","value"}]}``
	"""
	names = _stations()
	rate = _ratePct(linePath)
	buf = _bufferPct(linePath)

	nodes = [{"name": n} for n in names]
	links = []
	for i, n in enumerate(names):
		held = round(buf.get(n, 0.0) * 0.5, 1)
		if i + 1 < len(names):
			passed = max(0.0, round(rate.get(names[i + 1], 0.0), 1))
			if passed > 0:
				links.append({"source": n, "target": names[i + 1], "value": passed})
		if held > 1.0:
			sink = n + " " + HELD
			nodes.append({"name": sink})
			links.append({"source": n, "target": sink, "value": held})
	return {"nodes": nodes, "links": links}


def flowChord(linePath=None):
	"""``ia.canvas-charts.chord`` -- station-to-station coupling.

	The same downstream chain as `flowSankey`, plus the returns a sankey cannot
	show: empty carriers cycling back from Packaging to Kitting, and the rework
	path from Cooking back to Forming. A chord diagram is the right shape for
	that precisely because it tolerates cycles.

	Returns:
		dict: ``{"nodes": [{"name"}], "links": [{"source","target","value"}]}``
	"""
	names = _stations()
	rate = _ratePct(linePath)

	links = []
	for i in range(len(names) - 1):
		v = max(1.0, round(rate.get(names[i + 1], 0.0), 1))
		links.append({"source": names[i], "target": names[i + 1], "value": v})

	# Carrier return and rework -- proportional to finished-goods rate, so they
	# thin out with the line rather than staying constant and dominating.
	pkg = rate.get(names[-1], 0.0)
	links.append({"source": names[-1], "target": names[0],
				  "value": max(1.0, round(pkg * 0.35, 1))})
	links.append({"source": "Cooking", "target": "Forming",
				  "value": max(1.0, round(pkg * 0.08, 1))})
	return {"nodes": [{"name": n} for n in names], "links": links}


def topologyGraph(linePath=None):
	"""``ia.canvas-charts.graph`` -- the line as equipment, sized by alarm load.

	Three categories: the five Stations, their Buffers, and the Packaging Drive
	that every Alarm Flood scenario starts at. Station nodes grow with their
	active alarm count, so the node that is actually in trouble is the one that
	reads largest -- which is the whole point of showing a topology rather than
	a table.

	Returns:
		dict: ``{"categories": [...], "data": {"nodes": [...], "links": [...]}}``
	"""
	names = _stations()
	alarms = _activeAlarmsByStation(linePath)
	buf = _bufferPct(linePath)

	nodes = []
	links = []
	for n in names:
		nodes.append({"name": n, "category": "Station",
					  "symbolSize": 30 + 8 * min(6, alarms.get(n, 0))})
		bname = n + " buffer"
		nodes.append({"name": bname, "category": "Buffer",
					  "symbolSize": 10 + round(buf.get(n, 0.0) * 0.22, 1)})
		links.append({"source": n, "target": bname})
	for i in range(len(names) - 1):
		links.append({"source": names[i], "target": names[i + 1]})

	nodes.append({"name": "Packaging Drive", "category": "Drive", "symbolSize": 34})
	links.append({"source": "Packaging Drive", "target": "Packaging"})

	return {
		"categories": [{"name": "Station"}, {"name": "Buffer"}, {"name": "Drive"}],
		"data": {"nodes": nodes, "links": links},
	}


def alarmHeatmap(linePath=None, hoursBack=12, bucketMinutes=30):
	"""``ia.canvas-charts.heatmap`` -- alarm density, station by time bucket.

	Read from the journal rather than live status, because the point is *when*
	each station lit up: a flood shows as a diagonal smear from Packaging up to
	Kitting, and normal running shows as near-empty with the odd nuisance alarm
	on a non-target line.

	Every station/bucket cell is emitted, including zeros -- the component
	renders a grid, and a sparse list leaves holes rather than cold cells.

	Returns:
		dict: ``{"data": [{"station","bucket","value"}], "xField": "bucket",
		"yField": "station"}``
	"""
	names = _stations()
	line = _line(linePath)
	end = system.date.now()
	start = system.date.addHours(end, -abs(int(hoursBack or 12)))
	step = max(1, int(bucketMinutes or 30))

	# Bucketing is done in epoch millis, not Dates. `getActiveData().getTimestamp()`
	# on a journal event returns a **long**, not a java.util.Date, so feeding it
	# to system.date.isAfter fails with "2nd arg can't be coerced to
	# java.util.Date" -- which is the kind of thing that only shows up against a
	# journal that actually has rows in it.
	startMs = system.date.toMillis(start)
	stepMs = step * 60 * 1000
	buckets = int((system.date.toMillis(end) - startMs) // stepMs) + 1

	labels = []
	for i in range(buckets):
		labels.append(system.date.format(
			system.date.fromMillis(startMs + i * stepMs), "HH:mm"))
	if not labels:
		return {"data": [], "xField": "bucket", "yField": "station"}

	grid = {}
	for n in names:
		for lb in labels:
			grid[(n, lb)] = 0

	try:
		journal = system.alarm.queryJournal(journalName=JOURNAL, startDate=start,
											endDate=end, path=["*" + line + "*"])
	except:
		# Same as above: log and render an empty heatmap rather than fail.
		logger.warn("Alarm journal query failed for %s: %s" % (line, sys.exc_info()[1]))
		journal = []

	for evt in journal:
		try:
			ts = long(evt.getActiveData().getTimestamp())
		except:
			continue
		src = unicode(evt.getSource())
		station = None
		for n in names:
			if "/" + n + "/" in src or src.endswith("/" + n):
				station = n
				break
		if station is None:
			continue
		idx = int((ts - startMs) // stepMs)
		if idx < 0 or idx >= len(labels):
			continue
		grid[(station, labels[idx])] = grid.get((station, labels[idx]), 0) + 1

	rows = []
	for n in names:
		for lb in labels:
			rows.append({"station": n, "bucket": lb, "value": grid[(n, lb)]})
	return {"data": rows, "xField": "bucket", "yField": "station"}


def stationRadar(linePath=None, stations=None):
	"""``ia.canvas-charts.radar`` -- station health across five shared axes.

	Every axis is normalised so 100 is good and 0 is bad, which is the only way
	a radar reads at a glance: a healthy station is a big even pentagon and a
	sick one visibly caves in on whichever axis is failing. That means the
	buffer axis is *headroom* (100 - level), not level.

	Args:
		stations (list): Station names to overlay. Defaults to the first and
			last, which are the two ends of the cascade.

	Returns:
		dict: ``{"data": [...], "series": [...]}``
	"""
	names = _stations()
	picked = [s for s in (stations or []) if s in names] or [names[0], names[-1]]
	picked = picked[:4]

	rate = _ratePct(linePath)
	buf = _bufferPct(linePath)
	alarms = _activeAlarmsByStation(linePath)
	status = _statusMap(linePath)

	# Axis names are one short word: they are drawn outside the pentagon, so a
	# long one is clipped by the tile rather than wrapped ("Buffer headroom"
	# lost its first six characters at 4 columns). "Headroom" rather than the
	# shorter "Buffer" because this axis is 100 - level, and a reader seeing
	# "Buffer 60" would reasonably take it for 60% full -- the opposite.
	axes = ["Throughput", "Headroom", "Alarm-free", "Running", "Stability"]
	scores = {}
	for n in picked:
		r = min(100.0, rate.get(n, 0.0))
		scores[n] = {
			"Throughput": round(r, 1),
			"Headroom": round(max(0.0, 100.0 - buf.get(n, 0.0)), 1),
			"Alarm-free": round(max(0.0, 100.0 - 20.0 * alarms.get(n, 0)), 1),
			"Running": 100.0 if status.get(n) == "Running" else 0.0,
			# Stability is deliberately derived, not measured: it is how close
			# the station is to its own nominal in both directions, so a
			# station running hot scores as poorly as one running slow.
			"Stability": round(max(0.0, 100.0 - abs(100.0 - rate.get(n, 0.0))), 1),
		}

	data = []
	for ax in axes:
		row = {"dimension": ax, "max": 100}
		for n in picked:
			row[n] = scores[n][ax]
		data.append(row)

	series = [{"label": n, "valueField": n, "color": "", "lineWidth": 2,
			   "area": {"enabled": True}} for n in picked]
	return {"data": data, "series": series}


def throughputFunnel(linePath=None):
	"""``ia.canvas-charts.funnel`` -- where throughput is being lost.

	Stations in process order with their % of nominal. A funnel is only honest
	when the series is monotonically decreasing, and a live line is not: an
	upstream station can legitimately outrun a constrained downstream one. The
	values are therefore clamped to a running minimum, and the *label* carries
	the station's true reading whenever the clamp actually hid something.

	`_HELD_BACK_PTS` is why the annotation is not simply ``actual != floorVal``.
	Every rate carries measurement noise, so on a healthy line the running
	minimum is a point or two under most stations and every single one would be
	annotated -- which is how an earlier cut labelled Cooking and Packaging
	"blocked" while the line was running perfectly normally. Only a gap wide
	enough to mean something gets called out, and it is worded as what was
	measured ("running 104%") rather than as a diagnosis.

	Returns:
		list[dict]: ``[{"name", "value", "color"}, ...]``
	"""
	names = _stations()
	rate = _ratePct(linePath)
	out = []
	floorVal = None
	for n in names:
		actual = round(rate.get(n, 0.0), 1)
		floorVal = actual if floorVal is None else min(floorVal, actual)
		if actual - floorVal > _HELD_BACK_PTS:
			label = "%s - running %.0f%%, held to %.0f%%" % (n, actual, floorVal)
		else:
			label = n
		out.append({"name": label, "value": round(floorVal, 1), "color": ""})
	return out


def stationBars(linePath=None, metric="rate"):
	"""``ia.canvas-charts.bar`` -- one metric across all five stations.

	Args:
		metric (str): ``rate`` (% of nominal), ``buffer`` (% full) or
			``alarms`` (active count).

	Returns:
		dict: ``{"data": [{"station", "value"}], "series": [...]}``
	"""
	names = _stations()
	metric = (metric or "rate").lower()
	if metric == "buffer":
		vals, label = _bufferPct(linePath), "Buffer %"
	elif metric == "alarms":
		vals, label = _activeAlarmsByStation(linePath), "Active alarms"
	else:
		vals, label = _ratePct(linePath), "% of nominal"

	# `category` and `value` name the fields on each row, not the values. See
	# the note in historySeries -- bar wants both, area wants only `value`, and
	# radar wants `valueField` instead.
	data = [{"station": n, "value": vals.get(n, 0)} for n in names]
	series = [{"category": "station", "value": "value",
			   "label": label, "visible": True}]
	return {"data": data, "series": series}


def stationPie(linePath=None):
	"""``ia.canvas-charts.pie`` -- share of accumulated material by station.

	Answers "where is the line holding product right now", which during a
	cascade is the single most diagnostic question on the screen.

	Returns:
		list[dict]: ``[{"name", "value"}, ...]``
	"""
	buf = _bufferPct(linePath)
	return [{"name": n, "value": buf.get(n, 0.0)} for n in _stations()
			if buf.get(n, 0.0) > 0]


# --------------------------------------------------------------------------

def verify(linePath=None):
	"""Check the local presentation choices still match the model, and that
	every widget function returns something shaped.

	`_RATE` and `_BUFFER` name tags by hand; a model edit that renames or drops
	one would otherwise show up as a chart that is quietly all zeros. Run this
	after `exchange.alarmFlood.control.applyModel()`.

	Returns:
		dict: ``{"ok": bool, "missing": [...], "widgets": {name: description}}``
	"""
	missing = []
	for n in _stations():
		for table, which in ((_RATE, "rate"), (_BUFFER, "buffer")):
			rel = table.get(n)
			if rel and exchange.alarmFlood.model.tagSpec(n + "/" + rel) is None:
				missing.append("%s %s -> %s/%s" % (n, which, n, rel))

	widgets = {}
	checks = [
		("flowSankey", lambda: flowSankey(linePath)),
		("flowChord", lambda: flowChord(linePath)),
		("topologyGraph", lambda: topologyGraph(linePath)),
		("alarmHeatmap", lambda: alarmHeatmap(linePath, 2, 30)),
		("stationRadar", lambda: stationRadar(linePath)),
		("throughputFunnel", lambda: throughputFunnel(linePath)),
		("stationBars", lambda: stationBars(linePath)),
		("stationPie", lambda: stationPie(linePath)),
	]
	for name, fn in checks:
		try:
			r = fn()
			if isinstance(r, dict):
				widgets[name] = "keys=%s" % sorted(r.keys())
			else:
				widgets[name] = "rows=%d" % len(r)
		except:
			e = sys.exc_info()[1]
			widgets[name] = "ERROR: %s" % e
			missing.append(name)

	return {"ok": not missing, "missing": missing, "widgets": widgets}


# --------------------------------------------------------------------------
# Public read API for the AI agent tools (exchange.aiTools.productionLine).
# Added by the tool-refactor pass so describe_production_line no longer reaches
# into the private helpers above. Keep these thin: they exist to give the
# private functions a stable public name, not to add behaviour.

def lineSnapshot(linePath=None):
	"""Read how every station on a line is running right now.

	Args:
		linePath (str): Line path such as "Site1/Area1/Line1". Defaults to
			exchange.alarmFlood.model.DEFAULT_LINE.

	Returns:
		dict: {ratePct, bufferPct, status, activeAlarms}, each keyed by station
			instance name.

		Example: {"ratePct": {"Kitting": 99.2, ...}, "status": {"Kitting": "Running", ...}}
	"""
	return {
		"ratePct": _ratePct(linePath),
		"bufferPct": _bufferPct(linePath),
		"status": _statusMap(linePath),
		"activeAlarms": _activeAlarmsByStation(linePath),
	}


def stationTagRoles():
	"""Return which tag stands for each station's rate and buffer.

	Returns:
		dict: {station: {"rate": tagName or None, "buffer": tagName or None}}.
	"""
	roles = {}
	for name in _stations():
		roles[name] = {"rate": _RATE.get(name), "buffer": _BUFFER.get(name)}
	return roles
