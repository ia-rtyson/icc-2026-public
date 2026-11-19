# Keeps `ex_icc_equipment_downtime_events` populated for a "top five downtime
# reasons per equipment" report on the five Alarm Flood stations (Kitting,
# Mixing, Forming, Cooking, Packaging).
#
# Deliberately NOT driven off real exchange.alarmFlood.control.simulateFlood() runs -- a flood
# is something a presenter triggers by hand, so wiring generation to it would
# starve the table between demos. Instead a timer fabricates events on its
# own, once a minute, regardless of whether the line is actually in a fault.
# The REASONS below are drawn from exchange.alarmFlood.model's real alarm vocabulary
# per station (see that module), so the story still reads as "the kind of
# thing that goes wrong on this line" without literally requiring a flood to
# have happened.
#
# Driven by the `EquipmentDowntimeFeeder` gateway timer. All logic lives here
# so the timer handler stays a one-liner, matching exchange.designerEmbeds.events / exchange.alarmFlood.sim.
# Every statement is a named query under Exchange/Demo/Downtime/.

import random
import sys

log = system.util.getLogger('exchange.demo.Downtime')

DB = 'postgres'
PROJECT = 'icc-2026'
TABLE = 'ex_icc_equipment_downtime_events'
NQ = 'Exchange/Demo/Downtime/'

# How long history is kept. Anything older is deleted by the first tick of
# each local day; the other ticks only insert.
RETENTION_DAYS = 7

# ex_icc_demo_housekeeping row that records the day the purge last ran
PURGE_JOB = 'equipment_downtime_purge'

# Relative pick-frequency across the five stations. Packaging is weighted
# heaviest on purpose -- it is where this demo's own fault scenario
# (PackagingConveyorJam, see exchange.alarmFlood.sim) always starts, so it is the
# station a presenter is most likely to be asked about.
EQUIPMENT_WEIGHTS = [
	('Kitting', 15),
	('Mixing', 15),
	('Forming', 18),
	('Cooking', 17),
	('Packaging', 35),
]

# Station-specific reasons, weighted, drawn from the real alarm names in
# exchange.alarmFlood.model.STATIONS so the vocabulary matches what the line actually
# alarms on -- reworded slightly since these are downtime *reasons*, not
# raw alarm text.
REASONS = {
	'Kitting': [
		('Component shortage at infeed', 20),
		('Bin level high, discharge blocked', 14),
		('Pick rate below target', 12),
		('Conveyor speed low', 10),
		('Photo-eye fault at kitting infeed', 8),
	],
	'Mixing': [
		('Mixer motor overload', 20),
		('Tank level high, discharge delayed', 14),
		('Mix time exceeded', 12),
		('Mixer motor current high', 10),
		('Slurry temperature out of range', 8),
	],
	'Forming': [
		('Forming conveyor jam', 22),
		('Former pressure high', 14),
		('Die temperature high', 10),
		('Former cycle rate low', 10),
		('Buffer level high, upstream backup', 10),
	],
	'Cooking': [
		('Oven belt speed low', 20),
		('Oven temperature excursion', 12),
		('Cook time exceeded, overcook risk', 8),
		('Burner output high', 10),
		('Exit buffer level high', 10),
	],
	'Packaging': [
		('Conveyor drive torque high', 20),
		('Drive vibration high', 14),
		('Drive current high', 12),
		('Conveyor belt break', 10),
		('Gearbox temperature high', 8),
		('Infeed buffer level high', 10),
		('Packaging throughput low', 8),
	],
}

# Cross-station reasons that have nothing to do with the process model --
# the variety the demo data needs so every event is not a mechanical fault.
GENERIC_REASONS = [
	('Scheduled changeover', 10),
	('Material shortage', 8),
	('Operator break / shift change', 6),
	('Quality hold', 6),
	('Sensor calibration', 6),
	('Preventive maintenance', 6),
]

# Fraction of events that pull from GENERIC_REASONS instead of the chosen
# equipment's own list.
GENERIC_REASON_RATE = 0.22

# Per tick (one simulated minute), how many events land: mostly none, most of
# the rest exactly one. Cumulative-weight pairs, see _weightedChoice.
EVENT_COUNT_WEIGHTS = [(0, 55), (1, 40), (2, 5)]

# Most rows topReasons will return, whatever the caller asks for
MAX_TOP_REASONS = 100


