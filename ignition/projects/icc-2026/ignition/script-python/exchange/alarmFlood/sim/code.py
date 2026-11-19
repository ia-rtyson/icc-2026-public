"""Continuous process simulator and fault-scenario engine for the Alarm Flood demo.

Driven by the ``AlarmFloodSim`` gateway timer at 1 Hz. Two responsibilities:

**1. Normal operation.** Every tag on every line is continuously re-computed from
the ``sim`` model declared in :mod:`exchange.alarmFlood.model` -- a slow process swing plus
measurement noise, clamped to instrument range and rounded to instrument
resolution. Nothing is ever pinned at a constant, so trends look live and the
historian collects a plausible baseline the AI can compare against.

**2. Fault scenarios.** Pressing *Simulate Alarm Flood* calls :func:`startFlood`,
which does **not** write any alarm directly. It moves the simulator into a phase
sequence and lets the physics produce the alarms:

    NORMAL -> DEGRADING -> FAULT -> CASCADE -> HOLD -> RECOVERY -> NORMAL

For the ``PackagingConveyorJam`` scenario that reads as: the packaging conveyor
drive starts to bind, so torque / current / vibration / gearbox temperature climb
over ``Simulator/DegradeSecs`` seconds (10 by default -- tripping precursor alarms on the
way up), the belt finally parts under load (Critical), and the line backs up
station by station from
Packaging all the way upstream to Kitting -- each buffer crossing its own setpoint
as it fills. The flood is therefore *emergent*: every alarm has a physical cause
that is visible in tag history, which is exactly what the Alarm Flood Agent is
asked to reconstruct.

After the cascade the line is held down for ``Simulator/HoldSecs`` (default 60 s, so
the detector has time to close out and store the event) and then recovers
downstream-to-upstream back to normal operation.

All state lives in memory tags under ``[default]Exchange/Alarm Flood/Simulator`` so the phase
survives script reloads and can be bound straight into Perspective.
"""

import sys
import math
import random

import exchange.alarmFlood.model as M

logger = system.util.getLogger("exchange.alarmFlood.Sim")

SIM_BASE = "[default]Exchange/Alarm Flood/Simulator"
"""Folder holding the simulator's control and status tags."""

NONTARGET_REFRESH_TICKS = 5
"""Lines that are not the scenario target are refreshed every Nth tick -- they are
background scenery, so there is no reason to spend 130 tag writes a second on them."""

DEFAULT_HOLD_SECS = 30
"""How long the line stays down after the cascade before recovery begins.

This is the belt-replacement window -- the maintenance response, not a process
time -- so it is set for stage pacing rather than realism: 30 s of a visibly dead
line is long enough to read the alarm summary out loud and short enough that the
audience does not start waiting."""

NUISANCE_ODDS = 4000
"""1-in-N chance per line per tick of an unrelated nuisance alarm during NORMAL.
Deliberately noise for the AI to discard -- it is not part of any cascade."""

NUISANCE_SECS = 45
"""How long a nuisance alarm stays active."""

_LAST = {}
"""path -> last written value. Booleans and strings are only written when they
change, so ``OnChange`` history stays meaningful."""

def _simGlobals():
	"""Return this module's dictionary in the gateway globals.

	State that must outlive a script reload lives here instead of at module
	level. A project scan reloads this module; a module-level dict is then
	rebuilt empty, which for :data:`_SNAPSHOT` means a scan during RECOVERY
	makes every recovery ramp start from the assumed normal value instead of
	where the line really was, and for :data:`_NUISANCE` means an active
	nuisance alarm is never cleared. Only plain values are stored, so nothing
	here holds a reference into a stale copy of the module.

	Returns:
		dict: The ``icc2026`` / ``alarmFloodSim`` namespace, created on first use.
		If the globals cannot be reached, a module-level dict -- the old
		behaviour -- so the simulator still loads.
	"""
	try:
		return system.util.getGlobals().setdefault("icc2026", {}).setdefault("alarmFloodSim", {})
	except:
		# Bare except: never let state plumbing stop the 1 Hz simulator loading
		logger.warn("Gateway globals unavailable (%s); simulator state will not survive "
					"a project scan." % str(sys.exc_info()[1]))
		return _LOCAL_STATE


_LOCAL_STATE = {}


_SNAPSHOT = _simGlobals().setdefault("snapshot", {})
"""line -> {relPath: value} captured when RECOVERY begins, so recovery ramps start
from wherever the process actually was rather than from an assumed value.
Held in the gateway globals so it survives a project scan -- see :func:`_simGlobals`."""

_NUISANCE = _simGlobals().setdefault("nuisance", {})
"""full tag path -> epoch second at which the nuisance alarm should clear.
Held in the gateway globals for the same reason as :data:`_SNAPSHOT`."""


# ---------------------------------------------------------------------------
# Scenario definition
# ---------------------------------------------------------------------------

DEGRADE_SECS = 10
"""Default seconds from "drive starts to bind" to "belt parts".

Short on purpose -- the demo needs the jam to build and snap while the audience is
still watching. Every degrade curve is expressed in *normalised progress* (0..1),
so changing this compresses or stretches the whole ramp without changing the order
in which the precursor alarms fire. Override per run via ``startFlood(degradeSecs=)``
or the ``Simulator/DegradeSecs`` tag -- stretch it to 120-180 s when you want a long,
readable torque trend rather than a fast snap.

Note the alarms on the Packaging drive tags carry a 0 s on-delay precisely so they
can still latch inside a 10 s ramp (see ``exchange.alarmFlood.model._DRIVE_ON_DELAY``).

10 s is a floor, not a preference. The precursor setpoints are crossed in the last
~15% of the ramp, and the simulator samples at 1 Hz, so a shorter ramp puts no tick
between the last threshold crossing and the belt parting. Measured over 4000 runs
of the real curves: at 10 s the chain fires Torque Elevated 100% / Vibration
Elevated 100% / Torque High 96% / Current High 89%; at 5 s that collapses to 100% /
99% / 48% / 10%. Halving this does not speed the demo up, it deletes the evidence
the agent is supposed to find. Shorten ``CASCADE_SECS`` instead."""

