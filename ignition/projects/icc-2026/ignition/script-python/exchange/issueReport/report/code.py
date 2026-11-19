"""Instant Issue Report -- context capture and Perspective view/binding introspection.

The read side of the three-stage issue pipeline:

    Submitted  ->  Validate  ->  Implement  ->  Completed

Stage 1 runs in a Perspective session: an operator hits "Report this issue" on a
screen that is misbehaving, the button captures the runtime context, and a chat
agent researches it and files a ticket. Stages 2 and 3 are driven by YouTrack
column-change webhooks and reuse *these same* functions -- which is why nothing
here depends on a Perspective session being present.

**Tickets live in YouTrack, not here.** The board (project ``UI``, "Ignition
Issues") is the single source of truth and its ``Stage`` field is the state
machine; agents reach it through the gateway's ``youtrack`` MCP connection. This
module deliberately owns no ticket storage -- there is no database in the ticket
path at all.

Two groups of functions:

* **Introspection** (``loadViewJson``, ``getComponent``, ``getBindings``,
  ``resolveIndirectTagPath``, ``diagnoseTagPath``) -- read-only, gateway-scoped,
  no session required. These back the narrow agent tools ``get_view_json`` /
  ``get_component_bindings`` / ``diagnose_tag_reference``, and the Validate and
  Implement agents call them again when they need to see the resource they are
  about to change.
* **Capture** (``captureContext``, ``suspectComponents``) -- called from a
  Perspective button script. Collects only what the *session* knows (view path,
  live prop values, who is looking at it). Binding definitions are deliberately
  NOT captured here: they live in the view resource, and the agent fetches them
  with a tool so the research step is visible in the transcript.
"""

import os
import sys
import time
import traceback

from java.lang import System as JavaSystem

PROJECT = "icc-2026"

_PERSPECTIVE_RES = "com.inductiveautomation.perspective/views"

logger = system.util.getLogger("exchange.issueReport.Report")

YOUTRACK_PORT = "8089"


# ---------------------------------------------------------------------------
# YouTrack browser URL
# ---------------------------------------------------------------------------
#
# The host-derivation logic lives in :mod:`exchange.demo.hosts`, which every demo service
# in this stack shares (the Gmail/Mailpit inbox needs exactly the same trick).
# These two are kept as the long-standing public names -- ``youtrackUrl`` is
# called from the Report Issue page's YouTrack button, and ``_env`` from
# :func:`exchange.issueReport.pipeline._youtrackRest` -- so they delegate rather than duplicate.

import exchange.demo.hosts


def _env(name):
	"""A gateway-process environment variable, or None if unset/blank."""
	return exchange.demo.hosts.env(name)


def _hostOf(address):
	"""The hostname out of a URL -- no scheme, no port, no path."""
	return exchange.demo.hosts.hostOf(address)


def youtrackUrl(gatewayAddress=None, path=None):
	"""A browser-reachable URL for the YouTrack beside this gateway.

	YouTrack runs in the same compose stack and is published on the *same host*
	as the gateway, on its own port -- so the only unknown is the hostname the
	operator's browser used, and hardcoding it pins the link to one machine.

	``gatewayAddress`` is ``session.props.gateway.address``, which Perspective
	fills in with the address the browser connected to, published port included:
	``http://localhost:8088`` on the demo laptop, ``http://demo-server.example.com:8088`` on
	the AI server. Swapping its port for YouTrack's is the whole trick. Nothing
	gateway-side is a substitute -- ``system.util.getGatewayAddress()`` and the
	servlet's own view of itself only ever see the container-internal address
	(``:8088``), and ``session.props.host`` is the *client's* IP.

	Two overrides for a deployment where that does not hold (YouTrack behind a
	reverse proxy, or on a different box). Both are read from the gateway
	process environment, so they must be passed into the container -- see the
	ignition service's ``environment:`` block in docker-compose.yml:

	* ``YOUTRACK_URL``  -- full base URL, wins outright
	* ``YOUTRACK_PORT`` -- port only, replacing the 8089 default

	Args:
		gatewayAddress: value of ``session.props.gateway.address``. Falls back
			to localhost when empty, which is only right on the gateway's own
			machine.
		path: optional YouTrack route to append, e.g. ``issue/UI-14``.

	Returns:
		str, with no trailing slash.
	"""
	return exchange.demo.hosts.serviceUrl(
		gatewayAddress, YOUTRACK_PORT, "YOUTRACK_URL", "YOUTRACK_PORT", path)


