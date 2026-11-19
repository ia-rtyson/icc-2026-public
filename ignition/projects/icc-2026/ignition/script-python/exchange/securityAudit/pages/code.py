"""Perspective page and view access.

This is the part of the audit that answers "who can open what screen", and it
is the part with the most room to be quietly wrong, so it is worth being
explicit about how it decides.

Perspective can gate a screen in more than one way, and the ways are not
equivalent:

* **Declared** -- a ``permissions`` block on the view's project resource
  (``resource.json`` -> ``attributes.permissions``) or on the view itself. This
  is configuration: it states an intent in a place the platform reads.
* **Enforced** -- a binding in the view that actually evaluates the session's
  identity and hides, disables or redirects. This is code: it runs.

A screen can have one, both, or neither, and the interesting case is the
mismatch. A view carrying a declared permission block with nothing enforcing it
reads as protected in every config review and is not protected at runtime; a
view enforced only by a ``visible`` binding is protected visually while whatever
the screen calls -- a named query, a tag write, a WebDev endpoint -- stays
reachable by anyone who knows the URL.

So this module reports the mechanism it found alongside the requirement, and
never collapses the two into a single "protected" boolean. Where it cannot
prove enforcement it says so rather than assuming.
"""

import os
import re

import exchange.securityAudit.core as core

logger = system.util.getLogger("exchange.securityAudit.Pages")

# Text that means the view is *reading* the session's identity.
#
# Reading identity is not the same as enforcing anything, and conflating the two
# is the worst bug an access audit can have -- it reports a page as protected
# when anyone can open it. Two real examples from this project:
#
#   * matching a bare "securityLevel" hit the empty permissions block inside an
#     inline ai.tools definition, marking four wide-open pages as enforced; and
#   * a page that shows the logged-in user's name in its header reads
#     session.props.auth without gating anything at all.
#
# So these markers only establish that identity was read. Whether that read
# *gates* anything is decided separately, by where the read appears.
IDENTITY_MARKERS = [
	"isAuthorized",
	"hasRole",
	"session.props.auth",
	"props.auth.authenticated",
	"props.auth.securityLevels",
	"SecurityModel.",
	"system.security.",
]

# Property-name suffixes that actually control access to something. An identity
# read inside a binding on one of these is enforcement; the same read bound to a
# label's text is a display of who you are.
GATING_PROP_SUFFIXES = [
	".visible",
	".enabled",
	".display",
	".hidden",
	".disabled",
	".readOnly",
]

# Script calls that redirect or end a session. An identity read in the same
# script as one of these is gating by navigation rather than by property.
GATING_CALLS = [
	"system.perspective.logout",
	"system.perspective.navigate",
	"system.perspective.closePage",
]

# Views hosting one of these are treated as higher-stakes than a display screen,
# because reaching them means reaching something that can act.
SENSITIVE_COMPONENT_TYPES = [
	"ia.ai.chat",
]


def _viewDir(project, viewPath):
	return os.path.join(core.projectRoot(project),
	                    "com.inductiveautomation.perspective", "views",
	                    *viewPath.split("/"))


def _permissionsFrom(obj):
	"""Pull a permissions block out of a resource.json / view.json structure.

	Returns (securityLevels, whereFound) or ([], None).
	"""
	if not isinstance(obj, dict):
		return [], None
	# Project-resource attribute form -- the shape Ignition 8.3 uses for AI tool
	# bundles and other permissioned project resources.
	attrs = obj.get("attributes") or {}
	perm = attrs.get("permissions")
	if isinstance(perm, dict) and (perm.get("securityLevels") or []):
		return perm["securityLevels"], "resource.json attributes.permissions"
	# Top-level form, if a view ever carries one directly.
	perm = obj.get("permissions")
	if isinstance(perm, dict) and (perm.get("securityLevels") or []):
		return perm["securityLevels"], "view.json permissions"
	return [], None


def _levelNames(securityLevels):
	"""Flatten a securityLevels permission list into readable level names.

	The entries are objects rather than strings, and the key naming has varied,
	so read whichever of the plausible keys is present.
	"""
	names = []
	for entry in securityLevels or []:
		if isinstance(entry, basestring):
			names.append(unicode(entry))
			continue
		if not isinstance(entry, dict):
			continue
		for key in ("name", "path", "securityLevel", "level"):
			val = entry.get(key)
			if isinstance(val, basestring) and val:
				names.append(unicode(val))
				break
	return names


def _hasIdentity(text):
	"""The identity markers present in a blob of binding or script text."""
	return [m for m in IDENTITY_MARKERS if m in text]


