"""Enable switches for every gateway timer in the project.

One Boolean memory tag per timer, all in one folder::

	[default]Exchange/Demo/Control/Timers/<TimerName>Enabled

Every library function a timer calls checks its switch first
(:func:`timerEnabled`), so a timer can be stopped from a tag write -- no Designer
trip, no project edit -- during maintenance or on a gateway where it must not
run.

The tags are created on demand, enabled, by :func:`ensureTimerSwitches`, and
never overwritten once they exist. They take the ``default`` provider's value
persistence, which is ``Configuration``: a switch's value is written into the
tracked tag config files, so turning a timer off and committing that change is
what makes it stay off on every gateway the repo deploys to.

Three timers delete things -- :data:`DESTRUCTIVE`. For those the switch is the
environment guard, and it fails **closed**: if the switch cannot be read Good,
the timer does not run. Every other timer fails open, because a demo
simulator that stops on a tag-provider hiccup is worse than one that tries.
"""

import sys

logger = system.util.getLogger("exchange.demo.Control")

_PROVIDER = "[default]"
_FOLDER_NAMES = ["Exchange", "Demo", "Control", "Timers"]

TIMER_FOLDER = _PROVIDER + "/".join(_FOLDER_NAMES)
"""Folder holding one ``<TimerName>Enabled`` switch per gateway timer."""

TIMERS = [
	"AlarmFloodDetector",
	"AlarmFloodSim",
	"DashboardConfigPurge",
	"DemoEventsFeeder",
	"EquipmentDowntimeFeeder",
	"IssueFaultRearm",
	"IssueTicketPurge",
	"TagImportFolderPurge",
]
"""Every gateway timer in the project, by its resource name under ``timer/``."""

DESTRUCTIVE = ["DashboardConfigPurge", "IssueTicketPurge", "TagImportFolderPurge"]
"""Timers that delete data. Their switch fails closed -- see the module docstring."""

ENSURE_CHECK_SECS = 60
"""Shortest gap between two attempts to create missing switches.

A Bad read does not prove a tag is missing -- a faulted provider reports Bad for
tags that exist -- so an unthrottled create-on-Bad would turn a provider fault
into a 1 Hz ``system.tag.configure`` loop from the simulator timer alone."""

_DOCUMENTATION = ("Enable switch for the %s gateway timer. False stops the timer's "
	"library function at its first line. Created by exchange.demo.control.ensureTimerSwitches.")


def _moduleGlobals():
	"""Return this module's dictionary in the gateway globals.

	Kept in ``system.util.getGlobals()`` rather than at module level so the
	throttle and the log-once flags survive a project scan, which reloads this
	module and would otherwise re-log every fault and re-probe immediately.

	Returns:
		dict: The ``icc2026`` / ``demoControl`` namespace, created on first use,
		or a module-level dict if the globals cannot be reached.
	"""
	try:
		return system.util.getGlobals().setdefault("icc2026", {}).setdefault("demoControl", {})
	except:
		# Bare except: the switch check must never raise into a timer
		return _LOCAL_STATE


_LOCAL_STATE = {}


def switchPath(timerName):
	"""Return the full tag path of a timer's enable switch.

	Args:
		timerName (str): Timer resource name, e.g. ``AlarmFloodSim``.

	Returns:
		str: ``[default]Exchange/Demo/Control/Timers/<timerName>Enabled``.
	"""
	return "%s/%sEnabled" % (TIMER_FOLDER, timerName)


def ensureTimerSwitches():
	"""Create every missing timer switch, enabled. Idempotent.

	Existing switches are never touched, so a timer someone turned off stays
	off: only switches that do not exist go into the configure call. Merge is
	therefore safe -- it cannot reach a switch that is not in the list -- and,
	unlike ignore, it is well defined on the folders above the switches
	whether or not they exist yet.

	Returns:
		list: Names of the timers whose switch was created on this call.
	"""
	missing = [name for name in TIMERS if not system.tag.exists(switchPath(name))]
	if not missing:
		return []
	configs = []
	for name in missing:
		configs.append({
			"name": name + "Enabled",
			"tagType": "AtomicTag",
			"valueSource": "memory",
			"dataType": "Boolean",
			"value": True,
			"documentation": _DOCUMENTATION % name,
		})
	# Wrap the switches in one folder config per level, innermost first
	node = configs
	for folderName in reversed(_FOLDER_NAMES):
		node = [{"name": folderName, "tagType": "Folder", "tags": node}]
	system.tag.configure(_PROVIDER, node, "m")
	logger.infof("Created timer enable switches under %s: %s", TIMER_FOLDER, ", ".join(missing))
	return missing


