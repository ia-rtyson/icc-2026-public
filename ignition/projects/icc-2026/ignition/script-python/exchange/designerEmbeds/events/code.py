# Keeps `ex_icc_demo_equipment_events` alive for the Designer Embeds demo.
#
# The table shipped as a static 14-day backfill. The page's default filter is a
# rolling "last 24 hours", so a static table goes empty a day after it is
# generated and the demo shows nothing on stage. This module is what stops that:
# a timer inserts new events as time passes and drops anything older than the
# retention window, so the last 24 hours is always populated and the table never
# grows without bound.
#
# Driven by the `DemoEventsFeeder` gateway timer. All logic lives here so the
# timer handler stays a one-liner, matching AlarmFloodDetector. Every statement
# is a named query under Exchange/DesignerEmbeds/.

import random
import sys

log = system.util.getLogger('exchange.designerEmbeds.Events')

DB = 'postgres'
PROJECT = 'icc-2026'
TABLE = 'ex_icc_demo_equipment_events'
NQ = 'Exchange/DesignerEmbeds/'

# How long history is kept. Anything older is deleted on every tick.
RETENTION_DAYS = 7

# Events older than this are eligible to be acknowledged by the ageing pass, so
# the Ack column tells a story instead of being frozen at whatever was seeded.
ACK_AFTER_HOURS = 2

# Fraction of brand-new events that arrive already acknowledged. Most do not:
# a brand-new event nobody has looked at yet is the realistic case, and it is
# also what the page's default filter (unacknowledged) needs in order to show
# anything.
NEW_ACK_RATE = 0.25

# How many stale unacknowledged events get acked per tick.
ACK_PER_TICK = 2

# (equipment_name, area) -- matches the seeded data exactly.
EQUIPMENT = [
	('Bagger 1', 'Packaging'),
	('Bagger 2', 'Packaging'),
	('Boiler 1', 'Utilities'),
	('Chiller 1', 'Utilities'),
	('Compressor', 'Utilities'),
	('Cooler 1', 'Roasting'),
	('Destoner 1', 'Cleaning'),
	('Feeder 1', 'Roasting'),
	('Palletizer', 'Packaging'),
	('Roaster 1', 'Roasting'),
	('Roaster 2', 'Roasting'),
	('Sealer 1', 'Packaging'),
]

# (event_type, severity) -- severity is a property of the event type in the
# seeded data, so it is kept that way rather than randomised independently.
EVENT_TYPES = [
	('Bearing temperature', 3),
	('Comms timeout', 4),
	('Door interlock', 5),
	('Feed jam', 4),
	('Filter differential', 2),
	('Lubrication low', 3),
	('Maintenance due', 1),
	('Motor overload', 4),
	('Operator note', 1),
	('Recipe change', 1),
	('Setpoint deviation', 2),
	('Vibration high', 3),
]


def _runNamed(queryName, parameters, tx=None):
	"""Run an Exchange/DesignerEmbeds/ named query, inside a transaction when one is given.

	Args:
		queryName (str): Query name inside the Exchange/DesignerEmbeds/ folder.
		parameters (dict): Named-query parameters.
		tx (str): Transaction id, or None to run in the query's own transaction.

	Returns:
		object: Whatever runNamedQuery returns -- a dataset or a row count.
	"""
	if tx is None:
		return system.db.runNamedQuery(PROJECT, NQ + queryName, parameters)
	return system.db.runNamedQuery(PROJECT, NQ + queryName, parameters, tx=tx)


def _eventRow(when, acknowledged):
	"""Build one random event row for the InsertEvents batch.

	Args:
		when (Date): The event time.
		acknowledged (int): 1 if the event arrives acknowledged, else 0.

	Returns:
		dict: Keyed by column name; event_time as text in the gateway time zone.
	"""
	equipment, area = random.choice(EQUIPMENT)
	eventType, severity = random.choice(EVENT_TYPES)
	return {
		'equipment_name': equipment,
		'area': area,
		'event_type': eventType,
		'event_time': system.date.format(when, 'yyyy-MM-dd HH:mm:ss.SSS'),
		'severity': severity,
		'acknowledged': int(acknowledged),
		'notes': '%s on %s (%s)' % (eventType, equipment, area),
	}


def _insertRows(rows, tx=None):
	"""Insert event rows in one round trip through Exchange/DesignerEmbeds/InsertEvents.

	Args:
		rows (list): Dicts from :func:`_eventRow`.
		tx (str): Optional transaction id.

	Returns:
		int: Rows inserted.
	"""
	if not rows:
		return 0
	return _runNamed('InsertEvents', {'eventsJson': system.util.jsonEncode(rows)}, tx)


