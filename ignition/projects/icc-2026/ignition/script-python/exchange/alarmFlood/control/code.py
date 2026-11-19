"""Builds and drives the Alarm Flood demo tag model.

The *shape* of the model -- stations, tags, normal-operating behaviour, history
settings and alarms -- is declared once in :mod:`exchange.alarmFlood.model`. This module
turns that declaration into real Ignition tags:

* :func:`setupTags` creates the UDT types under ``[default]_types_/Exchange/AlarmFlood`` and
  the five-line instance tree under ``[default]Exchange/Alarm Flood``.
* :func:`applyModel` re-applies just the UDT *types*, which is how you push a model
  change (a new tag, a retuned setpoint, different history) to all five lines
  without disturbing the instances or the detector/simulator state folders.

Live behaviour lives in :mod:`exchange.alarmFlood.sim`, which is driven by the
``AlarmFloodSim`` gateway timer. The ``simulate``/``reset`` functions here are thin
wrappers kept so existing buttons and agent tools continue to work.
"""

import sys

import exchange.alarmFlood.model as M
import exchange.alarmFlood.sim as Sim

logger = system.util.getLogger("exchange.alarmFlood.Control")

DEFAULT_LINE_PATH = M.DEFAULT_LINE
"""Default relative line path used by ``simulateFlood`` and ``resetFlood``."""

HISTORY_PROVIDER = M.HISTORY_PROVIDER
"""Tag history provider used for the alarmed process values."""


# ---------------------------------------------------------------------------
# Model -> tags
# ---------------------------------------------------------------------------

def _lineFolder(lineName):
	"""Build a line folder containing one instance of each station UDT."""
	return {
		"name": lineName,
		"tagType": "Folder",
		"tags": [
			{"name": st["instance"], "tagType": "UdtInstance",
			 "typeId": "[default]_types_/Exchange/AlarmFlood/" + st["type"]}
			for st in sorted(M.STATIONS, key=lambda s: s["order"])
		],
	}


def _ensureExchangeFolder(parentPath):
	"""Make sure the ``Exchange`` root folder exists under ``parentPath``.

	Merge on a bare folder config is a no-op when the folder is already there,
	so this never disturbs a sibling resource that shares the ``Exchange`` root
	(the Tag Import Agent's UDT types live beside ``AlarmFlood`` under
	``_types_/Exchange``). The overwrite that follows is scoped to the
	``AlarmFlood`` / ``Alarm Flood`` folder alone.

	Args:
		parentPath (str): ``[default]`` or ``[default]_types_``.
	"""
	system.tag.configure(parentPath, [{"name": "Exchange", "tagType": "Folder"}], "m")


def applyModel():
	"""Re-apply the UDT *type* definitions from :mod:`exchange.alarmFlood.model`.

	Because every process value lives on the UDT type, this single call pushes new
	tags, retuned alarm setpoints and changed history settings to all five lines at
	once. Instances, the ``Detector State`` folder and the ``Simulator``
	folder are left untouched. Idempotent.

	Returns:
		dict: Quality strings plus a count of what the model now declares.
	"""
	typeFolder = {"name": "AlarmFlood", "tagType": "Folder", "tags": M.udtTypes()}
	_ensureExchangeFolder("[default]_types_")
	result = system.tag.configure("[default]_types_/Exchange", [typeFolder], "o")
	logger.info("Applied Alarm Flood model: %d station types, %d alarms per line"
				% (len(M.STATIONS), M.alarmCount()))
	return {
		"quality": [str(q) for q in result],
		"stationTypes": len(M.STATIONS),
		"tagsPerLine": len(M.allRelPaths()),
		"alarmsPerLine": M.alarmCount(),
	}


# Kept under its original name -- older notes and buttons call this.
enableTagHistory = applyModel


def setupTags():
	"""Create or overwrite the Alarm Flood UDTs, the line tree, and simulator state.

	Existing tags at these locations are overwritten (collision policy ``"o"``), so
	this is the "build it from scratch" entry point. It does not delete the
	``Detector State`` folder.

	Returns:
		dict: Quality results from each configure call.
	"""
	typeResult = applyModel()

	lines = {}
	for linePath in M.LINES:
		site, area, line = linePath.split("/")
		lines.setdefault(site, {}).setdefault(area, []).append(line)

	siteFolders = []
	for site in sorted(lines.keys()):
		areaFolders = []
		for area in sorted(lines[site].keys()):
			areaFolders.append({
				"name": area,
				"tagType": "Folder",
				"tags": [_lineFolder(l) for l in sorted(lines[site][area])],
			})
		siteFolders.append({"name": site, "tagType": "Folder", "tags": areaFolders})

	tree = {"name": "Alarm Flood", "tagType": "Folder", "tags": siteFolders}
	_ensureExchangeFolder("[default]")
	instResult = system.tag.configure("[default]Exchange", [tree], "o")

	Sim.ensureSimTags()

	return {
		"typeQuality": typeResult["quality"],
		"instanceQuality": [str(q) for q in instResult],
		"lines": M.LINES,
		"tagsPerLine": typeResult["tagsPerLine"],
		"alarmsPerLine": typeResult["alarmsPerLine"],
	}