# ---------------------------------------------------------------------------
# Resource-path resolution
# ---------------------------------------------------------------------------

def _dataDir():
	"""Locate the gateway data directory.

	Tries the ``ignition.datadir`` system property, then ``user.dir``/data, then
	the container default. Returns the first candidate that actually contains a
	``projects`` folder so this works on a Docker gateway and a Windows dev
	install alike.
	"""
	candidates = []
	for prop in ("ignition.datadir", "user.dir"):
		val = JavaSystem.getProperty(prop)
		if val:
			candidates.append(val)
			candidates.append(os.path.join(val, "data"))
	candidates.append("/usr/local/bin/ignition/data")
	for c in candidates:
		if c and os.path.isdir(os.path.join(c, "projects")):
			return c
	raise IOError("Could not locate the gateway data directory (tried: %s)" % ", ".join([unicode(c) for c in candidates]))


def viewDir(viewPath, project=None):
	"""Absolute path to a Perspective view's resource folder.

	Args:
		viewPath (str): Slash-separated view path as it appears in the Designer,
			e.g. ``Exchange/Report Issue Agent/Line Overview``. A leading slash is ignored.
		project (str): Project name. Defaults to :data:`PROJECT`.

	Returns:
		str: Absolute directory path (not guaranteed to exist).
	"""
	proj = project or PROJECT
	clean = unicode(viewPath or "").strip().strip("/")
	return os.path.join(_dataDir(), "projects", proj, _PERSPECTIVE_RES, *clean.split("/"))


def loadViewJson(viewPath, project=None):
	"""Read and decode a view's ``view.json``.

	Args:
		viewPath (str): e.g. ``Exchange/Report Issue Agent/Line Overview``.
		project (str): Project name. Defaults to :data:`PROJECT`.

	Returns:
		dict: The decoded view document.

	Raises:
		IOError: If the view does not exist.
	"""
	path = os.path.join(viewDir(viewPath, project), "view.json")
	if not os.path.isfile(path):
		raise IOError("No view.json at %s (view path '%s' correct?)" % (path, viewPath))
	return system.util.jsonDecode(system.file.readFileAsString(path, "UTF-8"))


def saveViewJson(viewPath, doc, project=None):
	"""Write a decoded view document back to disk, pretty-printed.

	The Implement stage is the only thing that calls this. It does not scan --
	the caller decides when, because an edit and its reload should be one
	deliberate step (see ``exchange.issueReport.pipeline.requestScan``).
	"""
	path = os.path.join(viewDir(viewPath, project), "view.json")
	if not os.path.isfile(path):
		raise IOError("No view.json at %s -- refusing to create a view by accident." % path)
	system.file.writeFile(path, system.util.jsonEncode(doc, 2), False)
	logger.info("Wrote %s" % path)
	return path


