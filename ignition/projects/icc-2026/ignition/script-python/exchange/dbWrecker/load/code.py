"""Workloads behind the DB Wrecker page (views/Exchange/DB Wrecker/Query Load).

The page exists to put visible load on the database so the Gateway's
diagnostics pages have something to show. Each button is a single call into
this module; results land in ``view.custom.result`` (``data`` feeds the table,
``status`` the header line) and the concurrency input is bound to
``view.custom.concurrentCount``.
"""

import sys

logger = system.util.getLogger("exchange.dbWrecker.script.load.Workload")

QUERY_PATH = "Exchange/DbWrecker/HeavyQuery"

# The Launch button fans out this many async calls at most -- enough to show
# up in diagnostics, not enough to exhaust the connection pool.
MAX_CONCURRENT = 20
DEFAULT_CONCURRENT = 5


def runHeavyQuery(times=1):
	"""Run the slow query one or more times in sequence and time it.

	Args:
		times (int): How many sequential runs. The table shows the last result.

	Returns:
		dict: ``data`` (Dataset, or an empty list on failure) and ``status``
		(str) for the header line.

		Example: {"data": <Dataset 5000R x 3C>, "status": "Completed one slow query | 5000 rows | 2104ms"}
	"""
	times = max(1, int(times or 1))
	start = system.date.now()
	data = None
	try:
		for index in range(times):
			data = system.db.runNamedQuery(QUERY_PATH)
	except:
		error = sys.exc_info()[1]
		logger.warn("Heavy query failed: %s" % error)
		return {"data": [], "status": "Query failed: %s" % error}

	elapsed = system.date.millisBetween(start, system.date.now())
	if times == 1:
		status = "Completed one slow query | %s rows | %sms" % (data.getRowCount(), elapsed)
	else:
		status = "Completed %s sequential slow queries | last result %s rows | %sms" % (times, data.getRowCount(), elapsed)
	return {"data": data, "status": status}


def _runDetached(index):
	"""Run the slow query once on an async thread, logging rather than raising.

	Args:
		index (int): Which call of the burst this is, for the log.
	"""
	try:
		system.db.runNamedQuery(QUERY_PATH)
	except:
		logger.warn("Concurrent heavy query #%s failed: %s" % (index + 1, sys.exc_info()[1]))


def launchConcurrent(count=DEFAULT_CONCURRENT):
	"""Fire the slow query on several async threads at once and return at once.

	Args:
		count (int): How many concurrent calls. Clamped to 1..MAX_CONCURRENT.

	Returns:
		str: A status line for the page.

		Example: "Launched 5 concurrent async dbwrecker calls. Check Gateway diagnostics now."
	"""
	if count is None:
		count = DEFAULT_CONCURRENT
	count = max(1, min(int(count), MAX_CONCURRENT))
	for index in range(count):
		# Named threads so each call is findable in the Gateway's thread list
		system.util.invokeAsynchronous(_runDetached, [index], {}, "Diagnostics Demo - dbwrecker slow DB call #%s" % (index + 1))
	return "Launched %s concurrent async dbwrecker calls. Check Gateway diagnostics now." % count