def _ensureThrottled():
	"""Run :func:`ensureTimerSwitches` at most once per :data:`ENSURE_CHECK_SECS`.

	Never raises: a failure here is logged and the caller falls back to its
	fail-open or fail-closed default.
	"""
	state = _moduleGlobals()
	now = system.date.toMillis(system.date.now()) / 1000.0
	lastTs = state.get("ensureTs", 0.0)
	# 0 <= sinceLast also guards a backwards clock step (NTP correction)
	sinceLast = now - lastTs
	if lastTs and 0 <= sinceLast < ENSURE_CHECK_SECS:
		return
	state["ensureTs"] = now
	try:
		ensureTimerSwitches()
	except:
		# Bare except: system.tag.* failures are Java exceptions
		logger.warnf("Could not create the timer enable switches: %s", sys.exc_info()[1])


def _noteUnreadable(timerName, quality):
	"""Log an unreadable switch once per episode rather than on every tick.

	Args:
		timerName (str): The timer whose switch could not be read.
		quality (object): The quality it read with, for the log line.
	"""
	flags = _moduleGlobals().setdefault("unreadable", {})
	if flags.get(timerName):
		return
	flags[timerName] = True
	if timerName in DESTRUCTIVE:
		logger.warnf("Enable switch %s reads %s; %s deletes data, so it will not run "
			"until the switch reads Good.", switchPath(timerName), quality, timerName)
	else:
		logger.warnf("Enable switch %s reads %s; running %s anyway (fails open).",
			switchPath(timerName), quality, timerName)


def timerEnabled(timerName):
	"""Return whether a timer should run this tick. Never raises.

	Reads the timer's switch. A missing switch is created (throttled) and read
	again. If it still cannot be read Good, a destructive timer is refused and
	any other timer is allowed.

	Args:
		timerName (str): Timer resource name, one of :data:`TIMERS`.

	Returns:
		bool: True if the timer's library function should proceed.
	"""
	if timerName not in TIMERS:
		logger.warnf("timerEnabled called for unknown timer '%s'; refusing to run it.", timerName)
		return False
	path = switchPath(timerName)
	quality = None
	try:
		qv = system.tag.readBlocking([path])[0]
		if not qv.quality.isGood():
			_ensureThrottled()
			qv = system.tag.readBlocking([path])[0]
		quality = qv.quality
		if qv.quality.isGood():
			_moduleGlobals().setdefault("unreadable", {}).pop(timerName, None)
			return bool(qv.value)
	except:
		# Bare except: a faulted provider throws Java exceptions out of readBlocking
		quality = sys.exc_info()[1]
	_noteUnreadable(timerName, quality)
	return timerName not in DESTRUCTIVE


def setTimerEnabled(timerName, enabled):
	"""Turn one timer on or off.

	Args:
		timerName (str): Timer resource name, one of :data:`TIMERS`.
		enabled (bool): The new switch value.

	Returns:
		dict: ``{timer, enabled, quality}`` -- quality of the write.

	Raises:
		ValueError: If timerName is not one of :data:`TIMERS`.
	"""
	if timerName not in TIMERS:
		raise ValueError("Unknown timer '%s'. Known: %s." % (timerName, ", ".join(TIMERS)))
	ensureTimerSwitches()
	quality = system.tag.writeBlocking([switchPath(timerName)], [bool(enabled)])[0]
	logger.infof("Timer %s switched %s.", timerName, "on" if enabled else "off")
	return {"timer": timerName, "enabled": bool(enabled), "quality": str(quality)}


def timerStatus():
	"""Return every timer's switch state, for a pre-stage health check.

	Returns:
		list: One dict per timer -- ``{timer, enabled, quality, destructive, path}``.
		``enabled`` is None when the switch could not be read Good.
	"""
	ensureTimerSwitches()
	paths = [switchPath(name) for name in TIMERS]
	qvs = system.tag.readBlocking(paths)
	out = []
	for name, path, qv in zip(TIMERS, paths, qvs):
		good = qv.quality.isGood()
		out.append({
			"timer": name,
			"enabled": bool(qv.value) if good else None,
			"quality": str(qv.quality),
			"destructive": name in DESTRUCTIVE,
			"path": path,
		})
	return out