def setViewCustomProperty(viewPath, name, value, expectedCurrent=None, project=None):
	"""Set one entry in a view's top-level ``custom`` object.

	Args:
		viewPath (str): e.g. ``Exchange/Report Issue Agent/Line Overview``.
		name (str): Key inside ``view.custom``.
		value: New value.
		expectedCurrent: If given, the write is refused unless the property
			currently equals this. The guard is the point -- an agent applying a
			fix has to say what it believes it is replacing, so a stale or
			already-applied ticket cannot silently clobber something else.
		project (str): Defaults to :data:`PROJECT`.

	Returns:
		dict: ``{view, property, previous, current, changed}``.

	Raises:
		KeyError: If the property does not already exist.
		ValueError: If ``expectedCurrent`` does not match.
	"""
	doc = loadViewJson(viewPath, project)
	custom = doc.get("custom")
	if not isinstance(custom, dict) or name not in custom:
		raise KeyError("View '%s' has no custom property '%s'. Present: %s"
		               % (viewPath, name, ", ".join(sorted(custom.keys())) if isinstance(custom, dict) else "(none)"))

	previous = custom[name]
	if expectedCurrent is not None and unicode(previous) != unicode(expectedCurrent):
		raise ValueError(
			"Refusing to write: '%s' is currently %r, not the expected %r. The ticket may be "
			"stale, or the fix may already have been applied."
			% (name, previous, expectedCurrent))

	if unicode(previous) == unicode(value):
		return {"view": viewPath, "property": name, "previous": previous,
		        "current": previous, "changed": False,
		        "note": "Already at the requested value -- nothing written."}

	custom[name] = value
	saveViewJson(viewPath, doc, project)
	return {"view": viewPath, "property": name, "previous": previous,
	        "current": value, "changed": True}


DEMO_VIEW = "Exchange/Report Issue Agent/Line Overview"
DEMO_PROPERTY = "torqueTagName"
DEMO_FAULT_VALUE = "MotorTorqe"
DEMO_GOOD_VALUE = "MotorTorque"


def injectDemoFault(faulted=True):
	"""Arm or clear the demo defect *in the view resource*, not just the session.

	The demo buttons used to assign ``self.view.custom.torqueTagName`` directly.
	That only changes the running session, so the operator saw the overlay while
	``view.json`` on disk still held the corrected value -- and every stage after
	Report reads the resource. The result was a ticket whose live capture and
	saved resource disagreed, a Validate verdict of CANNOT REPRODUCE, and an
	Implement stage that (correctly) refused to act.

	Writing the resource and rescanning keeps session and disk telling the same
	story, which is the only way the pipeline can act on the fault.

	Args:
		faulted (bool): True arms the typo, False restores the good tag name.

	Returns:
		dict: The result of the underlying write, plus ``reloaded``.
	"""
	target = DEMO_FAULT_VALUE if faulted else DEMO_GOOD_VALUE
	result = setViewCustomProperty(DEMO_VIEW, DEMO_PROPERTY, target)
	if result.get("changed"):
		exchange.issueReport.pipeline.requestScan()
		result["reloaded"] = True
	result["faulted"] = bool(faulted)
	return result


DEMO_REARM_SECS = 8 * 60


def demoFaultAge():
	"""Whether the demo defect is armed, and how long the current state has held.

	The "how long" comes from the mtime of ``view.json`` rather than from a
	memory tag or a module global, because the only two things that ever change
	this property *are* writes to that file -- the Implement agent fixing the
	typo, or :func:`injectDemoFault` putting it back. So the file's own
	timestamp already is the state clock, and it survives a script reload, a
	project rescan and a gateway restart without anything having to persist it.

	Returns:
		dict: ``{value, faulted, changedSecsAgo, path}``. ``changedSecsAgo`` is
		None if the mtime could not be read.
	"""
	doc = loadViewJson(DEMO_VIEW)
	value = (doc.get("custom") or {}).get(DEMO_PROPERTY)
	path = os.path.join(viewDir(DEMO_VIEW), "view.json")
	age = None
	try:
		age = time.time() - os.path.getmtime(path)
	except:
		logger.warn("could not stat %s -- rearm timer has no clock" % path)
	return {"value": value,
	        "faulted": unicode(value) == DEMO_FAULT_VALUE,
	        "changedSecsAgo": age,
	        "path": path}


