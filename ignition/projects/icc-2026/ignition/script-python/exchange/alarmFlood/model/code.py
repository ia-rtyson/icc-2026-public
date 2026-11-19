"""Single source of truth for the Alarm Flood demo process model.

Every station, every tag, its normal-operating behaviour, its history settings and
its alarms are declared here as plain data. Two consumers read this module:

* :mod:`exchange.alarmFlood.control` -- turns the declarations into UDT type definitions via
  ``system.tag.configure``.
* :mod:`exchange.alarmFlood.sim` -- reads the ``sim`` block of each tag to drive continuous
  realistic variation, and the fault scenarios to drive an alarm flood.

Keeping both off one declaration means a tag can never exist in the simulator but
not in the UDT (or carry a different baseline in each).

Tag spec keys
-------------
``name``        Tag name inside the station UDT.
``kind``        ``analog`` | ``bool`` | ``status``.
``engUnit``     Engineering unit (analog only).
``engLow`` / ``engHigh``
                Display range, used by Perspective gauges.
``sim``         Normal-operation model -- see below.
``history``     ``{"rate": <int>, "units": "SEC"}`` or ``None`` for no history.
``alarms``      List of alarm declarations (Ignition alarm property dicts).

``sim`` block (analog)
----------------------
``shape``   ``sine`` (default) or ``sawtooth``.
``base``    Centre value in normal operation.
``amp``     Amplitude of the slow process swing (sine).
``period``  Period of that swing, in seconds.
``noise``   Std-dev of the per-sample measurement noise.
``dp``      Decimal places to round to (instrument resolution).
``min`` / ``max``
            Hard clamp -- the value can never leave this range.
``cycle`` / ``peak`` / ``floor``
            Sawtooth only: batch cycle length in seconds, and the value at the
            top/bottom of the ramp.
"""

HISTORY_PROVIDER = "postgres-historian"
"""Tag history provider for every historised tag in the demo."""

LINES = [
	"Site1/Area1/Line1",
	"Site1/Area1/Line2",
	"Site1/Area2/Line3",
	"Site1/Area2/Line4",
	"Site1/Area2/Line5",
]
"""Every line in the demo tag model, in browse order."""

DEFAULT_LINE = LINES[0]
"""Line used when no target is supplied to a scenario."""

_H1 = {"rate": 1, "units": "SEC"}
"""1-second periodic history -- every historised process value in the demo.

Matches the simulator's 1 Hz tick, and it has to. There used to be a second,
5-second rate for the upstream stations on the reasoning that only the Packaging
drive moved fast enough to need 1 Hz. That stopped being true when the cascade was
compressed to ``exchange.alarmFlood.sim.CASCADE_SECS`` = 18 s: the individual backpressure
ramps are now 2-4 s each, so a 5 s sample rate captured roughly one point per ramp
and the upstream evidence -- buffers filling in sequence, which is how the agent
proves the propagation order -- effectively vanished from the historian. Deadband
stays off throughout; the noise is part of the signal here."""


def _analog(name, engUnit, engLow, engHigh, sim, history, alarms=None):
	return {
		"name": name,
		"kind": "analog",
		"engUnit": engUnit,
		"engLow": engLow,
		"engHigh": engHigh,
		"sim": sim,
		"history": history,
		"alarms": alarms or [],
	}


def _bool(name, alarms=None):
	return {"name": name, "kind": "bool", "sim": {"base": False}, "history": {"rate": 0, "units": "SEC"},
			"alarms": alarms or []}


def _status(name="Status"):
	return {"name": name, "kind": "status", "sim": {"base": "Running"},
			"history": {"rate": 0, "units": "SEC"}, "alarms": []}


def _sine(base, amp, period, noise, dp, lo, hi):
	return {"shape": "sine", "base": base, "amp": amp, "period": period,
			"noise": noise, "dp": dp, "min": lo, "max": hi}


def _sawtooth(cycle, floorVal, peak, noise, dp, lo, hi):
	return {"shape": "sawtooth", "cycle": cycle, "floor": floorVal, "peak": peak,
			"base": (floorVal + peak) / 2.0, "noise": noise, "dp": dp, "min": lo, "max": hi}


# Deadband alone does not stop chatter on a noisy signal that is *ramping* through a
# setpoint: the value crosses back and forth across the deadband band on successive
# samples, so the alarm logs an active/clear pair every few seconds and the stored
# sequence of events fills up with duplicates. The off delay is what fixes it -- the
# alarm will not clear until the value has stayed back below the setpoint for that
# long, so one physical excursion produces exactly one journal entry.
_OFF_DELAY_SECS = 20.0

