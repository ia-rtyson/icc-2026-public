"""Stage dispatcher for the Submitted -> Validate -> Implement -> Completed pipeline.

A YouTrack workflow fires an HTTP call at the ``issue-stage`` WebDev endpoint
whenever a card's ``Stage`` changes. That endpoint hands off to :func:`dispatch`,
which invokes the agent that owns the new column.

**This module never talks to YouTrack.** It knows only an issue id and a stage.
Reading the ticket, posting findings and leaving the idempotency marker are all
done *by the agent* through its ``youtrack`` MCP tools. Keeping the script blind
to YouTrack is deliberate: there is exactly one credential path (the gateway's
MCP connection) and one place the ticket is read from.

Agents are invoked with ``system.ai.sendMessage(agent, prompt)`` -- a blocking
one-shot with no history threading, so each stage gets a self-contained prompt
naming the issue it must work on.
"""

import sys

COLUMNS = ["Submitted", "Validate", "Implement", "Completed"]
"""Board columns in order, including the two nobody automates. The status screen
shows all four so the shape of the pipeline is visible, not just the automated
middle."""

STAGE_AGENTS = {
	"Validate": "Validate Agent",
	"Implement": "Implement Agent",
}
"""Board column -> agent that runs when a card lands in it.

``Submitted`` and ``Completed`` are absent on purpose. ``Submitted`` is where
the Report Issue Agent *files* tickets, and ``Completed`` is terminal -- the
Implement agent moves the card there itself once its fix verifies. Both still
fire the webhook, and both are a quiet no-op rather than an error. That is also
what stops the Implement agent's own move from re-triggering it.
"""

logger = system.util.getLogger("exchange.issueReport.Pipeline")

DB = "postgres"
"""Where the activity log lives.

This is a **log**, not the ticket store -- YouTrack still owns tickets. The log
exists because the previous in-memory version kept vanishing mid-demo: the
Implement agent's own fix calls :func:`requestScan`, the scan reloads this
script module, and module-level state is wiped. The agent was erasing its own
history as a side effect of succeeding. A table survives that.
"""

_TABLE = "ex_icc_agent_activity"

PROJECT = "icc-2026"

# Named-query folder for the activity log. The DDL fallbacks below are the only
# scripted SQL left in this module; they mirror sql/007 and sql/011.
NQ = "Exchange/IssueReport/"

# Set once the DDL below has succeeded in this script lifetime. The Pipeline
# Status dock runs while hidden and polls recentActivity/activityAgents every
# 2 s per session, so without this every poll issued five DDL statements.
# sql/011_agent_activity.sql is the source of truth; this is
# only the fallback for a database that never saw the migration.
_tableReady = False


def setupActivityTable():
	"""Create the activity table if it does not exist. Idempotent.

	Runs its DDL at most once per script lifetime (see ``_tableReady``).

	Returns:
		bool: True once the table is known to exist.
	"""
	global _tableReady
	if _tableReady:
		return True
	system.db.runUpdateQuery("""
		CREATE TABLE IF NOT EXISTS ex_icc_agent_activity (
			id            BIGSERIAL    NOT NULL,
			agent         VARCHAR(128) NOT NULL,
			stage         VARCHAR(32),
			issue         VARCHAR(32),
			event         VARCHAR(32)  NOT NULL DEFAULT 'run',
			status        VARCHAR(32)  NOT NULL DEFAULT 'running',
			started_at    TIMESTAMP    NOT NULL DEFAULT now(),
			finished_at   TIMESTAMP,
			duration_secs INTEGER,
			summary       TEXT,
			detail        TEXT,
			prompt        TEXT,
			CONSTRAINT ex_icc_agent_activity_pkey PRIMARY KEY (id)
		)""", database=DB)
	# Added after the first version shipped; harmless on a fresh table.
	try:
		system.db.runUpdateQuery(
			"ALTER TABLE ex_icc_agent_activity ADD COLUMN IF NOT EXISTS prompt TEXT", database=DB)
	except:
		# Not fatal -- logActivity still works without the column only if it is
		# never passed a prompt, so say so rather than failing silently.
		logger.warn("Could not add ex_icc_agent_activity.prompt column: %s"
		            % str(sys.exc_info()[1]))
	for ddl in (
		"CREATE INDEX IF NOT EXISTS ex_icc_agent_activity_agent_idx ON ex_icc_agent_activity (agent)",
		"CREATE INDEX IF NOT EXISTS ex_icc_agent_activity_started_idx ON ex_icc_agent_activity (started_at DESC)",
		"CREATE INDEX IF NOT EXISTS ex_icc_agent_activity_issue_idx ON ex_icc_agent_activity (issue)",
	):
		system.db.runUpdateQuery(ddl, database=DB)
	_tableReady = True
	return True