FAULT_SECS = 2
CASCADE_SECS = 18
"""Seconds for the backpressure to walk upstream from Packaging to Kitting.

Compressed from an original 82 s so the line reaches a full stop 30 s after the
drive first starts to bind (10 s degrade + 2 s fault + 18 s cascade). Every t0 and
duration in the cascade tables below was scaled by 18/82 and rounded, which
preserves the propagation *order* -- the thing the agent has to reconstruct -- while
making the whole backup happen fast. The upstream history rate was raised to 1 Hz
in the same change (see ``exchange.alarmFlood.model._H1``); at the old 5 s rate these ramps
are too short to leave a trend behind."""
RECOVERY_SECS = 20
"""Seconds for the staged restart once the belt has been replaced.

Compressed from an original 90 s (2026-09-10) so the whole run is 80 s rather than
150 s -- recovery used to be the longest phase by far, three times the breakdown it
was undoing. Every t0 and duration in the recovery tables below was scaled by 20/90
and rounded, which preserves the restart *order* (packaging -> cooking -> forming ->
mixing -> kitting) while making the restart no longer outlast the audience. The last
blend lands exactly on ``RECOVERY_SECS``."""

_RECOVERY_RUNNING_LEAD = 2
"""Seconds before the end of RECOVERY at which every station reads ``Running``.

Scaled with ``RECOVERY_SECS``: it must stay smaller than the gap between the last
station's ``Recovering`` t0 and the end of the phase, or Kitting would flip straight
from ``Stopped`` to ``Running`` and never show as recovering at all."""

_DEGRADE_CURVES = [
	# relPath, v0, delta, exponent, noise at p=0, extra noise at p=1
	# value = v0 + delta * progress**exponent  -- superlinear, so it creeps then runs away
	("Packaging/MotorTorque", 52.0, 42.0, 1.15, 0.50, 3.00),
	("Packaging/MotorCurrent", 22.0, 20.0, 1.40, 0.25, 1.00),
	("Packaging/DriveVibration", 2.4, 5.6, 2.20, 0.12, 0.60),
	("Packaging/BeltSpeed", 95.0, -14.0, 2.00, 0.35, 0.80),
	("Packaging/PackagesPerMinute", 42.0, -9.0, 2.00, 0.50, 0.50),
	("Packaging/InfeedBufferLevel", 35.0, 20.0, 1.50, 0.40, 0.40),
]

GEARBOX_BASE = 142.0
GEARBOX_RATE = 0.36
GEARBOX_MAX_RISE = 56.0
"""Gearbox heating during a jam, in degrees F per *second of elapsed jam*.

Deliberately not part of ``_DEGRADE_CURVES``: those are functions of normalised ramp
progress, which would have the gearbox gain 55 F in 10 seconds when the ramp is
short. A gearbox is a thermal mass -- it heats at a rate, so this is a function of
elapsed time and nothing else. The practical consequence is that the gearbox
temperature alarm only trips on a *slow* bind (roughly 130 s or more); on a 10 s snap
the belt parts long before the casing warms up, which is what would really happen."""


_DEGRADE_STAGE_FRACTIONS = [
	(0.00, "Drive load normal"),
	(0.35, "Drive torque climbing - jam building"),
	(0.72, "Drive torque high - belt near failure"),
]
"""Degrade banner stages, as a fraction of the ramp rather than absolute seconds --
so they still read correctly whether the ramp is 10 s or 180 s."""


def _degradeStages(degradeSecs):
	"""Absolute-second stage list for a given ramp length."""
	return [(int(round(f * float(degradeSecs))), label) for f, label in _DEGRADE_STAGE_FRACTIONS]

_FAULT_CONST = {
	"Packaging/ConveyorBeltStatus": True,
	"Packaging/BeltSpeed": 0.0,
	"Packaging/PackagesPerMinute": 0.0,
	"Packaging/MotorTorque": 6.0,
	"Packaging/MotorCurrent": 6.5,
	"Packaging/Status": "Fault",
}

_CASCADE_RAMPS = [
	# relPath, t0, duration, v0, v1  -- t0/duration scaled by 18/82 (see CASCADE_SECS)
	# Packaging: nothing leaves, so the infeed buffer fills first
	("Packaging/InfeedBufferLevel", 0, 5, 55.0, 99.0),
	# v0 is patched at runtime from the temperature reached during the jam.
	("Packaging/GearboxTemp", 0, 18, None, 172.0),
	("Packaging/DriveVibration", 0, 2, 3.0, 1.2),
	# Cooking cannot discharge -> oven belt stalls -> dwell time and temperature rise
	("Cooking/ExitBufferLevel", 5, 4, 42.0, 99.0),
	("Cooking/OvenBeltSpeed", 5, 3, 14.0, 1.5),
	("Cooking/CookTimeElapsed", 5, 4, 12.0, 44.0),
	("Cooking/OvenTemperature", 5, 4, 352.0, 438.0),
	("Cooking/BurnerOutput", 6, 3, 62.0, 16.0),
	# Forming pushes into a full cooking infeed -> pressure builds, cycle rate collapses
	("Forming/BufferLevel", 8, 4, 46.0, 98.0),
	("Forming/FormerPressure", 8, 3, 121.0, 205.0),
	("Forming/FormerCycleRate", 8, 3, 58.0, 10.0),
	("Forming/DieTemp", 9, 4, 266.0, 334.0),
	# Mixing has nowhere to discharge -> batch held in the tank, mixer works against it
	("Mixing/TankLevel", 12, 3, 51.0, 99.0),
	("Mixing/MixTimeElapsed", 12, 3, 14.0, 36.0),
	("Mixing/MixerMotorCurrent", 12, 3, 35.0, 53.0),
	("Mixing/SlurryTemp", 12, 4, 97.0, 120.0),
	# Kitting backs up last and the whole line comes to a stop
	("Kitting/BinLevel", 15, 3, 42.0, 97.0),
	("Kitting/ConveyorSpeed", 15, 3, 18.0, 1.5),
	("Kitting/PickRate", 15, 2, 62.0, 14.0),
]

_CASCADE_CONST = {
	"Packaging/ConveyorBeltStatus": True,
	"Packaging/BeltSpeed": 0.0,
	"Packaging/PackagesPerMinute": 0.0,
	"Packaging/MotorTorque": 5.0,
	"Packaging/MotorCurrent": 6.0,
}

_CASCADE_BOOLS = [
	("Forming/ConveyorJam", 11),
	("Mixing/MotorOverload", 14),
]