def _scanEnforcement(viewJson):
	"""(gatingHits, identityReads) for one view.

	Walks the component tree rather than grepping the file, because *where* an
	identity read appears is the whole question. A read inside a binding on
	props.visible gates the screen; the same read bound to a label's text just
	prints the user's name in a header.

	gatingHits    descriptions of reads that actually control access.
	identityReads descriptions of reads that do not, kept so the report can say
	              "this view knows who you are but does not act on it" instead
	              of silently discarding the evidence.
	"""
	gating = []
	reads = []

	def visit(node, path):
		if not isinstance(node, dict):
			return
		name = ((node.get("meta") or {}).get("name")) or path

		# Bindings, keyed by the property they drive.
		for propPath, cfg in (node.get("propConfig") or {}).items():
			text = system.util.jsonEncode(cfg)
			markers = _hasIdentity(text)
			if not markers:
				continue
			isGating = False
			for suffix in GATING_PROP_SUFFIXES:
				if propPath.endswith(suffix):
					isGating = True
					break
			entry = "%s -> %s (%s)" % (name, propPath, ", ".join(markers))
			if isGating:
				gating.append(entry)
			else:
				reads.append(entry)

		# Scripts and event handlers: gating by redirect rather than by property.
		for key in ("scripts", "events"):
			blob = node.get(key)
			if not blob:
				continue
			text = system.util.jsonEncode(blob)
			markers = _hasIdentity(text)
			if not markers:
				continue
			calls = [c for c in GATING_CALLS if c in text]
			entry = "%s -> %s (%s)" % (name, key, ", ".join(markers))
			if calls:
				gating.append("%s + %s" % (entry, ", ".join(calls)))
			else:
				reads.append(entry)

		for i, child in enumerate(node.get("children") or []):
			visit(child, "%s/%d" % (path, i))

	if isinstance(viewJson, dict):
		# View-level bindings live beside the root component, not inside it.
		visit({"propConfig": viewJson.get("propConfig") or {},
		       "meta": {"name": "view"}}, "view")
		visit(viewJson.get("root") or {}, "root")

	return gating, reads


def pageInventory(project=None):
	"""Every registered page URL with the protection found on its view."""
	project = project or core.PROJECT
	cfgPath = os.path.join(core.projectRoot(project),
	                       "com.inductiveautomation.perspective",
	                       "page-config", "config.json")
	cfg = core.readJson(cfgPath) or {}
	pages = cfg.get("pages") or {}

	out = []
	for url in sorted(pages.keys()):
		entry = pages[url] or {}
		viewPath = unicode(entry.get("viewPath") or "")
		vdir = _viewDir(project, viewPath) if viewPath else None

		record = {
			"url": url,
			"title": unicode(entry.get("title") or ""),
			"viewPath": viewPath,
			"viewExists": bool(vdir and os.path.isdir(vdir)),
			"declaredLevels": [],
			"declaredIn": None,
			"enforcementMarkers": [],
			"identityReads": [],
			"sensitiveComponents": [],
			"file": core.rel(cfgPath),
			"viewFile": core.rel(os.path.join(vdir, "view.json")) if vdir else None,
		}

		if record["viewExists"]:
			resJson = core.readJson(os.path.join(vdir, "resource.json"))
			viewJson = core.readJson(os.path.join(vdir, "view.json"))
			raw = core.readText(os.path.join(vdir, "view.json")) or ""

			levels, where = _permissionsFrom(resJson)
			if not levels:
				levels, where = _permissionsFrom(viewJson)
			record["declaredLevels"] = _levelNames(levels)
			record["declaredIn"] = where

			gating, reads = _scanEnforcement(viewJson)
			record["enforcementMarkers"] = gating
			record["identityReads"] = reads

			sensitive = []
			for ctype in SENSITIVE_COMPONENT_TYPES:
				if ('"%s"' % ctype) in raw:
					sensitive.append(ctype)
			record["sensitiveComponents"] = sensitive

		record["protection"] = _classify(record)
		out.append(record)

	return {"project": project, "pages": out, "file": core.rel(cfgPath)}


def _classify(record):
	"""One of: none | declared-only | enforced-only | declared-and-enforced."""
	declared = bool(record["declaredLevels"])
	enforced = bool(record["enforcementMarkers"])
	if declared and enforced:
		return "declared-and-enforced"
	if declared:
		return "declared-only"
	if enforced:
		return "enforced-only"
	return "none"