def logActivity(agent, stage=None, issue=None, event="run", status="running",
                summary=None, detail=None, prompt=None):
	"""Open an activity row and return its id.

	Never raises: a logging failure must not take down a dispatch. On failure it
	logs and returns None, and the callers below treat a None id as "not logged".
	"""
	try:
		setupActivityTable()
		activityId = system.db.runNamedQuery(PROJECT, NQ + "InsertActivity", {
			"agent": agent, "stage": stage, "issue": issue, "event": event,
			"status": status, "summary": summary, "detail": detail, "prompt": prompt,
		}, getKey=True)
		return int(activityId)
	except:
		e = sys.exc_info()[1]
		logger.error("Could not write activity row: %s" % str(e))
		return None


def finishActivity(activityId, status, summary=None, detail=None):
	"""Close an activity row, stamping the finish time and duration."""
	if activityId is None:
		return False
	try:
		system.db.runNamedQuery(PROJECT, NQ + "FinishActivity", {
			"id": int(activityId), "status": status, "summary": summary, "detail": detail,
		})
		return True
	except:
		e = sys.exc_info()[1]
		logger.error("Could not close activity row %s: %s" % (activityId, str(e)))
		return False


def clearActivity(keepRunningSecs=1800):
	"""Empty the activity log so a demo starts on a clean board.

	Called from :func:`exchange.issueReport.report.rearmDemoFault` -- re-arming the fault is the
	start of a fresh demo cycle, and the Pipeline Status dock showing last
	month's runs above this one's is noise on stage.

	**An in-flight run is never deleted.** A row is only removed if it has
	finished, or if it claims to still be ``running`` but started longer ago
	than ``keepRunningSecs`` -- which means it is a crashed dispatch whose
	``finishActivity`` never came, not live work. Without that guard a re-arm
	landing mid-run would erase the run from the board while it was still going,
	and its ``finishActivity`` would then quietly update nothing.

	This is a log, not the ticket store: YouTrack keeps every ticket and every
	agent comment, so nothing here is the only copy of anything.

	Args:
		keepRunningSecs (int): Grace period for rows still marked ``running``.

	Returns:
		dict: ``{deleted, kept}``.
	"""
	try:
		setupActivityTable()
		grace = max(0, int(keepRunningSecs or 0))
		deleted = system.db.runNamedQuery(PROJECT, NQ + "DeleteFinishedActivity", {"graceSecs": grace})
		kept = system.db.runNamedQuery(PROJECT, NQ + "CountActivity", {}).getValueAt(0, 0)
		logger.info("Cleared the agent activity log: %s deleted, %s kept"
		            % (deleted, kept))
		return {"deleted": int(deleted or 0), "kept": int(kept or 0)}
	except:
		e = sys.exc_info()[1]
		logger.error("Could not clear activity log: %s" % str(e))
		return {"deleted": 0, "kept": None, "error": str(e)}


# ---------------------------------------------------------------------------
# Nightly demo reset -- delete every ticket in the UI project
# ---------------------------------------------------------------------------