def _runNamed(queryName, parameters, tx=None):
	"""Run an Exchange/Demo/Downtime/ named query, inside a transaction when given one.

	Args:
		queryName (str): Query name inside the Exchange/Demo/Downtime/ folder.
		parameters (dict): Named-query parameters.
		tx (str): Transaction id, or None to run in the query's own transaction.

	Returns:
		object: Whatever runNamedQuery returns -- a dataset or a row count.
	"""
	if tx is None:
		return system.db.runNamedQuery(PROJECT, NQ + queryName, parameters)
	return system.db.runNamedQuery(PROJECT, NQ + queryName, parameters, tx=tx)


def _weightedChoice(pairs):
	"""Pick one item from a list of (value, weight) pairs."""
	total = sum(w for _, w in pairs)
	pick = random.uniform(0.0, total)
	upto = 0.0
	for value, weight in pairs:
		upto += weight
		if pick <= upto:
			return value
	return pairs[-1][0]


def _pickEquipment():
	"""Pick a station, weighted by EQUIPMENT_WEIGHTS."""
	return _weightedChoice(EQUIPMENT_WEIGHTS)


def _pickReason(equipment):
	"""Pick a downtime reason for a station, sometimes a generic one."""
	if random.random() < GENERIC_REASON_RATE:
		return _weightedChoice(GENERIC_REASONS)
	return _weightedChoice(REASONS[equipment])


def _pickDuration(reason):
	"""Pick a plausible duration in minutes for a reason."""
	# Generic operational reasons (changeovers, PM, quality holds) run longer
	# than a mechanical fault; process/mechanical faults are usually short.
	# Skewed with triangular() rather than a flat range, so most events are
	# brief and a long one is the exception, not the rule.
	generic = any(reason == r for r, _ in GENERIC_REASONS)
	if generic:
		minutes = random.triangular(10.0, 90.0, 25.0)
	else:
		minutes = random.triangular(3.0, 60.0, 10.0)
	return round(minutes, 1)


def _eventRow(equipment, reason, when, duration):
	"""Build one row for the InsertEvents batch.

	Args:
		equipment (str): Station name.
		reason (str): Downtime reason.
		when (Date): Start time.
		duration (float): Duration in minutes.

	Returns:
		dict: Keyed by column name; start_time as text in the gateway time zone.
	"""
	return {
		'equipment': equipment,
		'reason': reason,
		'start_time': system.date.format(when, 'yyyy-MM-dd HH:mm:ss.SSS'),
		'duration_minutes': duration,
	}


def _insertRows(rows, tx=None):
	"""Insert downtime rows in one round trip through Exchange/Demo/Downtime/InsertEvents.

	Args:
		rows (list): Dicts from :func:`_eventRow`.
		tx (str): Optional transaction id.

	Returns:
		int: Rows inserted.
	"""
	if not rows:
		return 0
	return _runNamed('InsertEvents', {'eventsJson': system.util.jsonEncode(rows)}, tx)


def purgeOld(days=RETENTION_DAYS, tx=None):
	"""Delete events older than the retention window.

	Args:
		days (int): Retention window in days.
		tx (str): Optional transaction id.

	Returns:
		int: Rows removed.
	"""
	cutoff = system.date.addDays(system.date.now(), -int(days))
	return _runNamed('DeleteOlderThan', {'cutoff': cutoff}, tx)


def _purgeDue():
	"""True when the retention purge has not run yet today (gateway local date).

	The flag lives in ex_icc_demo_housekeeping rather than a module global,
	because a project scan reloads this module. If the flag cannot be read the
	purge is skipped; it is housekeeping, and the next day retries it.
	"""
	today = system.date.format(system.date.now(), 'yyyy-MM-dd')
	try:
		ds = system.db.runNamedQuery(PROJECT, 'Exchange/Demo/SelectLastRun', {'job': PURGE_JOB})
	except:
		log.warn('Could not read the downtime purge flag: %s' % sys.exc_info()[1])
		return False
	if ds.getRowCount() == 0:
		return True
	last = ds.getValueAt(0, 'last_run_at')
	return last is None or system.date.format(last, 'yyyy-MM-dd') != today