_CASCADE_STATUS = [
	("Packaging/Status", 0, "Fault"),
	("Cooking/Status", 5, "Blocked"),
	("Forming/Status", 9, "Blocked"),
	("Mixing/Status", 12, "Holding"),
	("Kitting/Status", 15, "Stopped"),
]

_CASCADE_STAGES = [
	(0, "Packaging infeed backing up"),
	(5, "Cooking exit blocked - overcook risk"),
	(8, "Forming blocked - press pressure rising"),
	(12, "Mixing batch held in tank"),
	(15, "Kitting starved - line stopped"),
]

_HOLD_CONST = {
	"Packaging/ConveyorBeltStatus": True,
	"Packaging/InfeedBufferLevel": 99.0,
	"Packaging/BeltSpeed": 0.0,
	"Packaging/PackagesPerMinute": 0.0,
	"Packaging/MotorTorque": 5.0,
	"Packaging/MotorCurrent": 6.0,
	"Packaging/DriveVibration": 1.2,
	"Packaging/Status": "Fault",
	"Cooking/ExitBufferLevel": 99.0,
	"Cooking/OvenBeltSpeed": 1.5,
	"Cooking/BurnerOutput": 16.0,
	"Cooking/Status": "Blocked",
	"Forming/BufferLevel": 98.0,
	"Forming/FormerPressure": 205.0,
	"Forming/FormerCycleRate": 10.0,
	"Forming/ConveyorJam": True,
	"Forming/Status": "Blocked",
	"Mixing/TankLevel": 99.0,
	"Mixing/MixerMotorCurrent": 53.0,
	"Mixing/SlurryTemp": 120.0,
	"Mixing/MotorOverload": True,
	"Mixing/Status": "Holding",
	"Kitting/BinLevel": 97.0,
	"Kitting/ConveyorSpeed": 1.5,
	"Kitting/PickRate": 14.0,
	"Kitting/Status": "Stopped",
}

_HOLD_RAMPS = [
	# With the line down, hot equipment cools and held product keeps cooking.
	# v0 None = start from wherever the gearbox actually is (see _gearboxPeak).
	# Durations deliberately run past DEFAULT_HOLD_SECS: these are thermal masses,
	# so a 30 s hold should only get part way through the cooldown. RECOVERY blends
	# from wherever they actually reached (_SNAPSHOT), so a truncated ramp is fine.
	("Packaging/GearboxTemp", 0, 100, None, 148.0),
	("Cooking/OvenTemperature", 0, 120, 438.0, 296.0),
	("Cooking/CookTimeElapsed", 0, 130, 44.0, 72.0),
	("Mixing/MixTimeElapsed", 0, 130, 36.0, 56.0),
	("Forming/DieTemp", 10, 110, 334.0, 250.0),
]

_HOLD_STAGES = [
	(0, "Line down - awaiting belt replacement"),
]

_RECOVERY_BLENDS = [
	# relPath, t0, duration -- blends from the snapshot value back to normal operation
	("Packaging/MotorTorque", 1, 5),
	("Packaging/MotorCurrent", 1, 5),
	("Packaging/DriveVibration", 1, 5),
	("Packaging/GearboxTemp", 1, 13),
	("Packaging/InfeedBufferLevel", 2, 5),
	("Cooking/OvenBeltSpeed", 2, 4),
	("Cooking/BurnerOutput", 2, 4),
	("Cooking/OvenTemperature", 2, 7),
	("Cooking/CookTimeElapsed", 3, 4),
	("Cooking/ExitBufferLevel", 4, 5),
	("Forming/FormerCycleRate", 7, 4),
	("Forming/FormerPressure", 7, 4),
	("Forming/DieTemp", 7, 5),
	("Forming/BufferLevel", 8, 5),
	("Mixing/MixerMotorCurrent", 11, 3),
	("Mixing/SlurryTemp", 11, 4),
	("Mixing/TankLevel", 12, 5),
	("Mixing/MixTimeElapsed", 12, 4),
	("Kitting/ConveyorSpeed", 15, 3),
	("Kitting/PickRate", 15, 3),
	("Kitting/BinLevel", 16, 4),
]

_RECOVERY_CATCHUP = [
	# relPath, t0, rampDur, overshoot factor, settleDur
	# The belt runs above nominal for a while to clear the accumulated backlog.
	("Packaging/BeltSpeed", 1, 3, 1.15, 9),
	("Packaging/PackagesPerMinute", 1, 4, 1.35, 9),
]

_RECOVERY_BOOL_CLEAR = [
	("Packaging/ConveyorBeltStatus", 1),
	("Forming/ConveyorJam", 7),
	("Mixing/MotorOverload", 11),
]

_RECOVERY_STATUS = [
	("Packaging/Status", 1, "Recovering"),
	("Cooking/Status", 2, "Recovering"),
	("Forming/Status", 7, "Recovering"),
	("Mixing/Status", 11, "Recovering"),
	("Kitting/Status", 15, "Recovering"),
]

_RECOVERY_STAGES = [
	(0, "Belt replaced - restarting packaging"),
	(4, "Draining packaging and cooking buffers"),
	(8, "Restarting forming"),
	(11, "Restarting mixing"),
	(15, "Restarting kitting"),
]

SCENARIOS = {
	"PackagingConveyorJam": {
		"label": "Packaging conveyor drive jam -> belt break -> upstream backpressure",
		"rootCause": "Packaging/MotorTorque",
		"phases": [
			("DEGRADING", DEGRADE_SECS),
			("FAULT", FAULT_SECS),
			("CASCADE", CASCADE_SECS),
			("HOLD", None),          # None = read from Simulator/HoldSecs
			("RECOVERY", RECOVERY_SECS),
		],
	},
}
"""Scenario registry. Adding a scenario means adding an entry here plus a branch in
:func:`_scenarioOverrides` -- the phase machine, tag writing and UI need no changes."""

DEFAULT_SCENARIO = "PackagingConveyorJam"

PHASE_ORDER = ["NORMAL", "DEGRADING", "FAULT", "CASCADE", "HOLD", "RECOVERY"]


# ---------------------------------------------------------------------------
# Simulator state tags
# ---------------------------------------------------------------------------