PURGE_PROJECT = "UI"
PURGE_JOB = "youtrack_ticket_purge"
_DEFAULT_INTERNAL_URL = "http://youtrack:8080"


def _youtrackRest():
	"""``(baseUrl, token)`` for the gateway's own REST calls to YouTrack.

	Container-to-container, so this is deliberately NOT
	:func:`exchange.issueReport.report.youtrackUrl` -- that one builds a *browser-facing* URL
	from the session's gateway address and defaults to ``localhost:8089``, which
	from inside the gateway container resolves to the gateway itself.

	Returns ``(url, None)`` when no token is configured. **No token means no
	purge**: an environment that has not set ``YOUTRACK_TOKEN`` is inert rather
	than failing every ten minutes.
	"""
	base = exchange.issueReport.report._env("YOUTRACK_INTERNAL_URL") or _DEFAULT_INTERNAL_URL
	return base.rstrip("/"), exchange.issueReport.report._env("YOUTRACK_TOKEN")


# Set once the housekeeping DDL has succeeded in this script lifetime, the same
# arrangement as _tableReady above -- the ticket purge polls every 10 minutes
# and has no reason to issue DDL on every tick.
_housekeepingReady = False


def _ensureHousekeepingTable():
	"""Create ex_icc_demo_housekeeping if it is missing. Mirrors sql/007_demo_housekeeping.sql.

	Runs its DDL at most once per script lifetime.

	Returns:
		bool: True once the table is known to exist.
	"""
	global _housekeepingReady
	if _housekeepingReady:
		return True
	system.db.runUpdateQuery("""
		CREATE TABLE IF NOT EXISTS ex_icc_demo_housekeeping (
			id            SERIAL      NOT NULL,
			job           VARCHAR(64) NOT NULL,
			last_run_date DATE,
			last_run_at   TIMESTAMP,
			last_result   TEXT,
			CONSTRAINT ex_icc_demo_housekeeping_pkey PRIMARY KEY (id),
			CONSTRAINT ex_icc_demo_housekeeping_job_key UNIQUE (job)
		)""", database=DB)
	_housekeepingReady = True
	return True


