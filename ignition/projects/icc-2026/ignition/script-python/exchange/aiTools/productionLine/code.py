"""Production-line snapshot for the Dashboard Agent's describe_production_line tool.

Exists so the agent can compose a dashboard from the line's actual state rather
than from tag-path guesswork. browse_tags can enumerate the tree, but it returns
a flat list with no notion of process order, of which tag on a station stands
for throughput, or of whether the line is currently in a fault -- and all three
of those change which widgets are worth placing.

Everything here is derived from exchange.alarmFlood.model and the live tags via
exchange.dashboard.widgets' public read API, so it cannot disagree with what the widgets
will draw.
"""
import sys

import exchange.alarmFlood.model
import exchange.dashboard.widgets

logger = system.util.getLogger("exchange.aiTools.ProductionLine")

_SIM_KEYS = ("phase", "stageName", "targetLine", "scenarioLabel", "enabled")

_NOTES = [
	"rate_pct_of_nominal is each station's throughput as a percentage of "
	"its own nominal, because the five stations measure throughput in "
	"four different units. Mixing has no rate tag and is reported as the "
	"lower of its neighbours.",
	"Every analog tag is historised at 1 Hz, so any trend widget has "
	"per-second data available.",
]

_FAULT_HINT = ("If every tag is Bad quality the gateway's tag layer is "
	"faulted -- check exchange.alarmFlood.sim.status() for "
	"simTagsReady, and restart the gateway if it is False. "
	"No dashboard will show data until that is fixed.")


def _simulatorState():
	"""Return the simulator phase fields, or {} if the simulator cannot be read."""
	sim = {}
	try:
		# Imported here so a broken simulator module degrades this block to {}
		# instead of failing the whole snapshot
		import exchange.alarmFlood.sim
		status = exchange.alarmFlood.sim.status()
		for key in _SIM_KEYS:
			if key in status:
				sim[key] = status[key]
	except:
		logger.warn("exchange.alarmFlood.sim.status() failed: %s" % sys.exc_info()[1])
	return sim


def _stationTags(linePath, station):
	"""Describe every tag the model declares on one station."""
	tags = []
	for tag in station["tags"]:
		tags.append({
			"name": tag["name"],
			"kind": tag["kind"],
			"unit": tag.get("engUnit"),
			"range": ([tag.get("engLow"), tag.get("engHigh")]
				if tag["kind"] == "analog" else None),
			"path": exchange.alarmFlood.model.fullPath(linePath, station["instance"] + "/" + tag["name"]),
			"alarms": [alarm.get("label") for alarm in (tag.get("alarms") or [])],
		})
	return tags


def describeLine(linePath=None):
	"""Snapshot of the Alarm Flood line: stations, what each measures, how it runs now.

	Args:
		linePath (str): Line path such as "Site1/Area1/Line1". Defaults to
			exchange.alarmFlood.model.DEFAULT_LINE.

	Returns:
		dict: The describe_production_line payload, or {error, hint} when the
			live tags cannot be read.
	"""
	line = linePath or exchange.alarmFlood.model.DEFAULT_LINE
	try:
		snapshot = exchange.dashboard.widgets.lineSnapshot(line)
	except:
		error = sys.exc_info()[1]
		logger.warn("Could not read line %s: %s" % (line, error))
		return {"error": "could not read the line: %s" % str(error), "hint": _FAULT_HINT}

	roles = exchange.dashboard.widgets.stationTagRoles()
	rate = snapshot["ratePct"]
	buf = snapshot["bufferPct"]
	status = snapshot["status"]
	alarms = snapshot["activeAlarms"]

	stations = []
	for station in sorted(exchange.alarmFlood.model.STATIONS, key=lambda s: s["order"]):
		name = station["instance"]
		stationRoles = roles.get(name) or {}
		stations.append({
			"station": name,
			"order": station["order"],
			"rate_tag": stationRoles.get("rate"),
			"buffer_tag": stationRoles.get("buffer"),
			"now": {
				"rate_pct_of_nominal": rate.get(name),
				"buffer_pct": buf.get(name),
				"status": status.get(name),
				"active_alarms": alarms.get(name),
			},
			"tags": _stationTags(line, station),
		})

	total = sum(alarms.values())
	return {
		"line_path": line,
		"available_lines": exchange.alarmFlood.model.LINES,
		"process_order": [s["station"] for s in stations],
		"simulator": _simulatorState(),
		"active_alarm_total": total,
		"reading": ("The line is running normally." if total == 0 else
			"There are %d active alarms -- the line is in a fault or "
			"recovering from one." % total),
		"notes": _NOTES,
		"stations": stations,
	}