def tick():
	"""One feeder pass: maybe insert, and purge once a day. Called by the timer every minute.

	Insert and purge run in one transaction. The purge only runs on the first
	tick of each local day, so it fires on that day even if the gateway was off
	at midnight. Gated by
	``[default]Exchange/Demo/Control/Timers/EquipmentDowntimeFeederEnabled``.

	Returns:
		dict: ``{inserted, events, purged}``, ``{disabled: True}`` when the timer
		switch is off, or None on failure.
	"""
	if not exchange.demo.control.timerEnabled('EquipmentDowntimeFeeder'):
		return {'disabled': True}
	try:
		count = _weightedChoice(EVENT_COUNT_WEIGHTS)
		made = []
		rows = []
		for _ in range(count):
			# Jitter within the last minute rather than pinning every event to
			# the exact tick time, so start_time does not read as synthetic the
			# moment someone looks at raw rows
			when = system.date.addSeconds(system.date.now(), -random.randint(0, 59))
			equipment = _pickEquipment()
			reason = _pickReason(equipment)
			duration = _pickDuration(reason)
			made.append((equipment, reason, duration))
			rows.append(_eventRow(equipment, reason, when, duration))
		purgeNow = _purgeDue()
		purged = 0
		tx = system.db.beginNamedQueryTransaction(PROJECT, DB, system.db.READ_COMMITTED, 30000)
		try:
			_insertRows(rows, tx)
			if purgeNow:
				purged = purgeOld(tx=tx)
				system.db.runNamedQuery(PROJECT, 'Exchange/Demo/StampRun', {'job': PURGE_JOB,
					'result': '%d deleted older than %d days' % (purged, RETENTION_DAYS)}, tx=tx)
			system.db.commitTransaction(tx)
		except:
			system.db.rollbackTransaction(tx)
			raise
		finally:
			system.db.closeTransaction(tx)
		if purged:
			log.info('purged %d downtime event(s) older than %d days'
				% (purged, RETENTION_DAYS))
		return {'inserted': len(made), 'events': made, 'purged': purged}
	except:
		e = sys.exc_info()[1]
		# A demo feeder must never take its timer thread down with it, so this
		# logs and returns rather than propagating. Bare except: JDBC failures
		# are Java exceptions.
		log.error('exchange.demo.downtime.tick failed: %s' % str(e))
		return None


def backfill(days=RETENTION_DAYS, perEquipmentPerDay=25):
	"""Populate the retention window from scratch, spread across `days`.

	Only needed on a fresh database, or after the table has gone stale past
	the retention window -- the feeder alone would take a full week to build
	up a usable "top five" story from nothing. Existing rows are left alone.
	All rows go in as one batched insert.

	Args:
		days (int): How many days back to fill.
		perEquipmentPerDay (int): Events per station per day.

	Returns:
		int: Rows inserted.
	"""
	now = system.date.now()
	rows = []
	for equipment, _ in EQUIPMENT_WEIGHTS:
		total = int(days) * int(perEquipmentPerDay)
		for _ in range(total):
			ageMinutes = random.uniform(0.0, float(days) * 24 * 60)
			when = system.date.addMinutes(now, int(-ageMinutes))
			reason = _pickReason(equipment)
			rows.append(_eventRow(equipment, reason, when, _pickDuration(reason)))
	made = _insertRows(rows)
	log.info('backfilled %d downtime events over %d days' % (made, days))
	return made


def topReasons(equipment=None, limit=5):
	"""Top reasons by event count and total downtime, optionally for one equipment.

	This is the query the "top five downtime reasons per piece of equipment"
	report runs.

	Args:
		equipment (str): One station, or None / empty for every station.
		limit (int): Rows to return, capped at :data:`MAX_TOP_REASONS`.

	Returns:
		list: Dicts ``{equipment, reason, occurrences, total_minutes}``, ordered
		by occurrences descending.
	"""
	maxRows = max(1, min(int(limit), MAX_TOP_REASONS))
	rows = _runNamed('SelectTopReasons', {'equipment': equipment or '', 'maxRows': maxRows})
	out = []
	for i in range(rows.getRowCount()):
		out.append({
			'equipment': rows.getValueAt(i, 'equipment'),
			'reason': rows.getValueAt(i, 'reason'),
			'occurrences': rows.getValueAt(i, 'occurrences'),
			'total_minutes': rows.getValueAt(i, 'total_minutes'),
		})
	return out


def status():
	"""Row counts and window, for checking the feeder is healthy before going on stage.

	Returns:
		dict: ``{total, oldest, newest, equipmentCount, perEquipment}``, or None
		if the query returned nothing.
	"""
	rows = _runNamed('SelectStatus', {})
	if rows.getRowCount() == 0:
		return None
	perEquipment = _runNamed('SelectCountsByEquipment', {})
	return {
		'total': rows.getValueAt(0, 'total'),
		'oldest': rows.getValueAt(0, 'oldest'),
		'newest': rows.getValueAt(0, 'newest'),
		# The column is snake_case: an unquoted Postgres alias folds to lower
		# case, which is why the old camelCase alias never matched
		'equipmentCount': rows.getValueAt(0, 'equipment_count'),
		'perEquipment': dict([(perEquipment.getValueAt(i, 'equipment'), perEquipment.getValueAt(i, 'n'))
			for i in range(perEquipment.getRowCount())]),
	}