def purgeTickets(force=False, dryRun=False):
	"""Delete every ticket in the ``UI`` project. Once per local calendar day.

	The demo files a ticket every run, so the board accumulates near-identical
	"Drive Torque tile bound to a misspelled tag path" issues until it is more
	noise than demo. This empties it overnight, alongside the fault re-arm and
	the activity-log clear, so each day starts from nothing.

	**This is permanent.** YouTrack has no trash for issues and there is no
	delete tool in the MCP surface, so this goes through the REST API with an
	admin token. It is scoped to :data:`PURGE_PROJECT` and nothing else -- it
	queries ``project: UI`` rather than listing every issue on the server.

	Gateway event scripts have no cron, so the timer polls and this function
	owns the once-a-day decision. The "have I run today" flag lives in
	``ex_icc_demo_housekeeping`` rather than in a module global, because a project scan
	reloads this module and wipes module state -- the same thing that cost the
	activity log its history before it became a table. Firing on the first tick
	of a new local day (rather than only inside a midnight window) means a
	gateway that was switched off at midnight still resets when it comes back,
	which is what you want before a demo.

	Args:
		force (bool): Run even if it already ran today.
		dryRun (bool): Report what would be deleted; delete nothing.

	Gated by ``[default]Exchange/Demo/Control/Timers/IssueTicketPurgeEnabled`` -- the
	environment guard. It applies to a forced run too, and fails closed: an
	unreadable switch means no purge (see :mod:`exchange.demo.control`).

	Returns:
		dict: ``{action, deleted, failed, ids, ...}``. ``action`` is ``disabled``
		when the switch is off or unreadable.
	"""
	if not exchange.demo.control.timerEnabled("IssueTicketPurge"):
		return {"action": "disabled", "deleted": 0,
		        "switch": exchange.demo.control.switchPath("IssueTicketPurge")}
	base, token = _youtrackRest()
	if not token:
		logger.info("YouTrack ticket purge skipped: YOUTRACK_TOKEN is not set "
		            "in this environment, so nothing will be deleted.")
		return {"action": "no_token", "deleted": 0}

	try:
		_ensureHousekeepingTable()
		today = system.date.format(system.date.now(), "yyyy-MM-dd")
		if not force:
			ds = system.db.runNamedQuery(PROJECT, "Exchange/Demo/SelectLastRun", {"job": PURGE_JOB})
			if ds.getRowCount() > 0:
				last = ds.getValueAt(0, 0)
				if last is not None and system.date.format(last, "yyyy-MM-dd") == today:
					return {"action": "already_ran_today", "deleted": 0, "date": today}
	except:
		e = sys.exc_info()[1]
		logger.error("Ticket purge could not read its schedule: %s" % str(e))
		return {"action": "error", "deleted": 0, "error": str(e)}

	headers = {"Authorization": "Bearer %s" % token,
	           "Accept": "application/json"}
	client = system.net.httpClient()

	try:
		# Scoped to the one project on purpose -- never "every issue on the
		# server". A query, not a bare /api/issues listing.
		resp = client.get("%s/api/issues" % base,
		                  params={"query": "project: %s" % PURGE_PROJECT,
		                          "fields": "id,idReadable", "$top": "1000"},
		                  headers=headers)
		if not resp.good:
			raise IOError("listing issues returned HTTP %s: %s"
			              % (resp.statusCode, unicode(resp.text)[:300]))
		issues = resp.json or []
	except:
		e = sys.exc_info()[1]
		logger.error("Ticket purge could not list issues: %s" % str(e))
		return {"action": "error", "deleted": 0, "error": str(e)}

	readable = [i.get("idReadable") for i in issues]
	if dryRun:
		return {"action": "dry_run", "wouldDelete": len(issues), "ids": readable}

	deleted, failed = [], []
	for issue in issues:
		try:
			r = client.delete("%s/api/issues/%s" % (base, issue.get("id")),
			                  headers=headers)
			if r.good or r.statusCode == 404:
				deleted.append(issue.get("idReadable"))
			else:
				failed.append({"id": issue.get("idReadable"),
				               "status": r.statusCode,
				               "body": unicode(r.text)[:200]})
		except:
			e = sys.exc_info()[1]
			failed.append({"id": issue.get("idReadable"), "error": str(e)})

	summary = "%d deleted, %d failed" % (len(deleted), len(failed))
	logger.info("Purged YouTrack project %s: %s" % (PURGE_PROJECT, summary))

	try:
		system.db.runNamedQuery(PROJECT, "Exchange/Demo/StampRun",
		                        {"job": PURGE_JOB, "result": summary})
	except:
		e = sys.exc_info()[1]
		# A stamping failure only risks a second run, which deletes nothing new.
		logger.warn("Ticket purge ran but could not stamp its schedule: %s" % str(e))

	return {"action": "purged", "deleted": len(deleted), "failed": len(failed),
	        "ids": deleted, "failures": failed}


def _rows(ds):
	out = []
	if ds is None:
		return out
	cols = list(ds.getColumnNames())
	for r in range(ds.getRowCount()):
		row = {}
		for c in cols:
			v = ds.getValueAt(r, c)
			if v is not None and hasattr(v, "getTime") and not hasattr(v, "keySet"):
				v = system.date.format(v, "yyyy-MM-dd HH:mm:ss")
			row[c] = v
		out.append(row)
	return out