def rearmDemoFault(afterSecs=None):
	"""Put the demo defect back once it has been fixed and left alone a while.

	The demo is meant to be run repeatedly on a show floor, and the interesting
	half of it is the pipeline *fixing* the fault -- which leaves the stack in a
	state where the demo cannot be run again. This re-arms it, so the only
	manual step is the one the audience watches.

	Deliberately does nothing while the fault is already armed, so it can run on
	a one-minute timer and stay a no-op for all but one tick per cycle.

	Args:
		afterSecs (int): How long the fixed state must have held. Defaults to
			:data:`DEMO_REARM_SECS` (8 minutes). The clock runs from the moment
			the fix was written, so this is the margin the Implement agent has to
			finish its run after applying the fix. Its own invocation timeout is
			300 s, so 8 minutes clears the worst case with ~3 minutes to spare --
			the fault cannot reappear underneath a run however long it takes.

	Gated by ``[default]Exchange/Demo/Control/Timers/IssueFaultRearmEnabled`` (see
	:mod:`exchange.demo.control`).

	Returns:
		dict: ``{action, ...}`` where action is ``already_armed``, ``waiting``,
		``rearmed`` or ``disabled``.
	"""
	if not exchange.demo.control.timerEnabled("IssueFaultRearm"):
		return {"action": "disabled"}
	wait = DEMO_REARM_SECS if afterSecs is None else int(afterSecs)
	state = demoFaultAge()

	if state["faulted"]:
		return {"action": "already_armed", "value": state["value"]}

	age = state["changedSecsAgo"]
	if age is None:
		return {"action": "waiting", "reason": "could not read view.json mtime"}
	if age < wait:
		return {"action": "waiting", "value": state["value"],
		        "secsHeld": int(age), "secsRemaining": int(wait - age)}

	result = injectDemoFault(True)
	logger.info("Re-armed the demo binding fault after %d s clear (%s -> %s)"
	            % (int(age), state["value"], DEMO_FAULT_VALUE))
	result["action"] = "rearmed"
	result["secsHeld"] = int(age)

	# Re-arming is the start of a fresh demo cycle, so the Pipeline Status board
	# gets emptied with it -- last month's runs sitting above this one's is noise
	# on stage. Guarded so a database problem cannot stop the re-arm itself: the
	# fault coming back is the job, a tidy board is the garnish.
	try:
		result["activityCleared"] = exchange.issueReport.pipeline.clearActivity()
	except:
		logger.warn("Re-armed, but could not clear the activity log: %s"
		            % traceback.format_exc())
		result["activityCleared"] = None

	return result


def listViews(project=None, prefix=""):
	"""List every view path in the project, optionally filtered by prefix.

	Lets an agent recover when it has been handed a slightly wrong view path
	instead of failing the whole turn.

	Returns:
		list: Sorted slash-separated view paths.
	"""
	root = os.path.join(_dataDir(), "projects", project or PROJECT, *_PERSPECTIVE_RES.split("/"))
	found = []
	if not os.path.isdir(root):
		return found
	for dirpath, dirnames, filenames in os.walk(root):
		if "view.json" in filenames:
			rel = os.path.relpath(dirpath, root).replace(os.sep, "/")
			if rel != "." and rel.startswith(prefix):
				found.append(rel)
	found.sort()
	return found


# ---------------------------------------------------------------------------
# Component tree walking
# ---------------------------------------------------------------------------

def _childName(node):
	meta = node.get("meta") or {}
	return meta.get("name")


def getComponent(viewDoc, componentPath):
	"""Resolve a slash-separated component path within a decoded view document.

	Args:
		viewDoc (dict): Output of :func:`loadViewJson`.
		componentPath (str): Chain of ``meta.name`` values starting at ``root``,
			e.g. ``root/Body/TorqueCard/TorqueValue``. The leading ``root`` is
			optional. Empty/None returns the root container.

	Returns:
		dict: The component node.

	Raises:
		ValueError: If a segment cannot be found (the message lists the names
			that *were* available, which is what the agent needs to self-correct).
	"""
	node = viewDoc.get("root") or {}
	clean = unicode(componentPath or "").strip().strip("/")
	if not clean:
		return node
	parts = clean.split("/")
	if parts and parts[0] == "root":
		parts = parts[1:]
	walked = ["root"]
	for part in parts:
		children = node.get("children") or []
		match = None
		for child in children:
			if _childName(child) == part:
				match = child
				break
		if match is None:
			available = [_childName(c) for c in children]
			raise ValueError(
				"No component named '%s' under %s. Available: %s"
				% (part, "/".join(walked), ", ".join([unicode(a) for a in available]) or "(no children)")
			)
		node = match
		walked.append(part)
	return node


