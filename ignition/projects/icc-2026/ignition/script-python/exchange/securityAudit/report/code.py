"""Assemble, score and persist a full gateway security audit.

``runAudit()`` is the one entry point worth remembering. Everything else here
either shapes its output for a particular consumer (the agent, the Perspective
page, the database) or trims it, because a full audit structure is far larger
than an LLM context should be asked to carry.

The trimming matters. Handing a model the entire inventory -- every user, every
page, every tool -- and asking it to find problems produces confident summaries
of whatever happened to fit. Instead the deterministic code does the finding,
and the model receives findings plus the inventory slices they cite. What it is
being asked for is judgement about priority and phrasing, not detection.
"""

import os

import exchange.securityAudit.core as core
import exchange.securityAudit.gateway as gw
import exchange.securityAudit.matrix as matrixmod
import exchange.securityAudit.pages as pagesmod
import exchange.securityAudit.resources as resmod
import exchange.securityAudit.users as usersmod

logger = system.util.getLogger("exchange.securityAudit.Report")

DB = "postgres"

# The project that owns the Exchange/SecurityAudit/ named queries -- this project, not
# the project under audit, which runAudit takes as an argument
_PROJECT = "icc-2026"


def knownProjects():
	"""Project names actually present on this gateway."""
	root = os.path.join(core.dataDir(), "projects")
	return [n for n in core.listDirs(root) if not n.startswith(".")]


def runAudit(project=None):
	"""Run every domain and return the complete audit structure."""
	project = project or core.PROJECT

	userInv = usersmod.inventory()
	gwInv = gw.inventory()
	pageInv = pagesmod.pageInventory(project)
	resInv = resmod.inventory(project)

	levels = [lv["path"] for lv in gwInv["securityLevels"]]

	findings = []
	findings.extend(usersmod.audit(userInv))
	findings.extend(gw.audit(gwInv))
	findings.extend(pagesmod.audit(pageInv, knownLevels=levels))
	findings.extend(resmod.audit(resInv, knownProjects=knownProjects()))
	findings = core.sortFindings(findings)

	m = matrixmod.build(project)

	return {
		"project": project,
		"generatedAt": unicode(system.date.format(system.date.now(),
		                                          "yyyy-MM-dd HH:mm:ss")),
		"score": core.postureScore(findings),
		"counts": core.countBySeverity(findings),
		"findingCount": len(findings),
		"findings": findings,
		"inventory": {
			"users": userInv,
			"gateway": gwInv,
			"pages": pageInv,
			"resources": resInv,
		},
		"matrix": m,
	}


# --------------------------------------------------------- agent-facing view

def _trimInventory(audit):
	"""The inventory an agent needs, without the volume it does not.

	Drops the raw config blobs (security zone configs, full IdP attribute
	mappers, per-tool write markers) and keeps the shape a report is written
	from. This is the difference between a tool response the model reads and one
	it summarises.
	"""
	inv = audit["inventory"]

	users = []
	for src in inv["users"]["sources"]:
		for u in src["users"]:
			users.append({
				"source": src["name"],
				"username": u["username"],
				"name": ("%s %s" % (u["firstName"], u["lastName"])).strip(),
				"roles": u["roles"],
				"schedule": u["schedule"],
				"passwordAgeDays": u["passwordAgeDays"],
				"contactCount": u["contactCount"],
			})

	pages = []
	for p in inv["pages"]["pages"]:
		pages.append({
			"url": p["url"],
			"title": p["title"],
			"viewPath": p["viewPath"],
			"requires": p["declaredLevels"],
			"protection": p["protection"],
			"hostsAiChat": bool(p["sensitiveComponents"]),
		})

	agents = []
	for a in inv["resources"]["aiAgents"]:
		agents.append({
			"name": a["name"],
			"model": a["model"],
			"requires": a["permissionLevels"],
			"toolCount": len(a["tools"]),
		})

	endpoints = []
	for e in inv["resources"]["webdevEndpoints"]:
		endpoints.append({
			"name": e["name"],
			"openVerbs": e["openVerbs"],
		})

	return {
		"users": users,
		"roles": sorted(set([r for s in inv["users"]["sources"] for r in s["roles"]])),
		"userSources": [s["name"] for s in inv["users"]["sources"]],
		"securityLevels": [lv["path"] for lv in inv["gateway"]["securityLevels"]],
		"identityProviders": [{"name": i["name"], "type": i["type"],
		                       "userSource": i["userSource"],
		                       "ruleCount": i["ruleCount"]}
		                      for i in inv["gateway"]["identityProviders"]],
		"securityProperties": inv["gateway"]["securityProperties"],
		"pages": pages,
		"aiAgents": agents,
		"mcpServers": [{"name": s["name"], "wildcards": s["wildcards"],
		                "requires": s["permissionLevels"]}
		               for s in inv["resources"]["mcpServers"]],
		"webdevEndpoints": endpoints,
	}


def forAgent(project=None, domain=None):
	"""The audit shaped for an agent tool response.

	domain optionally narrows to one of users|gateway|pages|resources, so a
	follow-up question ("which pages are unprotected?") does not re-send the
	whole audit.
	"""
	audit = runAudit(project)
	findings = audit["findings"]
	if domain:
		findings = [f for f in findings if f["domain"] == domain]

	return {
		"generatedAt": audit["generatedAt"],
		"project": audit["project"],
		"postureScore": audit["score"],
		"scoreNote": ("0-100, computed by this audit from its own severity "
		              "weights. It is a presentation aid, not a compliance "
		              "rating -- quote it alongside the counts, not instead."),
		"counts": audit["counts"],
		"domain": domain or "all",
		"findings": findings,
		"inventory": _trimInventory(audit),
		"accessMatrixMarkdown": matrixmod.toMarkdown(audit["matrix"]),
	}