def verifyTags():
	"""Return a summary of the configured Alarm Flood area/line/station tree.

	Returns:
		dict: ``{areaName: {lineName: [stationNames]}}``.
	"""
	summary = {}
	areas = system.tag.browse("[default]Exchange/Alarm Flood/Site1", {}).getResults()
	for area in areas:
		areaName = str(area["name"])
		if areaName.startswith("_"):
			continue
		lines = system.tag.browse(area["fullPath"], {}).getResults()
		summary[areaName] = {}
		for line in lines:
			lineName = str(line["name"])
			stations = system.tag.browse(line["fullPath"], {}).getResults()
			summary[areaName][lineName] = sorted([str(s["name"]) for s in stations])
	return summary


def verifyModel(linePath=None):
	"""Check that every tag the model declares exists and reads Good on a line.

	Returns:
		dict: ``{"line", "ok", "good", "bad"}`` where ``bad`` lists any missing or
		bad-quality tag paths.
	"""
	line = linePath or DEFAULT_LINE_PATH
	relPaths = M.allRelPaths()
	qv = system.tag.readBlocking([M.fullPath(line, r) for r in relPaths])
	bad = []
	for i, rel in enumerate(relPaths):
		if not qv[i].quality.isGood():
			bad.append({"tag": rel, "quality": str(qv[i].quality)})
	return {"line": line, "ok": len(bad) == 0, "good": len(relPaths) - len(bad), "bad": bad}


# ---------------------------------------------------------------------------
# Simulation control (delegates to exchange.alarmFlood.sim)
# ---------------------------------------------------------------------------

def simulateFlood(linePath=None, scenario=None, holdSecs=None):
	"""Start a fault scenario that *produces* an alarm flood through process physics.

	This no longer writes alarm values directly. It hands off to
	:func:`exchange.alarmFlood.sim.startFlood`, which degrades the packaging conveyor drive
	until the belt breaks and then lets backpressure walk upstream, so every alarm
	has a cause visible in tag history.

	Args:
		linePath (str): Line to fault, e.g. ``Site1/Area1/Line1``. Defaults to the
			line currently selected in ``Simulator/TargetLine``.
		scenario (str): Scenario key. Defaults to the current selection.
		holdSecs (int): Seconds to hold the line down after the cascade before
			automatic recovery. Defaults to exchange.alarmFlood.sim.DEFAULT_HOLD_SECS (30).

	Returns:
		dict: The run parameters, including total expected duration.
	"""
	return Sim.startFlood(linePath=linePath, scenario=scenario, holdSecs=holdSecs)


def resetFlood(linePath=None):
	"""Immediately return a line to normal operating conditions.

	Skips the recovery ramp. For a realistic staged recovery use
	:func:`exchange.alarmFlood.sim.abortFlood` instead.
	"""
	return Sim.resetLine(linePath)


def simStatus():
	"""Return the simulator's current phase/stage/target as a plain dict."""
	return Sim.status()


# ---------------------------------------------------------------------------
# Alarm queries
# ---------------------------------------------------------------------------

def queryActiveAlarms(includeShelved=False, provider=None, path=None):
	"""Query currently active alarm events (acked and unacked).

	Args:
		includeShelved (bool): When True, include shelved active alarms.
		provider (str or list): Optional provider name(s) to limit the query.
		path (str or list): Optional source-path filter(s), wildcards allowed
			(e.g. ``"*Site1/Area1/Line1*"``). Without one this returns every
			active alarm on the gateway.

	Returns:
		list: Alarm event objects returned by ``system.alarm.queryStatus``.
	"""
	kwargs = {"state": ["ActiveUnacked", "ActiveAcked"], "includeShelved": includeShelved}
	if provider is not None:
		kwargs["provider"] = [provider] if isinstance(provider, basestring) else provider
	if path is not None:
		kwargs["path"] = [path] if isinstance(path, basestring) else path
	return system.alarm.queryStatus(**kwargs)