_SIM_TAGS = [
	("Enabled", "Boolean", True),
	("NuisanceEnabled", "Boolean", True),
	("Phase", "String", "NORMAL"),
	("PhaseStartTs", "DateTime", None),
	("PhaseElapsed", "Int4", 0),
	("Scenario", "String", DEFAULT_SCENARIO),
	("ScenarioLabel", "String", ""),
	("ScenarioStartTs", "DateTime", None),
	("StageName", "String", "Normal operation"),
	("StageIndex", "Int4", 0),
	("Progress", "Float4", 0.0),
	("TargetLine", "String", M.DEFAULT_LINE),
	("HoldSecs", "Int4", DEFAULT_HOLD_SECS),
	("DegradeSecs", "Int4", DEGRADE_SECS),
	("TickCount", "Int8", 0),
	("LastTickTs", "DateTime", None),
	("LastError", "String", ""),
]


_SIM_KNOBS = frozenset([
	"Enabled", "NuisanceEnabled", "Scenario", "TargetLine", "HoldSecs", "DegradeSecs",
])
"""The ``Simulator`` tags a human (or a deploy) sets, as opposed to the ones this module
writes every tick.

The ``default`` provider persists tag values to ``Configuration`` -- i.e. into
``ignition/config/.../tag-definition/**/tags.json``, a tracked file. That is
deliberate for these six: it is what lets ``HoldSecs`` reach another gateway through
git rather than having to be set by hand on that gateway.

Every other ``Simulator`` tag is runtime state written at 1 Hz, and persisting those to
configuration rewrites a tracked file once a second."""

SIM_STATE_PERSISTENCE = "Database"
"""Where the non-knob ``Simulator`` tags keep their value -- the provider's internal
database rather than the config file. Overrides the provider-level setting.

This has to be set through ``system.tag.configure``. Writing ``valuePersistence``
into ``Simulator/tags.json`` by hand does **not** work: the gateway strips the key from a
standalone tag's definition file on the next scan, silently, with nothing in the log.
It does stick on a UDT *type* member, which is how the five station instances are
kept out of the diff. Call :func:`applySimPersistence` after changing this --
:func:`ensureSimTags` only creates tags that are missing, so editing the constant
alone will not reach tags that already exist."""



ENSURE_CHECK_SECS = 60
"""How often :func:`ensureSimTags` is allowed to probe/reconfigure.

A Bad read is *not* proof the tags are missing -- a faulted tag provider reports
Bad for tags that exist -- so probing every tick and reconfiguring on every Bad
read means a provider fault becomes a 1 Hz `system.tag.configure` loop that
floods the gateway log and never repairs anything. Throttling to once a minute
keeps the folder self-healing if it is genuinely deleted, without the flood."""

_ENSURE_STATE = {"ready": False, "lastTs": 0.0}


def _simTagConfigs():
	"""Tag configs for the ``Simulator`` folder, with value persistence set per tag.

	Runtime state goes to the provider's database; the knobs in :data:`_SIM_KNOBS`
	stay on the provider default, so they persist into the tracked config file.
	"""
	configs = []
	for name, dtype, value in _SIM_TAGS:
		cfg = {"name": name, "tagType": "AtomicTag", "valueSource": "memory", "dataType": dtype}
		if value is not None:
			cfg["value"] = value
		if name not in _SIM_KNOBS:
			cfg["valuePersistence"] = SIM_STATE_PERSISTENCE
		configs.append(cfg)
	return configs


def applySimPersistence():
	"""Push :data:`SIM_STATE_PERSISTENCE` onto ``Simulator`` tags that already exist.

	:func:`ensureSimTags` returns early when the tags read Good, so it never touches a
	folder that is already there -- which means a change to :data:`_SIM_KNOBS` or
	:data:`SIM_STATE_PERSISTENCE` needs this one-shot to reach a running gateway.
	Idempotent, and safe to call while the simulator is running: it merges tag
	properties and deliberately writes no values.
	"""
	configs = []
	for cfg in _simTagConfigs():
		cfg = dict(cfg)
		cfg.pop("value", None)          # never stomp a live value
		configs.append(cfg)
	system.tag.configure("[default]Exchange/Alarm Flood",
						 [{"name": "Simulator", "tagType": "Folder", "tags": configs}], "m")
	state = sorted(n for n, _, _ in _SIM_TAGS if n not in _SIM_KNOBS)
	logger.info("Applied Simulator value persistence: %d state tags -> %s, %d knobs left on "
				"the provider default" % (len(state), SIM_STATE_PERSISTENCE, len(_SIM_KNOBS)))
	return {"stateTags": state, "knobs": sorted(_SIM_KNOBS),
			"persistence": SIM_STATE_PERSISTENCE}



def ensureSimTags():
	"""Create the ``Simulator`` control/status folder if it is missing. Idempotent.

	Throttled to one probe per :data:`ENSURE_CHECK_SECS` (see above), and the
	create is verified -- if the tags still do not read Good afterwards the tag
	provider itself is unhealthy, which is logged as such instead of being
	retried silently forever.
	"""
	now = _epoch(system.date.now())
	sinceLast = now - _ENSURE_STATE["lastTs"]
	# 0 <= sinceLast guards a backwards clock step (NTP correction): a negative
	# delta would otherwise satisfy the throttle and suppress the check until the
	# wall clock caught back up to the old stamp.
	if _ENSURE_STATE["lastTs"] and 0 <= sinceLast < ENSURE_CHECK_SECS:
		return False
	_ENSURE_STATE["lastTs"] = now

	probe = system.tag.readBlocking([SIM_BASE + "/Phase"])[0]
	if probe.quality.isGood():
		_ENSURE_STATE["ready"] = True
		return False
	_ENSURE_STATE["ready"] = False

	tags = _simTagConfigs()
	system.tag.configure("[default]Exchange/Alarm Flood", [{"name": "Simulator", "tagType": "Folder", "tags": tags}], "m")

	verify = system.tag.readBlocking([SIM_BASE + "/Phase"])[0]
	if verify.quality.isGood():
		_ENSURE_STATE["ready"] = True
		logger.info("Created Alarm Flood simulator state tags")
		return True
	logger.warn("Simulator state tags still read %s after configure -- the '%s' tag "
				"provider is likely faulted, not the tags missing. Retrying in %ds."
				% (verify.quality, SIM_BASE.split("]")[0].lstrip("["), ENSURE_CHECK_SECS))
	return False


