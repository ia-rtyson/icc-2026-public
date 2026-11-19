"""Logic behind the Designer Embeds demo page (views/Exchange/Designer Embeds/Example).

The page is a filter panel over the ``Exchange/DesignerEmbeds/SelectEquipmentEvents`` named
query. Every filter input is bidirectionally bound to ``view.custom.filters``
and the Run Query button is a single call into this module, whose result lands
in ``view.custom.result`` -- the table and the status line bind to that. No
component reaches into another component's props.
"""

import sys

logger = system.util.getLogger("exchange.designerEmbeds.script.query.EquipmentEvents")

QUERY_PATH = "Exchange/DesignerEmbeds/SelectEquipmentEvents"

# Used whenever a filter input is empty -- a cleared numeric field reads None.
DEFAULT_LAST_HOURS = 24
DEFAULT_MIN_SEVERITY = 0
DEFAULT_ROW_LIMIT = 100
MAX_ROW_LIMIT = 1000


def _read(obj, key, default=None):
	"""Read one key off a Perspective object property or a plain dict.

	Args:
		obj (object): A property-tree object wrapper or a dict.
		key (str): The key to read.
		default (object): Returned when the key is missing or None.

	Returns:
		object: The value, or default.
	"""
	# A property-tree wrapper supports item access but not always .get()
	try:
		value = obj[key]
	except:
		value = None
	return default if value is None else value


def queryEquipmentEvents(filters):
	"""Run the equipment-events query for the page's filter panel.

	Args:
		filters (object): ``view.custom.filters`` -- keys ``area`` (str),
			``lastHours`` (number), ``minSeverity`` (number), ``acknowledged``
			(bool) and ``rowLimit`` (number).

	Returns:
		dict: ``data`` (Dataset, or an empty list on failure) and ``status``
		(str) for the status line.

		Example: {"data": <Dataset 9R x 8C>, "status": "Loaded 9 rows | 2026-09-30 10:00:00"}
	"""
	lastHours = int(_read(filters, "lastHours", DEFAULT_LAST_HOURS))
	minSeverity = int(_read(filters, "minSeverity", DEFAULT_MIN_SEVERITY))
	rowLimit = int(_read(filters, "rowLimit", DEFAULT_ROW_LIMIT))
	# Bound the result set at the point of call, whatever the field says
	rowLimit = max(1, min(rowLimit, MAX_ROW_LIMIT))

	now = system.date.now()
	# startTime/endTime are DateTime parameters, so pass date objects: epoch
	# millis were coerced to a timestamp and then broke SQL that divided by 1000
	parameters = {
		"area": _read(filters, "area", ""),
		"startTime": system.date.addHours(now, -lastHours),
		"endTime": now,
		"minSeverity": minSeverity,
		"acknowledged": 1 if _read(filters, "acknowledged", False) else 0,
		"rowLimit": rowLimit,
	}

	try:
		data = system.db.runNamedQuery(QUERY_PATH, parameters)
	except:
		error = sys.exc_info()[1]
		logger.warn("Equipment events query failed: %s" % error)
		return {"data": [], "status": "Query failed: %s" % error}

	return {
		"data": data,
		"status": "Loaded %s rows | %s" % (data.getRowCount(), system.date.format(now, "yyyy-MM-dd HH:mm:ss")),
	}