def recentActivity(agent=None, limit=100):
	"""Activity rows, newest first, optionally for one agent.

	Args:
		agent (str): Agent name. ``None`` or ``"All"`` returns every agent.
		limit (int): Row cap.
	"""
	limit = max(1, min(int(limit or 100), 500))
	try:
		setupActivityTable()
		# An empty agent means every agent -- see Exchange/IssueReport/SelectRecentActivity
		name = unicode(agent or "").strip()
		if name == "All":
			name = ""
		ds = system.db.runNamedQuery(PROJECT, NQ + "SelectRecentActivity",
		                             {"agent": name, "maxRows": limit})
		return _rows(ds)
	except:
		e = sys.exc_info()[1]
		logger.error("Could not read activity: %s" % str(e))
		return []


def activityAgents():
	"""Every agent that has ever logged, for the status screen's filter."""
	try:
		setupActivityTable()
		ds = system.db.runNamedQuery(PROJECT, NQ + "SelectActivityAgents", {})
		names = [r["agent"] for r in _rows(ds)]
	except:
		e = sys.exc_info()[1]
		logger.error("Could not list activity agents: %s" % str(e))
		names = []
	# Always offer the agents this pipeline can dispatch, even before their first run.
	for a in sorted(set(STAGE_AGENTS.values())):
		if a not in names:
			names.append(a)
	return ["All"] + names


def statusSnapshot(limit=100, agent=None):
	"""Everything the pipeline status screen needs, in one call.

	Args:
		limit (int): Activity row cap.
		agent (str): Restrict activity to one agent. ``None``/``"All"`` = every agent.

	Returns:
		dict: ``{stages, activity, agents, filter, summary, checkedAt}``. ``stages`` is one row per
		board column with the agent that owns it and whether that agent is
		actually registered on the gateway -- a misnamed agent is otherwise
		invisible until a card is moved and nothing happens.
	"""
	try:
		registered = set(a.get("name") for a in listAgents())
	except:
		e = sys.exc_info()[1]
		logger.warn("Could not list agents: %s" % str(e))
		registered = None

	stages = []
	for column in COLUMNS:
		# Deliberately not named `agent` -- that would shadow the filter argument
		# and every call would silently fall back to the last column's owner.
		owner = STAGE_AGENTS.get(column)
		stages.append({
			"stage": column,
			"agent": owner or "-",
			"automated": owner is not None,
			"registered": (owner in registered) if (owner and registered is not None) else None,
		})

	activity = recentActivity(agent, limit)
	summary = {"running": 0, "ok": 0, "error": 0}
	for r in activity:
		key = r.get("status") or "error"
		summary[key] = summary.get(key, 0) + 1

	return {
		"stages": stages,
		"activity": activity,
		"agents": activityAgents(),
		"filter": agent or "All",
		"summary": summary,
		"checkedAt": system.date.format(system.date.now(), "HH:mm:ss"),
	}


def listAgents():
	"""Diagnostic: every agent registered on the gateway.

	Use this to confirm an agent name in :data:`STAGE_AGENTS` actually resolves
	before blaming the webhook.
	"""
	return [dict(a) for a in system.ai.listAgents()]


def requestScan():
	"""Ask the gateway to re-read project resources from disk.

	A tool that edits ``view.json`` has changed a file the gateway already holds
	in memory; without a scan the running project keeps serving the old
	resource, and the Implement stage looks like it did nothing.
	"""
	from com.inductiveautomation.ignition.gateway import IgnitionGateway
	IgnitionGateway.get().getProjectManager().requestScan()
	return {"scanned": True}


def _prompt(stage, issueId):
	"""Build the one-shot prompt for a stage.

	Deliberately terse: the agent's own system prompt carries the method. All
	this has to do is name the ticket and the trigger, so the agent cannot
	confuse which card it was woken for.
	"""
	if stage == "Validate":
		return (
			"Ticket %s has just been moved into the Validate column.\n\n"
			"Validate the research recorded on that ticket against the live gateway: confirm "
			"the view, the component and the binding still look the way the ticket claims, and "
			"confirm the stated root cause actually holds right now. Then post your verdict as "
			"a comment on %s."
		) % (issueId, issueId)
	if stage == "Implement":
		return (
			"Ticket %s has just been moved into the Implement column.\n\n"
			"Apply the fix described on that ticket, then verify it took effect and post what "
			"you changed as a comment on %s."
		) % (issueId, issueId)
	raise ValueError("No prompt defined for stage '%s'" % stage)