_DRIVE_ON_DELAY = 0.0
"""On-delay for the Packaging drive alarms.

Everything else gets a 2 s on-delay to reject noise spikes. The drive alarms cannot:
the whole bind-to-break ramp can be 10 seconds, so a 2 s on-delay would swallow the
precursor sequence that is the entire point of the demo. They are safe without it --
the off delay above still prevents chatter, and normal-operation torque peaks near
56 % against a 70 % setpoint, so noise cannot reach it. This also mirrors real
practice: drive protection alarms are fast-acting, tank levels are not."""


def _hi(label, setpoint, priority, deadband, onDelay=2.0, offDelay=_OFF_DELAY_SECS):
	"""An AboveValue alarm."""
	return {"name": label, "label": label, "displayPath": "", "mode": "AboveValue",
			"setpointA": setpoint, "priority": priority, "enabled": True,
			"deadband": deadband, "timeOnDelaySeconds": onDelay,
			"timeOffDelaySeconds": offDelay}


def _lo(label, setpoint, priority, deadband, onDelay=2.0, offDelay=_OFF_DELAY_SECS):
	"""A BelowValue alarm."""
	return {"name": label, "label": label, "displayPath": "", "mode": "BelowValue",
			"setpointA": setpoint, "priority": priority, "enabled": True,
			"deadband": deadband, "timeOnDelaySeconds": onDelay,
			"timeOffDelaySeconds": offDelay}


def _on(label, priority):
	"""A discrete alarm that is active while the boolean tag is True.

	``mode`` must be ``"Equal"`` with ``setpointA`` True -- ``"Boolean"`` and
	``"Equality"`` are silently accepted by ``system.tag.configure`` and produce an
	alarm that is permanently active.
	"""
	return {"name": label, "label": label, "displayPath": "", "mode": "Equal",
			"setpointA": True, "priority": priority, "enabled": True}


# ---------------------------------------------------------------------------
# Stations, ordered upstream -> downstream along the line
# ---------------------------------------------------------------------------