def componentTree(node, depth=0, maxDepth=6, prefix="root"):
	"""Flatten a component subtree into ``{path, type, name}`` rows.

	Used to give an agent a cheap map of a view without shipping the entire
	view.json.
	"""
	rows = [{"path": prefix, "type": node.get("type"), "name": _childName(node)}]
	if depth >= maxDepth:
		return rows
	for child in (node.get("children") or []):
		name = _childName(child) or "?"
		rows.extend(componentTree(child, depth + 1, maxDepth, prefix + "/" + name))
	return rows


# ---------------------------------------------------------------------------
# Binding introspection
# ---------------------------------------------------------------------------

def _tagRefsFromBinding(btype, config):
	"""Best-effort extraction of tag paths a binding depends on."""
	refs = []
	if not isinstance(config, dict):
		return refs
	if btype == "tag":
		tp = config.get("tagPath")
		if tp:
			refs.append(unicode(tp))
	elif btype == "tag-history":
		tags = config.get("tags")
		if isinstance(tags, list):
			for t in tags:
				if isinstance(t, dict) and t.get("path"):
					refs.append(unicode(t.get("path")))
	elif btype == "expr":
		expr = unicode(config.get("expression") or "")
		# Tag references inside an expression look like {[provider]path/to/tag}
		buf = None
		for ch in expr:
			if ch == "{":
				buf = ""
			elif ch == "}" and buf is not None:
				if buf.startswith("["):
					refs.append(buf)
				buf = None
			elif buf is not None:
				buf += ch
	return refs


def describeBinding(propPath, binding):
	"""Normalise one binding into a flat, agent-friendly dict."""
	btype = binding.get("type")
	config = binding.get("config") or {}
	transforms = binding.get("transforms") or []
	out = {
		"prop": propPath,
		"type": btype,
		"config": config,
		"transformCount": len(transforms),
		"transforms": [{"type": t.get("type"), "code": t.get("code"), "expression": t.get("expression")} for t in transforms],
		"tagReferences": _tagRefsFromBinding(btype, config),
	}
	if btype == "tag":
		out["mode"] = config.get("mode")
		out["tagPathTemplate"] = config.get("tagPath")
		out["references"] = config.get("references") or {}
	return out


def getBindings(viewPath, componentPath=None, project=None, includeDescendants=False):
	"""Return the binding definitions attached to a component.

	Args:
		viewPath (str): e.g. ``Exchange/Report Issue Agent/Line Overview``.
		componentPath (str): Component to inspect. ``None``/empty = the root
			container (which is also where view-level bindings on ``root`` live).
		project (str): Project name.
		includeDescendants (bool): Also walk children. Useful when the reporter
			flagged a card rather than the exact label that is erroring.

	Returns:
		dict: ``{view, component, viewCustom, bindings: [...]}`` where each
		binding is the output of :func:`describeBinding` plus an ``owner`` key
		giving the component path it was found on.
	"""
	doc = loadViewJson(viewPath, project)
	basePath = unicode(componentPath or "root").strip().strip("/") or "root"
	if not basePath.startswith("root"):
		basePath = "root/" + basePath
	node = getComponent(doc, basePath)

	bindings = []

	def collect(n, path):
		for propPath, cfg in (n.get("propConfig") or {}).items():
			if isinstance(cfg, dict) and cfg.get("binding"):
				desc = describeBinding(propPath, cfg["binding"])
				desc["owner"] = path
				bindings.append(desc)
		if includeDescendants:
			for child in (n.get("children") or []):
				collect(child, path + "/" + (_childName(child) or "?"))

	collect(node, basePath)

	# View-level propConfig (params/custom bindings) is context the agent needs
	# in order to resolve an indirect tag path.
	viewLevel = []
	for propPath, cfg in (doc.get("propConfig") or {}).items():
		if isinstance(cfg, dict) and cfg.get("binding"):
			desc = describeBinding(propPath, cfg["binding"])
			desc["owner"] = "(view)"
			viewLevel.append(desc)

	return {
		"view": viewPath,
		"component": basePath,
		"componentType": node.get("type"),
		"viewCustom": doc.get("custom") or {},
		"viewParams": doc.get("params") or {},
		"viewLevelBindings": viewLevel,
		"bindings": bindings,
		"count": len(bindings),
	}