def _readSim():
	names = ["Enabled", "NuisanceEnabled", "Phase", "PhaseStartTs", "Scenario",
			 "ScenarioStartTs", "TargetLine", "HoldSecs", "DegradeSecs", "TickCount"]
	qv = system.tag.readBlocking([SIM_BASE + "/" + n for n in names])
	out = {}
	for i, n in enumerate(names):
		out[n] = qv[i].value if qv[i].quality.isGood() else None
	return {
		"enabled": bool(out["Enabled"]) if out["Enabled"] is not None else True,
		"nuisance": bool(out["NuisanceEnabled"]) if out["NuisanceEnabled"] is not None else True,
		"phase": str(out["Phase"]) if out["Phase"] else "NORMAL",
		"phaseStart": out["PhaseStartTs"],
		"scenario": str(out["Scenario"]) if out["Scenario"] else DEFAULT_SCENARIO,
		"scenarioStart": out["ScenarioStartTs"],
		"targetLine": str(out["TargetLine"]) if out["TargetLine"] else M.DEFAULT_LINE,
		"holdSecs": int(out["HoldSecs"]) if out["HoldSecs"] is not None else DEFAULT_HOLD_SECS,
		"degradeSecs": int(out["DegradeSecs"]) if out["DegradeSecs"] else DEGRADE_SECS,
		"tick": int(out["TickCount"]) if out["TickCount"] is not None else 0,
	}


def _writeSim(**kwargs):
	paths = []
	values = []
	for name, val in kwargs.items():
		paths.append(SIM_BASE + "/" + name)
		values.append(val)
	if paths:
		system.tag.writeBlocking(paths, values)


# ---------------------------------------------------------------------------
# Value maths
# ---------------------------------------------------------------------------

def _seedOf(key):
	"""Deterministic small integer from a string.

	Used to give every (line, tag) pair its own phase offset so the five lines do
	not breathe in unison. Deterministic rather than random so a line looks the
	same shape across gateway restarts.
	"""
	h = 0
	for ch in str(key):
		h = (h * 31 + ord(ch)) % 100003
	return h


def _epoch(dt):
	"""Seconds since the epoch as a float."""
	return system.date.toMillis(dt) / 1000.0


def _clampRound(value, sim):
	lo = float(sim.get("min", -1e9))
	hi = float(sim.get("max", 1e9))
	if value < lo:
		value = lo
	elif value > hi:
		value = hi
	return round(value, int(sim.get("dp", 2)))


def _normalValue(spec, seed, t):
	"""The value a tag should have during normal operation at time ``t``.

	Analogs get two out-of-phase sine components (so the trace never looks like a
	textbook sine wave) plus Gaussian measurement noise. Sawtooth tags model a
	batch timer that ramps and resets.
	"""
	sim = spec["sim"]
	if spec["kind"] == "bool":
		return bool(sim["base"])
	if spec["kind"] == "status":
		return sim["base"]

	if sim.get("shape") == "sawtooth":
		cycle = float(sim["cycle"])
		offset = (seed % int(cycle))
		p = ((t + offset) % cycle) / cycle
		v = float(sim["floor"]) + (float(sim["peak"]) - float(sim["floor"])) * p
	else:
		period = float(sim["period"])
		amp = float(sim["amp"])
		off = (seed % 1000) / 1000.0 * 2.0 * math.pi
		v = float(sim["base"])
		v += amp * math.sin(2.0 * math.pi * t / period + off)
		v += amp * 0.35 * math.sin(2.0 * math.pi * t / (period * 0.37) + off * 1.7)

	v += random.gauss(0.0, float(sim.get("noise", 0.0)))
	return _clampRound(v, sim)


def _ramp(elapsed, t0, dur, v0, v1):
	"""Smoothstep ramp from ``v0`` to ``v1`` between ``t0`` and ``t0 + dur``."""
	if elapsed <= t0:
		return v0
	if dur <= 0 or elapsed >= t0 + dur:
		return v1
	p = (float(elapsed) - t0) / float(dur)
	p = p * p * (3.0 - 2.0 * p)
	return v0 + (v1 - v0) * p


def _stageAt(stages, elapsed):
	"""Return ``(index, name)`` of the latest stage whose start time has passed."""
	idx = 0
	name = stages[0][1]
	for i, (t0, label) in enumerate(stages):
		if elapsed >= t0:
			idx = i
			name = label
	return idx, name


# ---------------------------------------------------------------------------
# Scenario evaluation
# ---------------------------------------------------------------------------

_GEARBOX_PEAK = {}
"""line -> gearbox temperature reached during the jam, so the post-fault cooldown
starts from the real value instead of an assumed one."""


def _gearboxPeak(line):
	return _GEARBOX_PEAK.get(line, GEARBOX_BASE + 8.0)


def _emit(out, relPath, value, noise=None):
	"""Add a value to the override map, clamped/rounded like a real instrument."""
	spec = M.tagSpec(relPath)
	if spec is None:
		logger.warn("Scenario references unknown tag %s" % relPath)
		return
	if spec["kind"] == "analog":
		v = float(value)
		if noise:
			v += random.gauss(0.0, float(noise))
		out[relPath] = _clampRound(v, spec["sim"])
	else:
		out[relPath] = value