# Station key used on the mimic (see scripts/wire_alarm_flood_svg.py) -> the
# station folder name in the tag model.
_MASK_STATIONS = [
	("kit", "Kitting"),
	("mix", "Mixing"),
	("form", "Forming"),
	("cook", "Cooking"),
	("pkg", "Packaging"),
]

# The Packaging drive gets its own indicator (the ring around the sprocket), so
# these tags are reported separately as well as under "pkg".
_MASK_DRIVE_TAGS = ["MotorTorque", "MotorCurrent", "DriveVibration",
					"GearboxTemp", "ConveyorBeltStatus", "BeltSpeed"]

_MASK_HIGH_PRIORITY = 3
"""Ignition priority ordinal: 0 Diagnostic, 1 Low, 2 Medium, 3 High, 4 Critical.
At or above this flashes red on the mimic; below it flashes amber."""


def _eventPriority(evt):
	"""Priority ordinal of an alarm event, 0-4, defensively.

	AlarmEvent exposes priority through more than one accessor depending on
	version, and the value may come back as the enum or as an int, so try the
	documented routes in turn rather than assuming one. Unknown -> treat as High,
	because silently downgrading a real alarm to amber is the worse failure.
	"""
	for get in (lambda: evt.getPriority(), lambda: evt.get("priority")):
		try:
			value = get()
		except:
			continue
		if value is None:
			continue
		try:
			return int(value.ordinal())
		except:
			pass
		try:
			return int(value)
		except:
			continue
	return _MASK_HIGH_PRIORITY


def stationAlarmMask(line=None):
	"""Which parts of a line are currently in alarm, as a string for the mimic.

	Returns something like ``"|pkg:h|pdrv:h|cook:m|"`` -- one entry per part that
	has an active alarm, suffixed ``:h`` if its worst active alarm is High or
	Critical and ``:m`` otherwise. An expression binding tests membership with
	``indexOf(mask, "|pkg:h|") >= 0``, so a single ``runScript`` poll drives every
	alarm indicator on the mimic.

	A string rather than a dict because Perspective expression bindings cannot
	index into a dict comfortably, and the delimiters make membership tests exact
	-- without them "form" would also match "forming".

	This reads **real alarm state** rather than re-deriving it from tag values,
	which matters: after the belt parts, torque, current and vibration all
	*collapse* because the load is gone, so a value-threshold test says the drive
	is fine while its alarms are still standing. That is exactly the bug this
	replaced -- the ring around the sprocket used to vanish at the moment of the
	break.

	Args:
		line (str): Line path, e.g. ``Site1/Area1/Line1``. Defaults to the
			simulator's current target line.

	Returns:
		str: The mask, or ``""`` if nothing on the line is in alarm.
	"""
	if line is None:
		try:
			line = Sim.status().get("targetLine") or M.DEFAULT_LINE
		except:
			line = M.DEFAULT_LINE

	try:
		# Scoped to the line: this runs at 1 Hz per mimic/3D viewer, and an
		# unfiltered query returns every active alarm on the gateway. The
		# ``line not in source`` test below still applies, so the result is
		# identical -- the filter only stops the other lines' alarms coming back.
		events = list(queryActiveAlarms(path=["*" + line + "*"]))
	except:
		exc = sys.exc_info()[1]
		# Ignition's LoggerEx takes (message) or (message, throwable) -- the
		# stdlib `exc_info=` kwarg is not supported and raises here.
		logger.warn("stationAlarmMask: alarm query failed: %s" % exc)
		return ""

	# part key -> worst priority ordinal seen
	worst = {}

	def _note(key, priority):
		if key not in worst or priority > worst[key]:
			worst[key] = priority

	for evt in events:
		try:
			source = str(evt.getSource())
		except:
			continue
		priority = _eventPriority(evt)
		if line not in source:
			continue
		for key, station in _MASK_STATIONS:
			if "%s/%s/" % (line, station) not in source:
				continue
			_note(key, priority)
			if station == "Packaging":
				for tagName in _MASK_DRIVE_TAGS:
					if "/%s:" % tagName in source or source.endswith("/%s" % tagName):
						_note("pdrv", priority)
						break

	if not worst:
		return ""
	parts = []
	for key in sorted(worst):
		suffix = "h" if worst[key] >= _MASK_HIGH_PRIORITY else "m"
		parts.append("%s:%s" % (key, suffix))
	return "|" + "|".join(parts) + "|"


def countActiveAlarms():
	"""Return the number of currently active alarms -- a quick demo sanity check."""
	return len(list(queryActiveAlarms()))