def resolveIndirectTagPath(template, references, viewCustom, viewParams):
	"""Substitute an indirect tag binding's references to get the literal path.

	Only ``{view.custom.*}`` / ``{view.params.*}`` references can be resolved
	statically (``{this.*}`` needs a live component), so those are left as-is
	and reported to the caller.

	Returns:
		tuple: ``(resolvedPath, unresolvedRefs)``
	"""
	path = unicode(template or "")
	unresolved = []
	for name, ref in (references or {}).items():
		token = unicode(ref or "").strip().strip("{}")
		value = None
		if token.startswith("view.custom."):
			value = (viewCustom or {}).get(token[len("view.custom."):])
		elif token.startswith("view.params."):
			value = (viewParams or {}).get(token[len("view.params."):])
		if value is None:
			unresolved.append({"name": name, "reference": ref})
		else:
			path = path.replace("{%s}" % name, unicode(value))
	return path, unresolved


# ---------------------------------------------------------------------------
# Tag diagnosis -- the "does the agent's hypothesis hold up" check
# ---------------------------------------------------------------------------

def _levenshtein(a, b):
	if a == b:
		return 0
	if not a:
		return len(b)
	if not b:
		return len(a)
	prev = list(range(len(b) + 1))
	for i in range(len(a)):
		cur = [i + 1]
		for j in range(len(b)):
			cur.append(min(prev[j + 1] + 1, cur[j] + 1, prev[j] + (a[i] != b[j])))
		prev = cur
	return prev[-1]


def diagnoseTagPath(tagPath):
	"""Check whether a tag path resolves, and suggest near-misses if it does not.

	This is the function that actually catches a typo: it browses the parent
	folder and ranks siblings by edit distance, so ``.../Packaging/MotorTorqe``
	comes back with ``MotorTorque`` as the obvious intended target.

	Args:
		tagPath (str): Full path. A missing ``[provider]`` prefix is assumed
			``[default]``.

	Returns:
		dict: ``{path, exists, value, quality, good, parentExists, siblings,
		suggestions}``.
	"""
	path = unicode(tagPath or "").strip()
	if not path:
		raise ValueError("tagPath is required")
	if not path.startswith("["):
		path = "[default]" + path

	out = {"path": path, "exists": False, "value": None, "quality": None, "good": False,
	       "parent": None, "parentExists": False, "siblings": [], "suggestions": []}

	try:
		out["exists"] = bool(system.tag.exists(path))
	except:
		e = sys.exc_info()[1]
		logger.warn("tag.exists failed for %s: %s" % (path, str(e)))

	try:
		qv = system.tag.readBlocking([path])[0]
		out["quality"] = unicode(qv.quality)
		out["good"] = bool(qv.quality.isGood())
		if out["good"]:
			out["value"] = qv.value
	except:
		e = sys.exc_info()[1]
		out["quality"] = "read failed: %s" % str(e)

	# Browse the parent folder for near-misses.
	if "/" in path:
		parent = path.rsplit("/", 1)[0]
		leaf = path.rsplit("/", 1)[1]
		out["parent"] = parent
		try:
			results = system.tag.browse(parent)
			names = []
			for r in results.getResults():
				n = unicode(r["name"])
				names.append(n)
			out["parentExists"] = True
			out["siblings"] = sorted(names)
			scored = []
			for n in names:
				d = _levenshtein(leaf.lower(), n.lower())
				if d <= max(2, len(leaf) / 4):
					scored.append((d, n))
			scored.sort()
			out["suggestions"] = [{"name": n, "distance": d, "path": parent + "/" + n} for d, n in scored[:5]]
		except:
			e = sys.exc_info()[1]
			out["parentExists"] = False
			out["siblings"] = []
			logger.debug("browse failed for %s: %s" % (parent, str(e)))

	return out