def _firstLine(text):
	for line in unicode(text or "").splitlines():
		line = line.strip()
		if line:
			return line[:200]
	return None


_VERDICTS = ("CONFIRMED WITH CORRECTIONS", "CONFIRMED", "CANNOT REPRODUCE",
             "INSUFFICIENT INFORMATION", "NOT APPLIED", "APPLIED")


def _verdict(reply):
	"""Pull the agent's verdict keyword out of its reply for the summary column.

	The agents are told to open with one of these, so a scan is enough and no
	parsing of their prose is needed. Falls back to the first non-empty line.
	"""
	head = unicode(reply or "")[:600].upper()
	for v in _VERDICTS:
		if v in head:
			return v
	return _firstLine(reply)


def dispatch(issueId, stage):
	"""Run the agent that owns ``stage`` against ``issueId``.

	Blocking -- the caller decides whether to run it on a background thread. The
	WebDev endpoint does, because an agent turn easily outlives a webhook's
	patience.

	Args:
		issueId (str): Readable YouTrack id, e.g. ``UI-4``.
		stage (str): The column the card landed in.

	Returns:
		dict: ``{status, issue, stage, agent, reply}``. ``status`` is ``ignored``
		for a stage with no agent -- not an error, since ``Submitted`` fires a
		webhook too.
	"""
	issueId = unicode(issueId or "").strip()
	stage = unicode(stage or "").strip()
	if not issueId:
		raise ValueError("issueId is required")

	agent = STAGE_AGENTS.get(stage)
	if agent is None:
		logger.debug("No agent owns stage '%s' (issue %s) -- ignoring" % (stage, issueId))
		return {"status": "ignored", "issue": issueId, "stage": stage,
		        "reason": "No agent is bound to that column."}

	logger.info("Dispatching %s -> %s" % (issueId, agent))
	prompt = _prompt(stage, issueId)
	activityId = logActivity(agent, stage=stage, issue=issueId, status="running",
	                         summary="Dispatched for %s" % stage, prompt=prompt)
	try:
		reply = system.ai.sendMessage(agent=agent, prompt=prompt)
	except:
		e = sys.exc_info()[1]
		logger.error("Agent '%s' failed on %s: %s" % (agent, issueId, str(e)))
		finishActivity(activityId, "error",
		               summary=_firstLine(str(e)) or "Agent failed",
		               detail=str(e))
		return {"status": "error", "issue": issueId, "stage": stage,
		        "agent": agent, "error": str(e)}

	logger.info("%s finished %s" % (agent, issueId))
	# detail holds the agent's *final reply*, kept in full. Note that is a summary
	# by nature: the substance of a run goes into the YouTrack comment, and the
	# individual tool calls are inside the AI module where scripting cannot see
	# them. So this log answers "did it run, how long, what did it conclude" --
	# for the reasoning, read the ticket.
	finishActivity(activityId, "ok",
	               summary=_verdict(reply) or "Completed",
	               detail=reply)
	return {"status": "ok", "issue": issueId, "stage": stage,
	        "agent": agent, "reply": reply}


def dispatchAsync(issueId, stage):
	"""Fire :func:`dispatch` on a background thread and return immediately.

	The webhook only needs to know the work was accepted; an agent turn can run
	for minutes, and YouTrack should not be held open for it.
	"""
	def run():
		try:
			dispatch(issueId, stage)
		except:
			e = sys.exc_info()[1]
			logger.error("Async dispatch failed for %s/%s: %s" % (issueId, stage, str(e)))

	system.util.invokeAsynchronous(run)
	return {"status": "accepted", "issue": issueId, "stage": stage,
	        "agent": STAGE_AGENTS.get(unicode(stage or "").strip())}