def _scenarioOverrides(scenario, phase, elapsed, t, line, degradeSecs=DEGRADE_SECS):
	"""Compute the target-line tag values for a scenario phase.

	Returns a ``{relPath: value}`` map. Any tag *not* in the map keeps running its
	normal-operation model, which is what makes an unaffected station on a faulted
	line still look alive.
	"""
	out = {}
	if scenario != "PackagingConveyorJam":
		# Unknown scenario: behave like normal operation rather than writing garbage.
		return out

	if phase == "DEGRADING":
		p = max(0.0, min(1.0, float(elapsed) / float(max(1, degradeSecs))))
		for relPath, v0, delta, exponent, n0, nGain in _DEGRADE_CURVES:
			value = v0 + delta * (p ** exponent)
			_emit(out, relPath, value, noise=n0 + nGain * p)
		gbx = GEARBOX_BASE + min(GEARBOX_MAX_RISE, GEARBOX_RATE * float(elapsed))
		_GEARBOX_PEAK[line] = gbx
		_emit(out, "Packaging/GearboxTemp", gbx, noise=0.4)
		# Intermittent grabs as the jam tightens: torque spikes, not a clean curve.
		if p > 0.45 and random.random() < 0.12:
			_emit(out, "Packaging/MotorTorque",
				  out.get("Packaging/MotorTorque", 70.0) + random.uniform(2.5, 5.5))
		out["Packaging/Status"] = "Warning" if p >= 0.45 else "Running"

	elif phase == "FAULT":
		for relPath, value in _FAULT_CONST.items():
			_emit(out, relPath, value)
		# Vibration spikes as the belt parts, then falls away with the load.
		_emit(out, "Packaging/DriveVibration", _ramp(elapsed, 0, FAULT_SECS, 12.5, 3.0), noise=0.4)
		_emit(out, "Packaging/GearboxTemp", _gearboxPeak(line), noise=0.4)
		_emit(out, "Packaging/InfeedBufferLevel", _ramp(elapsed, 0, FAULT_SECS, 55.0, 57.0), noise=0.3)

	elif phase == "CASCADE":
		hot = _gearboxPeak(line)
		for relPath, value in _CASCADE_CONST.items():
			_emit(out, relPath, value, noise=0.15 if isinstance(value, float) else None)
		for relPath, t0, dur, v0, v1 in _CASCADE_RAMPS:
			spec = M.tagSpec(relPath)
			noise = float(spec["sim"].get("noise", 0.0)) * 1.6 if spec else None
			if v0 is None:
				v0 = hot
				v1 = min(v1, hot)
			_emit(out, relPath, _ramp(elapsed, t0, dur, v0, v1), noise=noise)
		for relPath, t0 in _CASCADE_BOOLS:
			if elapsed >= t0:
				out[relPath] = True
		for relPath, t0, value in _CASCADE_STATUS:
			if elapsed >= t0:
				out[relPath] = value

	elif phase == "HOLD":
		for relPath, value in _HOLD_CONST.items():
			spec = M.tagSpec(relPath)
			noise = float(spec["sim"].get("noise", 0.0)) * 0.7 if (spec and spec["kind"] == "analog") else None
			_emit(out, relPath, value, noise=noise)
		for relPath, t0, dur, v0, v1 in _HOLD_RAMPS:
			spec = M.tagSpec(relPath)
			noise = float(spec["sim"].get("noise", 0.0)) if spec else None
			if v0 is None:
				v0 = _gearboxPeak(line)
			_emit(out, relPath, _ramp(elapsed, t0, dur, v0, v1), noise=noise)

	elif phase == "RECOVERY":
		snap = _SNAPSHOT.get(line) or {}
		for relPath, t0, dur in _RECOVERY_BLENDS:
			spec = M.tagSpec(relPath)
			if spec is None:
				continue
			v0 = snap.get(relPath)
			if v0 is None:
				v0 = _HOLD_CONST.get(relPath, spec["sim"].get("base", 0.0))
			target = _normalValue(spec, _seedOf(line + "/" + relPath), t)
			_emit(out, relPath, _ramp(elapsed, t0, dur, float(v0), float(target)),
				  noise=float(spec["sim"].get("noise", 0.0)) * 0.5)
		for relPath, t0, upDur, factor, settleDur in _RECOVERY_CATCHUP:
			spec = M.tagSpec(relPath)
			if spec is None:
				continue
			seed = _seedOf(line + "/" + relPath)
			nominal = _normalValue(spec, seed, t)
			v0 = snap.get(relPath, 0.0)
			if elapsed < t0 + upDur:
				value = _ramp(elapsed, t0, upDur, float(v0), nominal * factor)
			else:
				value = _ramp(elapsed, t0 + upDur, settleDur, nominal * factor, nominal)
			_emit(out, relPath, value, noise=float(spec["sim"].get("noise", 0.0)))
		for relPath, t0 in _RECOVERY_BOOL_CLEAR:
			out[relPath] = bool(elapsed < t0)
		for relPath, t0, value in _RECOVERY_STATUS:
			held = _HOLD_CONST.get(relPath, "Running")
			if elapsed >= RECOVERY_SECS - _RECOVERY_RUNNING_LEAD:
				out[relPath] = "Running"
			elif elapsed >= t0:
				out[relPath] = value
			else:
				out[relPath] = held

	return out


def _stagesFor(phase, degradeSecs=DEGRADE_SECS):
	return {
		"DEGRADING": _degradeStages(degradeSecs),
		"CASCADE": _CASCADE_STAGES,
		"HOLD": _HOLD_STAGES,
		"RECOVERY": _RECOVERY_STAGES,
	}.get(phase)


# ---------------------------------------------------------------------------
# Tag writing
# ---------------------------------------------------------------------------

def _applyNormal(out, line, t):
	"""Fill ``out`` with the normal-operation value of every tag on ``line``."""
	for st in M.STATIONS:
		for spec in st["tags"]:
			relPath = st["instance"] + "/" + spec["name"]
			out[M.fullPath(line, relPath)] = _normalValue(spec, _seedOf(line + "/" + relPath), t)


def _commit(valueMap):
	"""Write a ``{fullPath: value}`` map, skipping unchanged discrete values.

	Analogs always change (they carry noise) so they are always written. Booleans
	and status strings are only written when the value actually differs, which
	keeps their ``OnChange`` history and the alarm journal free of duplicate churn.
	"""
	paths = []
	values = []
	for path, value in valueMap.items():
		if isinstance(value, bool) or isinstance(value, basestring):
			if _LAST.get(path, "\x00__unset__") == value:
				continue
		paths.append(path)
		values.append(value)
		_LAST[path] = value
	if paths:
		system.tag.writeBlocking(paths, values)
	return len(paths)


def _snapshotLine(line):
	"""Capture the current value of every tag on a line, keyed by relative path."""
	relPaths = M.allRelPaths()
	qv = system.tag.readBlocking([M.fullPath(line, r) for r in relPaths])
	snap = {}
	for i, rel in enumerate(relPaths):
		if qv[i].quality.isGood():
			snap[rel] = qv[i].value
	return snap


# ---------------------------------------------------------------------------
# Nuisance alarms
# ---------------------------------------------------------------------------