# ---------------------------------------------------------------------------
# Session-side context capture (called from a Perspective button)
# ---------------------------------------------------------------------------

def _plainProps(node, maxKeys=40):
	"""Snapshot a component's props as plain JSON-safe values."""
	try:
		return system.util.jsonDecode(system.util.jsonEncode(node.props))
	except:
		e = sys.exc_info()[1]
		return {"_error": "could not snapshot props: %s" % str(e)}


def captureContext(view, componentPath=None, username=None, pageUrl=None, viewPath=None):
	"""Build the context payload handed to the report agent.

	Called from a Perspective ``onActionPerformed`` script with ``self.view``.
	Only session-visible facts go in here; binding definitions and view JSON are
	left for the agent's tools so the research step is explicit.

	Args:
		view: The Perspective ``view`` object (``self.view``).
		componentPath (str): Path of the component the operator is complaining
			about, e.g. ``root/Body/TorqueCard/TorqueValue``. Optional -- when
			omitted the whole view is captured and ``suspectComponents`` carries
			the heuristic shortlist instead.
		username (str): Reporter, usually ``self.session.props.auth.user.userName``.
		pageUrl (str): Current page path, for the ticket's "where" line.
		viewPath (str): Override the view path. Needed when the button lives in
			an embedded view but the issue is on the host view.

	Returns:
		dict: JSON-safe context object.
	"""
	ctx = {
		"project": PROJECT,
		"viewPath": None,
		"componentPath": componentPath,
		"reporter": username,
		"pageUrl": pageUrl,
		"capturedAt": system.date.format(system.date.now(), "yyyy-MM-dd'T'HH:mm:ss"),
		"viewParams": {},
		"viewCustom": {},
		"componentProps": {},
		"suspectComponents": [],
	}

	if viewPath:
		ctx["viewPath"] = unicode(viewPath)
	else:
		try:
			# view.id is the mounted *instance* id and carries a suffix -- e.g.
			# "Exchange/Report Issue Agent/Line Overview@C". Everything downstream treats
			# viewPath as a resource path and would fail to load the file.
			ctx["viewPath"] = unicode(view.id).split("@")[0]
		except:
			e = sys.exc_info()[1]
			logger.warn("could not read view.id: %s" % str(e))

	for key, src in (("viewParams", "params"), ("viewCustom", "custom")):
		try:
			ctx[key] = system.util.jsonDecode(system.util.jsonEncode(getattr(view, src)))
		except:
			ctx[key] = {}

	# Live props of the flagged component, plus a shallow scan for components
	# whose bound props came back empty -- a cheap heuristic that usually points
	# at the same component the operator clicked, and sometimes finds one they
	# missed.
	if ctx["viewPath"]:
		try:
			doc = loadViewJson(ctx["viewPath"])
			if componentPath:
				node = getComponent(doc, componentPath)
				ctx["componentType"] = node.get("type")
				ctx["componentStaticProps"] = node.get("props") or {}
			ctx["suspectComponents"] = _scanForEmptyBoundProps(doc)

			# Compare live session custom props against the saved resource. When
			# they disagree, every stage after this one reads the *file* and will
			# not see what the operator is looking at -- so surface it here rather
			# than letting the agent quietly reconcile two different realities.
			savedCustom = doc.get("custom") or {}
			diverged = []
			for name, live in (ctx["viewCustom"] or {}).items():
				if name in savedCustom and unicode(savedCustom[name]) != unicode(live):
					diverged.append({
						"property": name,
						"sessionValue": live,
						"savedValue": savedCustom[name],
					})
			ctx["divergedProperties"] = diverged
			if diverged:
				ctx["divergenceWarning"] = (
					"The live session and the saved view resource disagree on %d custom "
					"property/properties. The later pipeline stages read the SAVED resource, "
					"so a fix based on the session values will not reproduce for them. Report "
					"this divergence as the finding instead of guessing which is correct."
					% len(diverged))
		except:
			e = sys.exc_info()[1]
			ctx["captureWarning"] = "could not read view resource: %s" % str(e)

	if componentPath:
		try:
			node = view.getChild(componentPath)
			if node is not None:
				ctx["componentProps"] = _plainProps(node)
		except:
			e = sys.exc_info()[1]
			ctx["componentPropsWarning"] = str(e)

	return ctx


