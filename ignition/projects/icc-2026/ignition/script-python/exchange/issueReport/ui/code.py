"""View-facing logic for the Report Issue Agent's Perspective views.

``exchange.issueReport.report`` captures context and ``exchange.issueReport.pipeline`` reads the pipeline; this
module is the thin layer the views call -- the Line Overview's Report an Issue
button, the Pipeline Status dock's polling binding and the Report Chat dock's
captured-context rows -- so none of that logic lives in a view.
"""

import sys

import exchange.issueReport.pipeline
import exchange.issueReport.report

logger = system.util.getLogger("exchange.issueReport.script.ui.Views")

REPORT_DOCK_ID = "issue-report"

# Rows the Pipeline Status dock asks for, and how much of an agent's outcome
# text the activity table shows before clamping.
ACTIVITY_LIMIT = 200
SUMMARY_CHARS = 150

# Suspect components listed on the Report Chat dock before "+N more".
MAX_SUSPECTS = 5


def _plain(value):
	"""Convert a Perspective property value into plain Python lists and dicts.

	Args:
		value (object): A property-tree wrapper, a Java map/list, or plain data.

	Returns:
		object: The same data as plain lists, dicts and scalars.
	"""
	return system.util.jsonDecode(system.util.jsonEncode(value))


def openReportDock(view, session, page):
	"""Capture the screen's context and open the Report an Issue chat dock.

	A dock, not a popup: a popup re-focuses its own root on every re-render,
	and the Line Overview updates at 1 Hz, so a chat input inside a popup loses
	focus about once a second and cannot be typed into.

	Args:
		view (object): The calling view (``self.view``), whose bindings are captured.
		session (object): ``self.session``, for the reporter's user name.
		page (object): ``self.page``, for the page URL.
	"""
	# A bare except: a missing Perspective property raises a Java error
	try:
		username = session.props.auth.user.userName
	except:
		username = None
	try:
		pageUrl = page.props.path
	except:
		pageUrl = None
	# componentPath is None on purpose: the operator only knows "this screen is
	# broken", so captureContext returns a heuristic shortlist of suspects
	context = exchange.issueReport.report.captureContext(view, componentPath=None, username=username, pageUrl=pageUrl)
	system.perspective.openDock(REPORT_DOCK_ID, params={"issue": context})


def contextRows(issue):
	"""Build the label/value rows the Report Chat dock shows for a capture.

	Args:
		issue (object): ``view.params.issue``, the dict from ``captureContext``.

	Returns:
		list: One ``{"label": str, "value": str}`` dict per row.
	"""
	if not issue:
		return [{"label": "Context", "value": "none captured"}]
	details = _plain(issue) or {}
	rows = [
		{"label": "View", "value": details.get("viewPath") or "-"},
		{"label": "Page", "value": details.get("pageUrl") or "-"},
		{"label": "Reporter", "value": details.get("reporter") or "unknown"},
		{"label": "Captured", "value": details.get("capturedAt") or "-"},
	]
	suspects = details.get("suspectComponents") or []
	if not suspects:
		rows.append({"label": "Suspects", "value": "none flagged"})
		return rows
	for index, suspect in enumerate(suspects[:MAX_SUSPECTS]):
		rows.append({
			"label": "Suspect %d" % (index + 1) if index else "Suspects",
			"value": u"%s  \u2192  %s  (%s)" % (suspect.get("component"), suspect.get("prop"), suspect.get("bindingType")),
		})
	if len(suspects) > MAX_SUSPECTS:
		rows.append({"label": "", "value": "+%d more" % (len(suspects) - MAX_SUSPECTS)})
	return rows


def pipelineStatus(agentFilter="All"):
	"""Snapshot the issue pipeline for the Pipeline Status dock.

	Wraps ``exchange.issueReport.pipeline.statusSnapshot`` with the shaping the dock's
	components need, so they bind with plain property bindings: dropdown
	options for the agent filter, and outcome text clamped to a table-friendly
	length. Never raises -- a failure returns an empty snapshot carrying
	``error``, so the dock renders rather than going blank.

	Args:
		agentFilter (str): The agent to show activity for, or "All".

	Returns:
		dict: The snapshot plus ``agentOptions``.

		Example: {"stages": [...], "activity": [...], "agents": ["All"], "agentOptions": [{"label": "All", "value": "All"}],
		"filter": "All", "summary": {"running": 0, "ok": 3, "error": 0}, "checkedAt": "10:00:02"}
	"""
	agent = unicode(agentFilter or "All") or "All"
	try:
		snapshot = exchange.issueReport.pipeline.statusSnapshot(ACTIVITY_LIMIT, agent)
	except:
		error = sys.exc_info()[1]
		logger.warn("Pipeline status snapshot failed: %s" % error)
		snapshot = {
			"stages": [], "activity": [], "agents": ["All"], "filter": agent,
			"summary": {"running": 0, "ok": 0, "error": 0},
			"checkedAt": "unavailable", "error": unicode(error),
		}

	# The table sizes rows to their content, so a paragraph-long outcome would
	# swallow the viewport; clamp here, since a CSS line-clamp hides the text
	# without shrinking the measured row. The full text is on the ticket.
	activity = _plain(snapshot.get("activity") or [])
	for row in activity:
		text = row.get("summary")
		if text and len(text) > SUMMARY_CHARS:
			row["summary"] = text[:SUMMARY_CHARS].rstrip() + u"\u2026"
	snapshot["activity"] = activity
	snapshot["stages"] = _plain(snapshot.get("stages") or [])

	names = snapshot.get("agents") or ["All"]
	snapshot["agentOptions"] = [{"label": unicode(name), "value": unicode(name)} for name in names]
	return snapshot