def insertEvent(when=None, tx=None):
	"""Insert one event, defaulting to now. Mostly unacknowledged -- see NEW_ACK_RATE.

	Args:
		when (Date): The event time. Defaults to now.
		tx (str): Optional transaction id.

	Returns:
		str: The note text written.
	"""
	if when is None:
		when = system.date.now()
	acknowledged = 1 if random.random() < NEW_ACK_RATE else 0
	row = _eventRow(when, acknowledged)
	_insertRows([row], tx)
	return row['notes']


def ageAcknowledgements(limit=ACK_PER_TICK, tx=None):
	"""Acknowledge the oldest still-unacknowledged events.

	Without this every event ever inserted stays unacknowledged forever, and the
	'Show acknowledged' filter stops distinguishing anything.

	Args:
		limit (int): Most events to acknowledge.
		tx (str): Optional transaction id.

	Returns:
		int: Rows acknowledged.
	"""
	cutoff = system.date.addHours(system.date.now(), -ACK_AFTER_HOURS)
	return _runNamed('AcknowledgeOldest', {'cutoff': cutoff, 'maxRows': int(limit)}, tx)


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


def tick():
	"""One feeder pass: insert, age acknowledgements, purge. Called by the timer.

	The three writes run in one transaction, so a failure part-way leaves the
	table as it was. Gated by ``[default]Exchange/Demo/Control/Timers/DemoEventsFeederEnabled``.

	Returns:
		dict: ``{inserted, acknowledged, purged}``, ``{disabled: True}`` when the
		timer switch is off, or None on failure.
	"""
	if not exchange.demo.control.timerEnabled('DemoEventsFeeder'):
		return {'disabled': True}
	try:
		tx = system.db.beginNamedQueryTransaction(PROJECT, DB, system.db.READ_COMMITTED, 30000)
		try:
			insertEvent(tx=tx)
			acked = ageAcknowledgements(tx=tx)
			purged = purgeOld(tx=tx)
			system.db.commitTransaction(tx)
		except:
			system.db.rollbackTransaction(tx)
			raise
		finally:
			system.db.closeTransaction(tx)
		if purged:
			log.info('purged %d event(s) older than %d days' % (purged, RETENTION_DAYS))
		return {'inserted': 1, 'acknowledged': acked, 'purged': purged}
	except:
		e = sys.exc_info()[1]
		# A demo feeder must never take its timer thread down with it, so this
		# logs and returns rather than propagating. Bare except: JDBC and tag
		# failures are Java exceptions.
		log.error('exchange.designerEmbeds.events.tick failed: %s' % str(e))
		return None


def backfill(days=RETENTION_DAYS, perDay=48):
	"""Populate the retention window from scratch.

	Only needed on a fresh database, or after the table has been left to go
	stale for longer than the retention window. Existing rows are left alone.
	All rows go in as one batched insert rather than one statement per row.

	Args:
		days (int): How many days back to fill.
		perDay (int): Events per day.

	Returns:
		int: Rows inserted.
	"""
	now = system.date.now()
	total = int(days) * int(perDay)
	spacingMins = (int(days) * 24 * 60) / float(total)
	rows = []
	for i in range(total):
		when = system.date.addMinutes(now, int(-1 * i * spacingMins))
		ageHours = (i * spacingMins) / 60.0
		# Older events are mostly acknowledged; recent ones mostly are not
		if ageHours < ACK_AFTER_HOURS:
			ack = 0
		else:
			ack = 1 if random.random() < 0.75 else 0
		rows.append(_eventRow(when, ack))
	made = _insertRows(rows)
	log.info('backfilled %d events over %d days' % (made, days))
	return made


def status():
	"""Row counts and window, for checking the demo is healthy before going on stage.

	Returns:
		dict: ``{total, oldest, newest, unacknowledged, unacknowledgedLast24h}``,
		or None if the query returned nothing.
	"""
	since = system.date.addHours(system.date.now(), -24)
	rows = _runNamed('SelectStatus', {'since': since})
	if rows.getRowCount() == 0:
		return None
	return {
		'total': rows.getValueAt(0, 'total'),
		'oldest': rows.getValueAt(0, 'oldest'),
		'newest': rows.getValueAt(0, 'newest'),
		'unacknowledged': rows.getValueAt(0, 'unacknowledged'),
		'unacknowledgedLast24h': rows.getValueAt(0, 'unacknowledged_last_24h'),
	}