def suspectComponents(viewPath, project=None):
	"""Heuristic shortlist of components in a view whose bindings look dead.

	Public wrapper around :func:`_scanForEmptyBoundProps` so the same shortlist
	can be recomputed later (by the Validate agent, or a test) without a session.
	"""
	return _scanForEmptyBoundProps(loadViewJson(viewPath, project))


# Binding types whose persisted value is legitimately empty -- a tag-history or
# named-query binding stores [] in view.json and only fills at runtime, so an
# empty value says nothing about whether it works.
_DATA_BINDING_TYPES = ("tag-history", "query", "http", "expr-struct")


def _resolvePropPath(props, propPath):
	"""Resolve a Perspective prop path like ``props.series[0].data`` against a props dict.

	Returns ``(found, value)``. Handles dotted segments and ``[n]`` indexes; an
	unresolvable path returns ``(False, None)`` so callers can tell "missing
	path" apart from "present but empty".
	"""
	if not propPath.startswith("props."):
		return False, None
	node = props
	for seg in propPath[len("props."):].split("."):
		name, idxs = seg, []
		while name.endswith("]") and "[" in name:
			head, _, rest = name.rpartition("[")
			idxs.insert(0, rest[:-1])
			name = head
		if name:
			if not isinstance(node, dict) or name not in node:
				return False, None
			node = node[name]
		for i in idxs:
			try:
				node = node[int(i)]
			except (ValueError, IndexError, TypeError, KeyError):
				return False, None
	return True, node


def _scanForEmptyBoundProps(doc, maxHits=8):
	"""Find components whose bound props have a null/empty *persisted* value.

	A bound scalar prop saved with no value is a decent signal that the binding
	has never successfully evaluated. Heuristic only -- reported to the agent as
	a hint, never as a conclusion.

	Data-shaped bindings (see :data:`_DATA_BINDING_TYPES`) and collection values
	are skipped: a chart's ``series[0].data`` is *supposed* to persist empty, and
	flagging it buries the one component that actually matters.
	"""
	hits = []

	def walk(node, path):
		if len(hits) >= maxHits:
			return
		props = node.get("props") or {}
		for propPath, cfg in (node.get("propConfig") or {}).items():
			if not (isinstance(cfg, dict) and cfg.get("binding")):
				continue
			if cfg["binding"].get("type") in _DATA_BINDING_TYPES:
				continue
			found, val = _resolvePropPath(props, propPath)
			if not found:
				continue
			if isinstance(val, (list, tuple, dict)):
				continue
			if val is None or val == "":
				hits.append({
					"component": path,
					"type": node.get("type"),
					"prop": propPath,
					"bindingType": cfg["binding"].get("type"),
				})
		for child in (node.get("children") or []):
			walk(child, path + "/" + (_childName(child) or "?"))

	walk(doc.get("root") or {}, "root")
	return hits
