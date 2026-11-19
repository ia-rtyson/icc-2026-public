"""Shared plumbing for the Security Audit Agent.

Everything the audit reads comes from one of two places:

* the live gateway scripting APIs (``system.user.*``), which are authoritative
  for users and roles but expose essentially nothing about *configuration*; and
* the gateway's own resource files on disk under ``data/config`` and
  ``data/projects``, which are authoritative for everything else.

Reading configuration off disk rather than through an API is deliberate, not a
shortcut. Ignition 8.3 stores every gateway config resource as JSON in a
well-known tree, and there is no scripting API that exposes -- for one concrete
example -- an AI agent's ``permissions`` block. Reading the file is the only way
to audit it, and it has the useful property that every finding can cite the
exact file it came from, which the agent's system prompt requires it to do.

Nothing in this package writes. The audit is report-only: each finding carries
a suggested fix as text, and applying it is left to a human.
"""

import os

logger = system.util.getLogger("exchange.securityAudit.Core")

PROJECT = "icc-2026"

# Severity ordering, worst first. The agent is told to use exactly these names.
SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]

# Weight per severity, used to turn a finding list into a single 0-100 posture
# score. The weights are deliberately steep: one CRITICAL should dominate a pile
# of LOWs, because that is how a real auditor reads a report.
_SEVERITY_WEIGHT = {
	"CRITICAL": 40,
	"HIGH": 15,
	"MEDIUM": 5,
	"LOW": 2,
	"INFO": 0,
}


# ---------------------------------------------------------------- filesystem

def dataDir():
	"""Absolute path of the gateway's data directory.

	Asked of the running gateway rather than hardcoded, so this still works if
	the stack is ever run from something other than the standard container
	image (where it is /usr/local/bin/ignition/data).
	"""
	from com.inductiveautomation.ignition.gateway import IgnitionGateway
	ctx = IgnitionGateway.get()
	return str(ctx.getSystemManager().getDataDir().getAbsolutePath())


def configRoot():
	"""Root of the gateway config resource tree (data/config/resources/core)."""
	return os.path.join(dataDir(), "config", "resources", "core")


def projectRoot(project=None):
	"""Root of one project's resource tree (data/projects/<project>)."""
	return os.path.join(dataDir(), "projects", project or PROJECT)


def rel(path):
	"""Shorten an absolute gateway path to something quotable in a report.

	Findings cite sources, and citing an 80-character container path in every
	row makes the report unreadable. This trims the data-dir prefix so the
	citation matches what the user sees in the git repo.
	"""
	d = dataDir()
	if path and path.startswith(d):
		return path[len(d):].lstrip("/\\").replace("\\", "/")
	return path


def readText(path):
	"""Read a file, or return None if it is missing or unreadable.

	Returns None rather than raising: an audit that dies because one optional
	resource is absent is worse than an audit that reports the gap.
	"""
	try:
		if not os.path.isfile(path):
			return None
		return system.file.readFileAsString(path, "UTF-8")
	except Exception, e:
		logger.warn("Could not read %s: %s" % (path, e))
		return None


def readJson(path):
	"""Read and decode a JSON resource file. None if absent or malformed."""
	txt = readText(path)
	if txt is None:
		return None
	try:
		return system.util.jsonDecode(txt)
	except Exception, e:
		logger.warn("Malformed JSON at %s: %s" % (path, e))
		return None


def listDirs(path):
	"""Sorted names of the immediate subdirectories of path ([] if absent)."""
	try:
		if not os.path.isdir(path):
			return []
		return sorted([n for n in os.listdir(path)
		               if os.path.isdir(os.path.join(path, n))])
	except Exception, e:
		logger.warn("Could not list %s: %s" % (path, e))
		return []


def findResourceDirs(root, marker="resource.json"):
	"""Every directory under root that contains ``marker``, depth-first.

	Ignition nests resources arbitrarily deep and names the folders after the
	resource (``agent/Tag Import Agent/``, ``views/A/B/C/``), so the only
	reliable way to enumerate them is to walk for the marker file.
	"""
	out = []
	if not os.path.isdir(root):
		return out
	for dirpath, dirnames, filenames in os.walk(root):
		if marker in filenames:
			out.append(dirpath)
	return sorted(out)


# ------------------------------------------------------------------ findings

def finding(fid, severity, domain, title, detail, source, remediation,
            evidence=None):
	"""Build one finding.

	Every field is mandatory except ``evidence`` because the agent's report
	format has a column for each of them -- a finding missing its ``source``
	cannot be cited, and the system prompt forbids uncited findings.

	fid         short stable id, e.g. "U001". Stable across runs so two audits
	            can be diffed.
	severity    one of SEVERITIES.
	domain      "users" | "gateway" | "pages" | "resources".
	source      the config file or API call the finding was read from.
	remediation one sentence, imperative, describing the fix.
	evidence    optional dict of the raw values behind the finding.
	"""
	if severity not in SEVERITIES:
		raise ValueError("Unknown severity '%s'" % severity)
	return {
		"id": fid,
		"severity": severity,
		"domain": domain,
		"title": title,
		"detail": detail,
		"source": source,
		"remediation": remediation,
		"evidence": evidence or {},
	}


def sortFindings(findings):
	"""Worst first, then by id, so report order is stable between runs."""
	return sorted(findings, key=lambda f: (SEVERITIES.index(f["severity"]), f["id"]))


def postureScore(findings):
	"""Collapse a finding list to a 0-100 score. 100 is clean.

	This is a presentation aid, not a standard -- the weights are ours. The
	agent is told to quote the score alongside the finding counts rather than
	in place of them, so nobody mistakes it for a compliance rating.
	"""
	penalty = 0
	for f in findings:
		penalty += _SEVERITY_WEIGHT.get(f["severity"], 0)
	return max(0, 100 - penalty)


def countBySeverity(findings):
	"""{severity: count} covering every severity, including the zeroes."""
	counts = {}
	for s in SEVERITIES:
		counts[s] = 0
	for f in findings:
		counts[f["severity"]] = counts.get(f["severity"], 0) + 1
	return counts


# -------------------------------------------------------------------- dates

def parseIgnitionDate(raw):
	"""Parse Ignition's user-source date format into a java.util.Date.

	users.json stores dates as ``20250716.125712550-0600``. Only the leading
	yyyyMMdd is needed for an age-in-days calculation, and parsing just that
	avoids depending on the fractional-second precision, which has varied.
	Returns None on anything unparseable.
	"""
	if not raw:
		return None
	try:
		datePart = unicode(raw).split(".")[0]
		if len(datePart) < 8:
			return None
		return system.date.parse(datePart, "yyyyMMdd")
	except Exception:
		return None


def daysSince(raw):
	"""Whole days between an Ignition-format date string and now, or None."""
	d = parseIgnitionDate(raw)
	if d is None:
		return None
	return int(system.date.daysBetween(d, system.date.now()))