def _nuisance(out, targetLine, phase, tEpoch, enabled):
	"""Occasionally raise an unrelated low-priority alarm on a non-target line.

	This exists so the flood the agent analyses is not suspiciously clean -- a real
	journal always has unrelated noise in it, and the agent should be able to say
	so. Only fires during NORMAL, and never on the scenario's target line.
	"""
	for path in list(_NUISANCE.keys()):
		if tEpoch >= _NUISANCE[path]:
			out[path] = False
			del _NUISANCE[path]
	if not enabled or phase != "NORMAL":
		return
	for line in M.LINES:
		if line == targetLine:
			continue
		path = M.fullPath(line, "Kitting/ComponentShortage")
		if path in _NUISANCE:
			continue
		if random.randint(1, NUISANCE_ODDS) == 1:
			out[path] = True
			_NUISANCE[path] = tEpoch + NUISANCE_SECS
			logger.debug("Nuisance alarm raised on %s" % line)


# ---------------------------------------------------------------------------
# Phase machine
# ---------------------------------------------------------------------------

def _phaseDurations(scenario, holdSecs, degradeSecs=DEGRADE_SECS):
	"""Ordered ``[(phase, seconds)]`` for a scenario, with HOLD and DEGRADING resolved."""
	out = []
	for name, secs in SCENARIOS[scenario]["phases"]:
		if secs is None:
			out.append((name, holdSecs))
		elif name == "DEGRADING":
			out.append((name, int(degradeSecs)))
		else:
			out.append((name, secs))
	return out


def scenarioTotalSecs(scenario=DEFAULT_SCENARIO, holdSecs=DEFAULT_HOLD_SECS,
					  degradeSecs=DEGRADE_SECS):
	"""Total wall-clock length of a scenario run, in seconds."""
	return sum([s for _, s in _phaseDurations(scenario, holdSecs, degradeSecs)])


def _nextPhase(scenario, phase):
	phases = [p for p, _ in SCENARIOS[scenario]["phases"]]
	if phase not in phases:
		return "NORMAL"
	i = phases.index(phase)
	if i + 1 >= len(phases):
		return "NORMAL"
	return phases[i + 1]


# ---------------------------------------------------------------------------
# Timer entry point
# ---------------------------------------------------------------------------

def tick():
	"""One simulator iteration. Called every second by the ``AlarmFloodSim`` timer.

	Returns:
		dict: ``{"phase", "stage", "elapsed", "writes", "targetLine"}`` -- handy for
		runtime testing and for the gateway log when something looks wrong.
		``stage`` is ``timer_disabled`` when the timer's enable switch is off.
	"""
	# Timer enable switch, [default]Exchange/Demo/Control/Timers/AlarmFloodSimEnabled.
	# Distinct from Simulator/Enabled: that freezes the process values but keeps the
	# phase machine ticking; this stops the tick entirely.
	if not exchange.demo.control.timerEnabled("AlarmFloodSim"):
		return {"phase": None, "stage": "timer_disabled", "elapsed": 0, "writes": 0,
				"targetLine": None}
	try:
		ensureSimTags()
		st = _readSim()
		now = system.date.now()
		t = _epoch(now)
		tickCount = st["tick"] + 1

		if not st["enabled"]:
			_writeSim(TickCount=tickCount, LastTickTs=now, StageName="Simulator disabled")
			return {"phase": st["phase"], "stage": "disabled", "elapsed": 0, "writes": 0,
					"targetLine": st["targetLine"]}

		phase = st["phase"]
		if phase not in PHASE_ORDER:
			phase = "NORMAL"
		scenario = st["scenario"] if st["scenario"] in SCENARIOS else DEFAULT_SCENARIO
		target = st["targetLine"]
		elapsed = 0
		if st["phaseStart"] is not None:
			elapsed = max(0, int(system.date.secondsBetween(st["phaseStart"], now)))

		# --- build this tick's value map -------------------------------------
		values = {}
		fullRefresh = (tickCount % NONTARGET_REFRESH_TICKS == 0)
		for line in M.LINES:
			if line == target or fullRefresh:
				_applyNormal(values, line, t)

		if phase != "NORMAL":
			overrides = _scenarioOverrides(scenario, phase, elapsed, t, target, st["degradeSecs"])
			for relPath, value in overrides.items():
				values[M.fullPath(target, relPath)] = value

		_nuisance(values, target, phase, t, st["nuisance"])
		writes = _commit(values)

		# --- advance the phase machine ---------------------------------------
		stageIdx = 0
		stageName = "Normal operation"
		stages = _stagesFor(phase, st["degradeSecs"])
		if stages:
			stageIdx, stageName = _stageAt(stages, elapsed)

		durations = dict(_phaseDurations(scenario, st["holdSecs"], st["degradeSecs"]))
		total = scenarioTotalSecs(scenario, st["holdSecs"], st["degradeSecs"])
		progress = 0.0
		if phase != "NORMAL" and st["scenarioStart"] is not None:
			ran = max(0, int(system.date.secondsBetween(st["scenarioStart"], now)))
			progress = min(100.0, 100.0 * ran / float(total)) if total else 0.0

		if phase != "NORMAL" and elapsed >= durations.get(phase, 0):
			newPhase = _nextPhase(scenario, phase)
			if newPhase == "RECOVERY":
				_SNAPSHOT[target] = _snapshotLine(target)
			_writeSim(Phase=newPhase, PhaseStartTs=now, PhaseElapsed=0,
					  StageIndex=0, TickCount=tickCount, LastTickTs=now,
					  Progress=(0.0 if newPhase == "NORMAL" else progress),
					  StageName=("Normal operation" if newPhase == "NORMAL"
								 else (_stagesFor(newPhase, st["degradeSecs"]) or [(0, newPhase)])[0][1]))
			logger.info("Sim phase %s -> %s on %s" % (phase, newPhase, target))
			if newPhase == "NORMAL":
				_SNAPSHOT.pop(target, None)
				_writeSim(ScenarioLabel="")
			return {"phase": newPhase, "stage": "phase_change", "elapsed": elapsed,
					"writes": writes, "targetLine": target}

		_writeSim(PhaseElapsed=elapsed, StageIndex=stageIdx, StageName=stageName,
				  Progress=progress, TickCount=tickCount, LastTickTs=now)
		return {"phase": phase, "stage": stageName, "elapsed": elapsed,
				"writes": writes, "targetLine": target}

	except:
		e = sys.exc_info()[1]
		msg = "%s: %s" % (type(e).__name__, str(e))
		logger.error("Sim tick failed -- %s" % msg)
		try:
			_writeSim(LastError=msg)
		except:
			pass
		return {"phase": "ERROR", "stage": msg, "elapsed": 0, "writes": 0, "targetLine": None}