# ------------------------------------------------------------- persistence

# Set once the CREATE TABLE has succeeded in this script lifetime. Perspective
# polls this module every few seconds through a runScript binding, and issuing
# DDL on every poll fills the gateway log with noise for no benefit.
_tableReady = False

def _ensureTable():
	"""Create the audit history table if it is absent.

	Mirrors sql/002_security_audit.sql, which postgres-init replays on every
	``docker compose up``. This is the idempotent fallback for a database that
	never saw the migration,
	the same arrangement exchange.alarmFlood.data.setupTables() uses.
	"""
	global _tableReady
	if _tableReady:
		return
	system.db.runUpdateQuery("""
		CREATE TABLE IF NOT EXISTS ex_icc_security_audit_report (
			id            SERIAL      NOT NULL,
			generated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
			project       TEXT        NOT NULL,
			score         INTEGER     NOT NULL,
			finding_count INTEGER     NOT NULL,
			critical      INTEGER     NOT NULL DEFAULT 0,
			high          INTEGER     NOT NULL DEFAULT 0,
			medium        INTEGER     NOT NULL DEFAULT 0,
			low           INTEGER     NOT NULL DEFAULT 0,
			findings_json JSONB,
			inventory_json JSONB,
			markdown      TEXT,
			CONSTRAINT ex_icc_security_audit_report_pkey PRIMARY KEY (id)
		)
	""", DB)
	_tableReady = True


def saveReport(audit=None, markdown=None):
	"""Persist one audit run. Returns the new report's id.

	Stored so two runs can be diffed -- "what changed since last week" is the
	question a security report gets asked second, and it cannot be answered
	from a chat transcript.
	"""
	audit = audit or runAudit()
	_ensureTable()
	counts = audit["counts"]
	reportId = int(system.db.runNamedQuery(_PROJECT, "Exchange/SecurityAudit/InsertReport", {
		"project": audit["project"],
		"score": int(audit["score"]),
		"findingCount": int(audit["findingCount"]),
		"critical": int(counts["CRITICAL"]),
		"high": int(counts["HIGH"]),
		"medium": int(counts["MEDIUM"]),
		"low": int(counts["LOW"]),
		"findingsJson": system.util.jsonEncode(audit["findings"]),
		"inventoryJson": system.util.jsonEncode(_trimInventory(audit)),
		"markdown": unicode(markdown or ""),
	}, getKey=True))
	logger.info("Saved security audit report %d (score %d, %d findings)"
	            % (reportId, audit["score"], audit["findingCount"]))
	return reportId


def latestReport():
	"""The most recent stored report as a dict, or None."""
	_ensureTable()
	ds = system.db.runNamedQuery(_PROJECT, "Exchange/SecurityAudit/SelectLatestReport", {})
	if ds.getRowCount() == 0:
		return None
	return {
		"reportId": int(ds.getValueAt(0, "id")),
		"generatedAt": unicode(ds.getValueAt(0, "generated_at")),
		"project": unicode(ds.getValueAt(0, "project")),
		"score": int(ds.getValueAt(0, "score")),
		"findingCount": int(ds.getValueAt(0, "finding_count")),
		"critical": int(ds.getValueAt(0, "critical")),
		"high": int(ds.getValueAt(0, "high")),
		"medium": int(ds.getValueAt(0, "medium")),
		"low": int(ds.getValueAt(0, "low")),
	}


def compareToPrevious():
	"""Findings added and cleared since the previous stored report."""
	_ensureTable()
	ds = system.db.runNamedQuery(_PROJECT, "Exchange/SecurityAudit/SelectLastTwoReportFindings", {})
	if ds.getRowCount() < 2:
		return {"comparable": False,
		        "reason": "Fewer than two audit reports have been stored."}

	def keys(rowIdx):
		raw = unicode(ds.getValueAt(rowIdx, "findings_json") or "[]")
		out = {}
		for f in system.util.jsonDecode(raw) or []:
			out["%s|%s" % (f.get("id"), f.get("title"))] = f
		return out

	newer = keys(0)
	older = keys(1)
	added = [newer[k] for k in newer if k not in older]
	cleared = [older[k] for k in older if k not in newer]
	return {
		"comparable": True,
		"newerReportId": int(ds.getValueAt(0, "id")),
		"olderReportId": int(ds.getValueAt(1, "id")),
		"added": core.sortFindings(added),
		"cleared": core.sortFindings(cleared),
	}


def statusLine():
	"""One line of audit status for the Security Audit page header.

	Returned as a formatted string rather than a structure because it feeds a
	label's text through a runScript expression binding, and doing the
	formatting here keeps the presentation out of the binding where it cannot
	be tested.
	"""
	try:
		latest = latestReport()
	except Exception, e:
		logger.warn("statusLine could not read the report table: %s" % e)
		return "Audit history unavailable (%s)" % e
	if latest is None:
		return "No audit has been saved yet. Ask the agent to run one."
	return ("Last assessed %s  |  score %d/100  |  %d critical, %d high, "
	        "%d medium, %d low"
	        % (latest["generatedAt"][:16], latest["score"], latest["critical"],
	           latest["high"], latest["medium"], latest["low"]))