STATIONS = [
	{
		"instance": "Kitting",
		"type": "KittingStation",
		"order": 0,
		"tags": [
			_status(),
			_analog("BinLevel", "%", 0.0, 100.0,
					_sine(40.0, 7.0, 190.0, 0.40, 1, 2.0, 100.0), _H1,
					[_hi("Kitting Bin Level High", 90.0, "High", 2.0)]),
			_analog("ConveyorSpeed", "ft/min", 0.0, 30.0,
					_sine(18.0, 0.9, 95.0, 0.12, 2, 0.0, 30.0), _H1,
					[_lo("Kitting Conveyor Speed Low", 4.0, "Medium", 0.5)]),
			_analog("PickRate", "picks/min", 0.0, 90.0,
					_sine(62.0, 3.5, 130.0, 0.70, 1, 0.0, 90.0), _H1,
					[_lo("Kitting Pick Rate Low", 30.0, "Medium", 2.0)]),
			_bool("ComponentShortage", [_on("Kitting Component Shortage", "Low")]),
		],
	},
	{
		"instance": "Mixing",
		"type": "MixingStation",
		"order": 1,
		"tags": [
			_status(),
			_analog("TankLevel", "%", 0.0, 100.0,
					_sine(50.0, 6.0, 210.0, 0.40, 1, 5.0, 100.0), _H1,
					[_hi("Mixing Tank Level High", 92.0, "High", 2.0)]),
			_analog("MixTimeElapsed", "min", 0.0, 60.0,
					_sawtooth(240.0, 0.5, 18.0, 0.05, 2, 0.0, 60.0), _H1,
					[_hi("Mixing Time Exceeded", 25.0, "Medium", 1.0)]),
			_analog("MixerMotorCurrent", "A", 0.0, 60.0,
					_sine(34.0, 1.8, 85.0, 0.30, 2, 0.0, 60.0), _H1,
					[_hi("Mixer Motor Current High", 48.0, "High", 2.0)]),
			_analog("SlurryTemp", "F", 40.0, 140.0,
					_sine(96.0, 1.6, 260.0, 0.20, 1, 40.0, 140.0), _H1,
					[_hi("Mixing Slurry Temperature High", 115.0, "Medium", 2.0),
					 _lo("Mixing Slurry Temperature Low", 80.0, "Low", 2.0)]),
			_bool("MotorOverload", [_on("Mixer Motor Overload", "Medium")]),
		],
	},
	{
		"instance": "Forming",
		"type": "FormingStation",
		"order": 2,
		"tags": [
			_status(),
			_analog("BufferLevel", "%", 0.0, 100.0,
					_sine(45.0, 7.0, 175.0, 0.40, 1, 2.0, 100.0), _H1,
					[_hi("Forming Buffer Level High", 90.0, "High", 2.0)]),
			_analog("FormerPressure", "psi", 0.0, 250.0,
					_sine(120.0, 7.0, 70.0, 0.90, 1, 0.0, 250.0), _H1,
					[_hi("Former Pressure High", 180.0, "Medium", 5.0)]),
			_analog("FormerCycleRate", "cyc/min", 0.0, 80.0,
					_sine(58.0, 2.2, 110.0, 0.40, 1, 0.0, 80.0), _H1,
					[_lo("Former Cycle Rate Low", 25.0, "Medium", 2.0)]),
			_analog("DieTemp", "F", 60.0, 400.0,
					_sine(265.0, 4.5, 240.0, 0.50, 1, 60.0, 400.0), _H1,
					[_hi("Former Die Temperature High", 320.0, "Medium", 3.0)]),
			_bool("ConveyorJam", [_on("Forming Conveyor Jam", "High")]),
		],
	},
	{
		"instance": "Cooking",
		"type": "CookingStation",
		"order": 3,
		"tags": [
			_status(),
			_analog("CookTimeElapsed", "min", 0.0, 60.0,
					_sine(12.0, 0.7, 150.0, 0.08, 2, 0.0, 80.0), _H1,
					[_hi("Cook Time Exceeded - Overcook Risk", 35.0, "Critical", 1.0)]),
			_analog("OvenTemperature", "F", 60.0, 500.0,
					_sine(350.0, 4.5, 120.0, 0.60, 1, 60.0, 500.0), _H1,
					[_hi("Oven Temperature High", 420.0, "Critical", 4.0),
					 _lo("Oven Temperature Low", 300.0, "Medium", 4.0, 10.0)]),
			_analog("OvenBeltSpeed", "ft/min", 0.0, 25.0,
					_sine(14.0, 0.5, 100.0, 0.08, 2, 0.0, 25.0), _H1,
					[_lo("Oven Belt Speed Low", 5.0, "High", 0.5)]),
			_analog("BurnerOutput", "%", 0.0, 100.0,
					_sine(62.0, 6.0, 90.0, 0.80, 1, 0.0, 100.0), _H1,
					[_hi("Oven Burner Output High", 95.0, "Medium", 2.0)]),
			_analog("ExitBufferLevel", "%", 0.0, 100.0,
					_sine(40.0, 7.0, 200.0, 0.40, 1, 2.0, 100.0), _H1,
					[_hi("Cooking Exit Buffer Level High", 90.0, "High", 2.0)]),
		],
	},
	{
		"instance": "Packaging",
		"type": "PackagingStation",
		"order": 4,
		"tags": [
			_status(),
			_analog("InfeedBufferLevel", "%", 0.0, 100.0,
					_sine(35.0, 7.0, 165.0, 0.40, 1, 2.0, 100.0), _H1,
					[_hi("Packaging Infeed Buffer Level High", 90.0, "High", 2.0, _DRIVE_ON_DELAY)]),
			_analog("PackagesPerMinute", "pkg/min", 0.0, 80.0,
					_sine(42.0, 2.5, 100.0, 0.50, 1, 0.0, 80.0), _H1,
					[_lo("Packaging Throughput Low", 5.0, "Medium", 2.0, _DRIVE_ON_DELAY)]),
			_analog("MotorTorque", "%", 0.0, 120.0,
					_sine(52.0, 3.0, 75.0, 0.50, 1, 0.0, 120.0), _H1,
					[_hi("Packaging Drive Torque Elevated", 70.0, "Medium", 4.0, _DRIVE_ON_DELAY),
					 _hi("Packaging Drive Torque High", 85.0, "High", 4.0, _DRIVE_ON_DELAY)]),
			_analog("MotorCurrent", "A", 0.0, 60.0,
					_sine(22.0, 1.2, 65.0, 0.25, 2, 0.0, 60.0), _H1,
					[_hi("Packaging Drive Current High", 38.0, "High", 2.0, _DRIVE_ON_DELAY)]),
			_analog("DriveVibration", "mm/s", 0.0, 20.0,
					_sine(2.4, 0.35, 55.0, 0.12, 2, 0.0, 20.0), _H1,
					[_hi("Packaging Drive Vibration Elevated", 4.5, "Medium", 0.7, _DRIVE_ON_DELAY),
					 _hi("Packaging Drive Vibration High", 7.1, "High", 0.7, _DRIVE_ON_DELAY)]),
			_analog("GearboxTemp", "F", 60.0, 260.0,
					_sine(142.0, 3.5, 230.0, 0.40, 1, 60.0, 260.0), _H1,
					[_hi("Packaging Gearbox Temperature High", 190.0, "High", 3.0, _DRIVE_ON_DELAY)]),
			_analog("BeltSpeed", "ft/min", 0.0, 130.0,
					_sine(95.0, 2.2, 85.0, 0.35, 2, 0.0, 130.0), _H1,
					[_lo("Packaging Belt Speed Low", 60.0, "Medium", 3.0, _DRIVE_ON_DELAY)]),
			_bool("ConveyorBeltStatus", [_on("Packaging Conveyor Belt Break", "Critical")]),
		],
	},
]