# ---------------------------------------------------------------------------
# Control API -- called from Perspective buttons, the script console, or an agent
# ---------------------------------------------------------------------------

def startFlood(linePath=None, scenario=None, holdSecs=None, degradeSecs=None):
	"""Begin a fault scenario. No alarm is written directly -- the physics produce them.

	Args:
		linePath (str): Line to fault, e.g. ``Site1/Area1/Line1``. Defaults to the
			line currently selected in ``Simulator/TargetLine``.
		scenario (str): Key in :data:`SCENARIOS`. Defaults to the current selection.
		holdSecs (int): Seconds to hold the line down after the cascade before
			recovering. Defaults to the current ``Simulator/HoldSecs`` value (60).
		degradeSecs (int): Seconds for the drive to bind and the belt to part.
			Defaults to ``Simulator/DegradeSecs`` (10). Stretch this to 120-180 for a
			long, readable torque trend instead of a fast snap.

	Returns:
		dict: The run parameters, including the expected total duration.
	"""
	ensureSimTags()
	st = _readSim()
	line = linePath or st["targetLine"]
	if line not in M.LINES:
		raise ValueError("Unknown line '%s' -- expected one of %s" % (line, ", ".join(M.LINES)))
	key = scenario or st["scenario"]
	if key not in SCENARIOS:
		raise ValueError("Unknown scenario '%s' -- expected one of %s" % (key, ", ".join(SCENARIOS.keys())))
	hold = int(holdSecs) if holdSecs is not None else st["holdSecs"]
	degrade = max(1, int(degradeSecs)) if degradeSecs is not None else st["degradeSecs"]

	if st["phase"] != "NORMAL":
		logger.warn("startFlood called while phase=%s on %s -- restarting on %s"
					% (st["phase"], st["targetLine"], line))
		resetLine(st["targetLine"])

	# Start from a clean, known-normal line so precursor alarms read cleanly.
	resetLine(line)
	now = system.date.now()
	_SNAPSHOT.pop(line, None)
	_writeSim(Phase="DEGRADING", PhaseStartTs=now, PhaseElapsed=0, ScenarioStartTs=now,
			  Scenario=key, ScenarioLabel=SCENARIOS[key]["label"], TargetLine=line,
			  HoldSecs=hold, DegradeSecs=degrade, StageIndex=0,
			  StageName=_degradeStages(degrade)[0][1],
			  Progress=0.0, LastError="")
	total = scenarioTotalSecs(key, hold, degrade)
	logger.info("Flood scenario '%s' started on %s (degrade=%ds, hold=%ds, total=%ds)"
				% (key, line, degrade, hold, total))
	return {"scenario": key, "label": SCENARIOS[key]["label"], "line": line,
			"degradeSecs": degrade, "holdSecs": hold, "totalSecs": total,
			"phases": _phaseDurations(key, hold, degrade)}


def abortFlood():
	"""Skip straight to RECOVERY from wherever the scenario currently is."""
	ensureSimTags()
	st = _readSim()
	if st["phase"] in ("NORMAL", "RECOVERY"):
		return {"phase": st["phase"], "changed": False}
	_SNAPSHOT[st["targetLine"]] = _snapshotLine(st["targetLine"])
	_writeSim(Phase="RECOVERY", PhaseStartTs=system.date.now(), PhaseElapsed=0,
			  StageIndex=0, StageName=_RECOVERY_STAGES[0][1])
	logger.info("Flood scenario aborted on %s -- recovering" % st["targetLine"])
	return {"phase": "RECOVERY", "changed": True, "line": st["targetLine"]}


def resetLine(linePath=None):
	"""Force one line straight back to normal values and clear the phase machine.

	Unlike :func:`abortFlood` this is immediate -- no recovery ramp. Use it to clear
	a half-finished demo.
	"""
	ensureSimTags()
	st = _readSim()
	line = linePath or st["targetLine"]
	values = {}
	_applyNormal(values, line, _epoch(system.date.now()))
	_commit(values)
	if line == st["targetLine"]:
		_writeSim(Phase="NORMAL", PhaseStartTs=system.date.now(), PhaseElapsed=0,
				  StageIndex=0, StageName="Normal operation", Progress=0.0, ScenarioLabel="")
	_SNAPSHOT.pop(line, None)
	return "Reset %s to normal operating conditions" % line


def resetAll():
	"""Force every line back to normal values and clear the phase machine."""
	ensureSimTags()
	values = {}
	t = _epoch(system.date.now())
	for line in M.LINES:
		_applyNormal(values, line, t)
	_NUISANCE.clear()
	_SNAPSHOT.clear()
	_commit(values)
	_writeSim(Phase="NORMAL", PhaseStartTs=system.date.now(), PhaseElapsed=0, StageIndex=0,
			  StageName="Normal operation", Progress=0.0, ScenarioLabel="", LastError="")
	return "Reset %d lines to normal operating conditions" % len(M.LINES)


def setEnabled(enabled=True):
	"""Turn continuous variation on or off. Off freezes every tag where it stands."""
	ensureSimTags()
	_writeSim(Enabled=bool(enabled))
	return {"enabled": bool(enabled)}




def sample(linePath=None):
	"""Return the current value of every tag on a line, keyed by relative path.

	A quick way to confirm the simulator is actually moving values (call it twice
	and compare) and to see where a line sits mid-scenario.
	"""
	ensureSimTags()
	line = linePath or _readSim()["targetLine"]
	return _snapshotLine(line)


def status():
	"""Return the simulator's current state as a plain dict (for UI or an agent)."""
	ensureSimTags()
	st = _readSim()
	st["scenarioLabel"] = SCENARIOS.get(st["scenario"], {}).get("label", "")
	st["totalSecs"] = scenarioTotalSecs(st["scenario"], st["holdSecs"], st["degradeSecs"])
	st["lines"] = M.LINES
	st["scenarios"] = sorted(SCENARIOS.keys())
	st["alarmsPerLine"] = M.alarmCount()
	# False means the last probe could not read Simulator/Phase Good -- i.e. the tag
	# provider is unhealthy and every field above is a default, not a reading.
	# Surfaced explicitly because Bad tag reads are otherwise silently
	# indistinguishable from real values here.
	st["simTagsReady"] = _ENSURE_STATE["ready"]
	return st