def audit(inv=None, knownLevels=None):
	"""Findings for the pages domain.

	knownLevels is the list of security-level paths that actually exist, used to
	catch a page requiring a level that was never defined.
	"""
	inv = inv or pageInventory()
	knownLevels = knownLevels or []
	out = []

	for p in inv["pages"]:
		url = p["url"]
		cite = p["viewFile"] or p["file"]

		if not p["viewExists"]:
			out.append(core.finding(
				"P004", "MEDIUM", "pages",
				"Page %s points at a view that does not exist" % url,
				"page-config maps %s to view %s, but there is no such view in "
				"the project. The URL is registered and will resolve to a "
				"broken page rather than a 404, so it is not obvious from the "
				"outside that anything is wrong." % (url, p["viewPath"]),
				p["file"],
				"Remove the page entry, or restore the missing view.",
				{"url": url, "viewPath": p["viewPath"]}))
			continue

		prot = p["protection"]

		if prot == "none":
			sev = "CRITICAL" if p["sensitiveComponents"] else "HIGH"
			extra = ""
			if p["sensitiveComponents"]:
				extra = (" This page hosts %s, so opening the URL does not just "
				         "reveal information -- it hands the visitor a working "
				         "AI agent session with whatever tools that agent is "
				         "configured to call."
				         % ", ".join(p["sensitiveComponents"]))
			knows = ""
			if p["identityReads"]:
				knows = (" The view does read the session identity (%s), but "
				         "only to display it -- none of those reads drives a "
				         "visible, enabled or navigation property, so nothing "
				         "is gated." % "; ".join(p["identityReads"][:3]))
			out.append(core.finding(
				"P001", sev, "pages",
				"Page %s has no access control of any kind" % url,
				"Neither a declared permission block nor any runtime identity "
				"check was found on view %s. Any session that reaches the "
				"gateway can open it.%s%s" % (p["viewPath"], extra, knows),
				cite,
				"Decide which security level should own this screen, declare it "
				"on the view resource, and enforce it at runtime.",
				{"url": url, "viewPath": p["viewPath"],
				 "sensitiveComponents": p["sensitiveComponents"],
				 "identityReads": p["identityReads"]}))

		elif prot == "declared-only":
			out.append(core.finding(
				"P002", "HIGH", "pages",
				"Page %s declares a permission nothing appears to enforce" % url,
				"View %s declares %s in %s, but the view contains no binding or "
				"script that evaluates the session's identity. A declared "
				"permission with no runtime check reads as protected in a "
				"config review while behaving as unprotected to a visitor -- "
				"which is worse than having no permission at all, because it "
				"stops anyone from looking closer."
				% (p["viewPath"], ", ".join(p["declaredLevels"]), p["declaredIn"]),
				cite,
				"Add the runtime check the declaration implies, and confirm by "
				"opening the URL as a user who should not have access.",
				{"url": url, "declaredLevels": p["declaredLevels"],
				 "declaredIn": p["declaredIn"]}))

		elif prot == "enforced-only":
			out.append(core.finding(
				"P005", "LOW", "pages",
				"Page %s is gated in code but declares no permission" % url,
				"View %s gates on the session identity at runtime (%s) but "
				"carries no declared permission block. The screen behaves "
				"correctly; the gap is that its access rule exists only inside "
				"a binding, so it does not appear in any configuration review "
				"and is easy to drop during a refactor."
				% (p["viewPath"], "; ".join(p["enforcementMarkers"])),
				cite,
				"Declare the equivalent permission on the view resource so the "
				"intent is visible in configuration as well as in code.",
				{"url": url, "markers": p["enforcementMarkers"]}))

		# A requirement naming a level that does not exist can never be met.
		if knownLevels:
			for lvl in p["declaredLevels"]:
				if lvl not in knownLevels:
					out.append(core.finding(
						"P003", "MEDIUM", "pages",
						"Page %s requires security level %s, which is not defined"
						% (url, lvl),
						"The view requires %s but that level does not appear in "
						"the gateway's security-level tree, so no user can ever "
						"satisfy it." % lvl,
						cite,
						"Define the level, or change the requirement to a level "
						"that exists.",
						{"url": url, "level": lvl, "knownLevels": knownLevels}))

	# UI-only gating is a usability control, never a security boundary. Say it
	# once at the end rather than repeating it on every page.
	visualOnly = [p["url"] for p in inv["pages"]
	              if p["protection"] in ("enforced-only", "declared-and-enforced")]
	if visualOnly:
		out.append(core.finding(
			"P006", "INFO", "pages",
			"Page-level gating hides screens; it does not protect what they call",
			"%d page(s) gate access in the Perspective view: %s. That controls "
			"what a user sees, not what they can invoke. The named queries, tag "
			"writes and WebDev endpoints those screens call are reachable by "
			"any authenticated session that knows the path, unless each one "
			"carries its own check."
			% (len(visualOnly), ", ".join(visualOnly)),
			inv["file"],
			"Confirm every sensitive named query, tag write and WebDev endpoint "
			"enforces its own access rule independently of the screen.",
			{"pages": visualOnly}))

	return core.sortFindings(out)