STATION_ORDER = [s["instance"] for s in sorted(STATIONS, key=lambda s: s["order"])]
"""Station instance names from most upstream to most downstream."""


def station(instance):
	"""Return the station declaration for an instance name, or None."""
	for s in STATIONS:
		if s["instance"] == instance:
			return s
	return None


def tagSpec(relPath):
	"""Look up a tag declaration by station-relative path, e.g. ``Packaging/MotorTorque``.

	Args:
		relPath (str): ``<StationInstance>/<TagName>``.

	Returns:
		dict or None: The tag declaration.
	"""
	parts = str(relPath).split("/")
	if len(parts) != 2:
		return None
	st = station(parts[0])
	if st is None:
		return None
	for t in st["tags"]:
		if t["name"] == parts[1]:
			return t
	return None


def allRelPaths(kinds=None):
	"""Every station-relative tag path in the model.

	Args:
		kinds (list): Optional filter on tag ``kind`` values.

	Returns:
		list: Paths like ``Packaging/MotorTorque``.
	"""
	out = []
	for st in sorted(STATIONS, key=lambda s: s["order"]):
		for t in st["tags"]:
			if kinds is None or t["kind"] in kinds:
				out.append(st["instance"] + "/" + t["name"])
	return out


def fullPath(linePath, relPath):
	"""Build a provider-qualified tag path from a line path and a relative path."""
	return "[default]Exchange/Alarm Flood/" + linePath + "/" + relPath


# ---------------------------------------------------------------------------
# UDT construction
# ---------------------------------------------------------------------------

def _historyProps(history):
	"""Translate a spec ``history`` block into Ignition tag history properties.

	A ``rate`` of 0 means "store every change" (booleans and status strings);
	anything else is periodic sampling at that rate.
	"""
	if not history:
		return {"historyEnabled": False}
	props = {
		"historyEnabled": True,
		"historyProvider": HISTORY_PROVIDER,
	}
	if int(history.get("rate", 0)) <= 0:
		props["sampleMode"] = "OnChange"
		props["historicalDeadbandMode"] = "Off"
	else:
		props["sampleMode"] = "Periodic"
		props["historySampleRate"] = int(history["rate"])
		props["historySampleRateUnits"] = history.get("units", "SEC")
		props["historicalDeadbandMode"] = "Off"
	return props


def udtTagDef(spec):
	"""Convert one tag declaration into a ``system.tag.configure`` tag dict."""
	if spec["kind"] == "analog":
		cfg = {
			"name": spec["name"],
			"tagType": "AtomicTag",
			"valueSource": "memory",
			"dataType": "Float4",
			"value": float(spec["sim"]["base"]),
			"engUnit": spec["engUnit"],
			"engLow": spec["engLow"],
			"engHigh": spec["engHigh"],
		}
	elif spec["kind"] == "bool":
		cfg = {
			"name": spec["name"],
			"tagType": "AtomicTag",
			"valueSource": "memory",
			"dataType": "Boolean",
			"value": bool(spec["sim"]["base"]),
		}
	else:
		cfg = {
			"name": spec["name"],
			"tagType": "AtomicTag",
			"valueSource": "memory",
			"dataType": "String",
			"value": spec["sim"]["base"],
		}
	cfg.update(_historyProps(spec.get("history")))
	if spec.get("alarms"):
		# Copy so a caller mutating the returned config cannot corrupt the model.
		cfg["alarms"] = [dict(a) for a in spec["alarms"]]
	return cfg


def udtTypes():
	"""Build every station UDT type definition declared in :data:`STATIONS`."""
	types = []
	for st in sorted(STATIONS, key=lambda s: s["order"]):
		types.append({
			"name": st["type"],
			"tagType": "UdtType",
			"tags": [udtTagDef(t) for t in st["tags"]],
		})
	return types


def alarmCount():
	"""Total number of alarms declared per line -- a sanity check for the demo."""
	n = 0
	for st in STATIONS:
		for t in st["tags"]:
			n += len(t.get("alarms", []))
	return n
