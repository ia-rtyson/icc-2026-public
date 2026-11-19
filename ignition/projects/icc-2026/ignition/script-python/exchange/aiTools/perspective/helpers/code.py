"""
Shared helpers for the Perspective CRUD tools.

All filesystem ops go through system.* gateway functions (or java.io where the
system.* surface has no equivalent) so the writes land in the gateway sandbox
where the project scan watches.

Conventions enforced here:

	* view.json sha256 -> resource.json attributes.lastModificationSignature,
	refreshed without discarding the rest of the resource descriptor
	* view.json is read shape-agnostically: the component tree may be nested
	under "root" (the real Perspective format) or, in older resources written
	by these tools, be the top-level dict itself. See viewRoot().
	* meta.name uniqueness within a view (scripting + binding handle)
	* bind in propConfig["<scope>.<path>"].binding, never inline in props;
	propConfig is a flat map keyed by full path ("props.style.fontSize"),
	and transforms nest inside the binding object
	* event scope is a sibling of config, never inside it
	* page-config atomic read-modify-write (no sibling-key drop)
"""

import json
import os
import sys
import time
import traceback

logger = system.util.getLogger("exchange.aiTools.PerspectiveHelpers")


# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

# Candidate gateway data/projects directories, in priority order. The first
# one that exists wins; if none exist we fall back to the Linux container path
# so error messages still name a plausible location. Override with the
# IGNITION_PROJECTS_DIR environment variable.
_PROJECT_ROOT_CANDIDATES = (
	"/usr/local/bin/ignition/data/projects",
	"/var/lib/ignition/data/projects",
	"C:/Program Files/Inductive Automation/Ignition/data/projects",
)

_projectRootCache = []


def projectRoot():
	"""Resolve the gateway's data/projects directory."""
	if _projectRootCache:
		return _projectRootCache[0]
	from java.io import File
	try:
		override = os.environ.get("IGNITION_PROJECTS_DIR")
	except Exception:
		override = None
	candidates = ([override] if override else []) + list(_PROJECT_ROOT_CANDIDATES)
	resolved = _PROJECT_ROOT_CANDIDATES[0]
	for c in candidates:
		try:
			if File(c).isDirectory():
				resolved = c
				break
		except:
			# Bare except: java.io.File raises Java exceptions
			logger.warn("Cannot inspect projects dir candidate %s: %s" % (c, sys.exc_info()[1]))
			continue
	_projectRootCache.append(resolved)
	return resolved


# Retained for callers that referenced the old module-level constant. Prefer
# projectRoot() -- this value is only the first candidate.
PROJECT_ROOT = _PROJECT_ROOT_CANDIDATES[0]

VIEW_DIR = "com.inductiveautomation.perspective/views"
STYLESHEET_DIR = "com.inductiveautomation.perspective/styles"
PAGE_CONFIG_DIR = "com.inductiveautomation.perspective/page-config"
NAMED_SESSION_DIR = "com.inductiveautomation.perspective/named-sessions"

AGENT_MODULE = "com.inductiveautomation.catalyst.agent"  # was ...ai.agent before 2027.2.0-beta1
LOCAL_IGNITION_CONFIG = (
	"/usr/local/bin/ignition/data/config/resources/core/"
	"com.inductiveautomation.catalyst.agent/mcp-server-host/local-ignition/config.json"
)

# Actor recorded in resource.json when these tools write a resource. Matches
# what the gateway's own external-import path records.
RESOURCE_ACTOR = "external"

CONTAINER_TYPES = (
	"ia.container.coord",
	"ia.container.flex",
	"ia.container.breakpt",
	"ia.container.tab",
	"ia.container.split",
	"ia.container.column",
	"ia.container.view",
)

BINDING_TYPES = (
	"tag", "property", "expression", "expression-structure",
	"query", "tag-history", "http", "structure",
)

TRANSFORM_TYPES = ("format", "script", "map", "expression")


# ---------------------------------------------------------------------------
# Filesystem primitives
# ---------------------------------------------------------------------------

def _listDir(path):
	"""List directory entry names. system.file has no listFiles equivalent."""
	from java.io import File
	f = File(path)
	if not f.exists() or not f.isDirectory():
		return []
	children = f.list()
	if children is None:
		return []
	out = []
	for i in range(len(children)):
		out.append(str(children[i]))
	return out


def isDir(path):
	from java.io import File
	try:
		return File(path).isDirectory()
	except:
		# Bare except: java.io.File raises Java exceptions
		logger.warn("isDir failed for %s: %s" % (path, sys.exc_info()[1]))
		return False


def deletePath(path):
	"""Recursively delete a file or directory. Returns True if it is gone.

	system.file.writeFile(path, '') only truncates -- it leaves the resource
	directory in place, which the project scan then reads as a corrupt
	resource. Actually removing the tree is what callers mean by "delete".
	"""
	from java.io import File
	f = File(path)
	if not f.exists():
		return False

	def _rm(handle):
		if handle.isDirectory():
			kids = handle.listFiles()
			if kids is not None:
				for i in range(len(kids)):
					_rm(kids[i])
		handle.delete()

	_rm(f)
	return not f.exists()


def readText(path):
	"""Read a file as a string, or None if it is missing/unreadable."""
	try:
		if not system.file.fileExists(path):
			return None
		return system.file.readFileAsString(path)
	except:
		# Bare except: system.file raises Java exceptions
		logger.warn("readText failed for %s: %s" % (path, sys.exc_info()[1]))
		return None


def isoNow():
	return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def toJson(obj, indent=2):
	return json.dumps(obj, indent=indent, sort_keys=False, separators=(",", ": "))


def fromJson(s):
	if s is None or s == "":
		return None
	return json.loads(s)


def safeLoad(path, default=None):
	s = readText(path)
	if s is None or s == "":
		return default
	try:
		return json.loads(s)
	except Exception:
		return default


def safeWrite(path, data):
	"""Write JSON (dict/list) or raw text (basestring) to path."""
	if isinstance(data, basestring):
		system.file.writeFile(path, data)
	else:
		system.file.writeFile(path, toJson(data))


def requestScan():
	"""Ask the gateway to rescan projects from disk.

	The arity of system.project.requestScan differs across 8.x builds; try the
	no-arg form first and fall back to the list form.
	"""
	try:
		return system.project.requestScan()
	except TypeError:
		return system.project.requestScan([])


# ---------------------------------------------------------------------------
# View helpers
# ---------------------------------------------------------------------------

def viewPath(project, view):
	return "{root}/{p}/{dir}/{v}".format(
		root=projectRoot(), p=project, dir=VIEW_DIR, v=view
	)


def viewJsonPath(project, view):
	return viewPath(project, view) + "/view.json"


def viewResourcePath(project, view):
	return viewPath(project, view) + "/resource.json"


def loadView(project, view):
	return safeLoad(viewJsonPath(project, view), default={})


def saveView(project, view, data):
	safeWrite(viewJsonPath(project, view), data)
	return refreshResourceSignature(project, view)


def viewExists(project, view):
	return system.file.fileExists(viewJsonPath(project, view))


def viewRoot(data):
	"""Return the component-tree root node of a view.json dict.

	Real Perspective view.json is {custom, params, props, root: {...}}. Some
	resources written by earlier versions of these tools stored the root node
	flat at the top level. Accept both so tree operations work either way;
	return None if neither shape is recognizable.
	"""
	if not isinstance(data, dict):
		return None
	root = data.get("root")
	if isinstance(root, dict):
		return root
	if "type" in data or "children" in data:
		return data
	return None


def newView(rootType="ia.container.coord", rootName="Root",
			width=1000, height=800):
	"""Build an empty view.json in the canonical nested shape."""
	return {
		"custom": {},
		"params": {},
		"props": {"defaultSize": {"width": width, "height": height}},
		"root": {
			"type": rootType,
			"meta": {"name": rootName},
			"props": {},
			"custom": {},
			"position": {},
			"children": [],
		},
	}


def refreshResourceSignature(project, view):
	"""Recompute view.json's sha256 and update resource.json in place.

	The existing descriptor is preserved and only the lastModification fields
	are replaced -- rewriting the file from scratch would drop scope, version
	and files:["view.json"], which the project scan needs.
	"""
	import hashlib
	viewBytes = readText(viewJsonPath(project, view))
	if viewBytes is None:
		return {"ok": False, "error": "view.json missing"}
	digest = hashlib.sha256(viewBytes.encode("utf-8")).hexdigest()
	ts = isoNow()

	rp = viewResourcePath(project, view)
	resource = safeLoad(rp, default=None)
	if not isinstance(resource, dict):
		resource = {}
	resource.setdefault("scope", "G")
	resource.setdefault("version", 1)
	resource.setdefault("restricted", False)
	resource.setdefault("overridable", True)
	files = resource.get("files")
	if not isinstance(files, list) or "view.json" not in files:
		resource["files"] = ["view.json"]
	attrs = resource.get("attributes")
	if not isinstance(attrs, dict):
		attrs = {}
		resource["attributes"] = attrs
	attrs["lastModificationSignature"] = digest
	attrs["lastModification"] = {"actor": RESOURCE_ACTOR, "timestamp": ts}

	safeWrite(rp, resource)
	return {"ok": True, "sha256": digest, "timestamp": ts}


# ---------------------------------------------------------------------------
# meta.name uniqueness across a view
# ---------------------------------------------------------------------------

def _collectNames(node, names):
	if isinstance(node, dict):
		n = (node.get("meta") or {}).get("name")
		if n:
			names.append(n)
		for child in node.get("children", []) or []:
			_collectNames(child, names)
	return names


def collectNames(data):
	"""All meta.name values in a view (accepts a view dict or a bare node)."""
	return _collectNames(viewRoot(data) or data, [])


def _findByName(node, name, trail):
	if isinstance(node, dict):
		if (node.get("meta") or {}).get("name") == name:
			return node, trail
		for child in node.get("children", []) or []:
			r, t = _findByName(
				child, name, trail + [(node.get("meta") or {}).get("name")])
			if r is not None:
				return r, t
	return None, None


def findByName(data, name):
	"""Return (node, ancestor_name_trail) or (None, None)."""
	if name is None:
		return None, None
	root = viewRoot(data) or data
	return _findByName(root, name, [])


def nameExists(data, name):
	node, _ = findByName(data, name)
	return node is not None


def _containsNode(root, target):
	"""True if `target` is `root` or appears anywhere in its subtree."""
	if root is target:
		return True
	if not isinstance(root, dict):
		return False
	for child in root.get("children", []) or []:
		if _containsNode(child, target):
			return True
	return False


def _parentOf(root, name):
	if isinstance(root, dict):
		for child in root.get("children", []) or []:
			if isinstance(child, dict) and (child.get("meta") or {}).get("name") == name:
				return root
		for child in root.get("children", []) or []:
			r = _parentOf(child, name)
			if r is not None:
				return r
	return None


def parentOf(data, name):
	"""Walk the tree; return the parent dict whose children include `name`."""
	return _parentOf(viewRoot(data) or data, name)


def _removeChildByName(root, name):
	if not isinstance(root, dict):
		return False
	kids = root.get("children") or []
	new = []
	removed = False
	for c in kids:
		if isinstance(c, dict) and (c.get("meta") or {}).get("name") == name:
			removed = True
			continue
		if _removeChildByName(c, name):
			removed = True
		new.append(c)
	if removed:
		root["children"] = new
	return removed


def removeChildByName(data, name):
	"""Mutate the tree to remove the child with meta.name==name."""
	return _removeChildByName(viewRoot(data) or data, name)


def _walk(node, fn, trail):
	if not isinstance(node, dict):
		return
	fn(node, trail)
	for child in node.get("children", []) or []:
		_walk(child, fn, trail + [node])


def walk(data, fn):
	_walk(viewRoot(data) or data, fn, [])


def treeIndex(data):
	"""Compact {name, type, children[]} outline of a view's component tree."""
	def _index(node):
		if not isinstance(node, dict):
			return None
		out = {
			"name": (node.get("meta") or {}).get("name"),
			"type": node.get("type"),
			"children": [],
		}
		for child in node.get("children", []) or []:
			ci = _index(child)
			if ci is not None:
				out["children"].append(ci)
		return out

	return _index(viewRoot(data) or data)


# ---------------------------------------------------------------------------
# Bindings / events
# ---------------------------------------------------------------------------

# propConfig is a FLAT map keyed by the fully-scoped dotted prop path --
# "props.text", "props.style.fontSize", "custom.total" -- not a nested object
# tree. exchange.aiTools.translator.scan._bindingPaths depends on exactly this. A bare
# path like "text" is scoped to "props." for the caller's convenience.
PROPCONFIG_SCOPES = ("props", "custom", "position", "meta", "params")


def propconfigKey(propPath):
	"""Normalize a caller-supplied prop path to its propConfig key."""
	p = str(propPath).strip().strip(".")
	head = p.split(".")[0]
	if head in PROPCONFIG_SCOPES:
		return p
	return "props." + p


def _pcFindSlot(node, propPath):
	"""Locate an existing propConfig slot. Returns (slot, key_used).

	Looks at the canonical scoped key first, then two legacy locations written
	by earlier versions of these tools: an unscoped flat key, and a nested
	dict tree. Legacy hits are reported so writers can migrate them.
	"""
	pc = node.get("propConfig")
	if not isinstance(pc, dict):
		return None, None

	key = propconfigKey(propPath)
	slot = pc.get(key)
	if isinstance(slot, dict):
		return slot, key

	bare = str(propPath).strip().strip(".")
	if bare != key:
		slot = pc.get(bare)
		if isinstance(slot, dict):
			return slot, bare

	parts = bare.split(".")
	if len(parts) > 1:
		cur = pc
		for p in parts[:-1]:
			if not isinstance(cur, dict) or p not in cur:
				return None, None
			cur = cur[p]
		slot = cur.get(parts[-1]) if isinstance(cur, dict) else None
		if isinstance(slot, dict):
			return slot, ".".join(parts)
	return None, None


def _pcSlotForWrite(node, propPath):
	"""Get or create the canonical propConfig slot, migrating a legacy
	unscoped flat key onto the scoped one so a view never carries both."""
	pc = node.get("propConfig")
	if not isinstance(pc, dict):
		pc = {}
		node["propConfig"] = pc

	key = propconfigKey(propPath)
	slot = pc.get(key)
	if isinstance(slot, dict):
		return slot, key

	bare = str(propPath).strip().strip(".")
	legacy = pc.get(bare) if bare != key else None
	if isinstance(legacy, dict):
		del pc[bare]
		pc[key] = legacy
		return legacy, key

	slot = {}
	pc[key] = slot
	return slot, key


def setPropconfig(data, name, propPath, value):
	"""Set propConfig["<scope>.<path>"] = value."""
	node, _ = findByName(data, name)
	if node is None:
		return {"ok": False, "error": "no child named %s" % name}
	pc = node.get("propConfig")
	if not isinstance(pc, dict):
		pc = {}
		node["propConfig"] = pc
	key = propconfigKey(propPath)
	pc[key] = value
	return {"ok": True, "node": node, "key": key}


def getPropconfig(data, name, propPath):
	"""Return the propConfig slot for a prop path, or None."""
	node, _ = findByName(data, name)
	if node is None:
		return None
	slot, _ = _pcFindSlot(node, propPath)
	return slot


def getBinding(data, targetName, propPath):
	"""Return the binding dict for a prop path, or None."""
	slot = getPropconfig(data, targetName, propPath)
	if isinstance(slot, dict) and isinstance(slot.get("binding"), dict):
		return slot["binding"]
	return None


def setBinding(data, targetName, propPath, bindingType, bindingConfig,
				transforms=None):
	"""Place a binding at propConfig["<scope>.<path>"].binding.

	Transforms are nested inside the binding, not beside it.
	"""
	node, _ = findByName(data, targetName)
	if node is None:
		return {"ok": False, "error": "no child named %s" % targetName}
	slot, key = _pcSlotForWrite(node, propPath)
	slot["binding"] = {"type": bindingType, "config": bindingConfig or {}}
	if transforms:
		slot["binding"]["transforms"] = transforms
	# An earlier version wrote transforms as a sibling of binding; drop the
	# stale copy so it cannot shadow the nested list.
	slot.pop("transforms", None)
	return {"ok": True, "node": node, "key": key}


def removeBinding(data, targetName, propPath):
	node, _ = findByName(data, targetName)
	if node is None:
		return {"ok": False, "error": "no child named %s" % targetName}
	slot, key = _pcFindSlot(node, propPath)
	if not isinstance(slot, dict):
		return {"ok": True, "removed": False}
	had = "binding" in slot
	slot.pop("binding", None)
	slot.pop("transforms", None)
	# Drop the slot entirely if nothing else was configured on it.
	pc = node.get("propConfig")
	if isinstance(pc, dict) and not slot and key in pc:
		del pc[key]
	return {"ok": True, "removed": had, "node": node, "key": key}


def addTransform(data, targetName, propPath, transformType, transformConfig):
	"""Append a transform to the binding at propConfig["<scope>.<path>"].

	A transform is only meaningful attached to a binding, so a missing binding
	is an error rather than a silently-created empty one.
	"""
	node, _ = findByName(data, targetName)
	if node is None:
		return {"ok": False, "error": "no child named %s" % targetName}
	slot, key = _pcFindSlot(node, propPath)
	if not isinstance(slot, dict) or not isinstance(slot.get("binding"), dict):
		return {"ok": False,
				"error": "no binding at propConfig[%r] on %s; a transform must "
						"attach to an existing binding"
						% (propconfigKey(propPath), targetName)}
	transforms = slot["binding"].setdefault("transforms", [])
	transforms.append({"type": transformType, "config": transformConfig or {}})
	return {"ok": True, "node": node, "key": key,
			"index": len(transforms) - 1, "transforms": transforms}


def removeTransform(data, targetName, propPath, index):
	node, _ = findByName(data, targetName)
	if node is None:
		return {"ok": False, "error": "no child named %s" % targetName}
	slot, key = _pcFindSlot(node, propPath)
	if not isinstance(slot, dict):
		return {"ok": False, "error": "no propConfig entry for %s"
										% propconfigKey(propPath)}
	transforms = (slot.get("binding") or {}).get("transforms") or []
	if index < 0 or index >= len(transforms):
		return {"ok": False,
				"error": "transform index %s out of range (%d present)"
						% (index, len(transforms))}
	transforms.pop(index)
	return {"ok": True, "remaining": transforms, "node": node, "key": key}


def setEvent(data, targetName, event, scope, config):
	"""Place an event handler. `scope` is a SIBLING of `config`, not nested."""
	node, _ = findByName(data, targetName)
	if node is None:
		return {"ok": False, "error": "no child named %s" % targetName}
	events = node.setdefault("events", {})
	handler = events.get(event)
	if not isinstance(handler, dict):
		handler = {}
		events[event] = handler
	handler["scope"] = scope  # "G" or "C"
	handler["config"] = config or {}
	return {"ok": True, "node": node}


def removeEvent(data, targetName, event):
	node, _ = findByName(data, targetName)
	if node is None:
		return {"ok": False, "error": "no child named %s" % targetName}
	events = node.get("events") or {}
	removed = event in events
	if removed:
		del events[event]
	return {"ok": True, "node": node, "removed": removed}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

# Position keys that make sense for each container type. Warnings only --
# Perspective tolerates extras, but a flex child given x/y is almost always a
# mistake the agent wants to hear about.
_POSITION_KEYS = {
	"ia.container.coord": ("x", "y", "width", "height", "rotate", "aspectRatio"),
	"ia.container.flex": ("grow", "shrink", "basis", "align", "order", "display"),
	"ia.container.breakpt": ("size",),
}

_PROPCONFIG_RESERVED = ("binding", "transforms", "persistent", "access",
						"paramDirection")


def validateView(data, project=None):
	"""Structural sanity-check a view.json dict.

	Checks shape, root presence, per-node type/meta.name, meta.name uniqueness,
	binding placement (propConfig, not props), known binding and transform
	types, event handler shape, and position keys against the parent container.

	Returns {ok, errors[], warnings[], suggestions[]}; ok is False on any error.
	"""
	errors, warnings, suggestions = [], [], []

	if not isinstance(data, dict):
		return {"ok": False, "errors": ["view_json is not a dict"],
				"warnings": [], "suggestions": []}

	root = viewRoot(data)
	if root is None:
		return {"ok": False,
				"errors": ["view.json has no 'root' and is not flat-shaped "
							"(no 'type' or 'children')"],
				"warnings": [], "suggestions": []}
	if "root" not in data:
		suggestions.append(
			"view.json stores the component tree flat at the top level; the "
			"canonical shape nests it under 'root' alongside custom/params/props")

	seen = {}

	def _checkPropconfig(pc, label):
		for k, v in pc.items():
			dotted = str(k)
			if dotted.split(".")[0] not in PROPCONFIG_SCOPES:
				errors.append(
					"%s: propConfig key %r is not scoped; propConfig is a flat "
					"map keyed by full path, e.g. %r"
					% (label, dotted, propconfigKey(dotted)))
			if not isinstance(v, dict):
				errors.append("%s: propConfig[%r] must be an object"
								% (label, dotted))
				continue
			binding = v.get("binding")
			if isinstance(binding, dict):
				bt = binding.get("type")
				if bt not in BINDING_TYPES:
					errors.append(
						"%s: propConfig[%r].binding has unknown type %r (expected "
						"one of %s)" % (label, dotted, bt, ", ".join(BINDING_TYPES)))
				cfg = binding.get("config")
				if cfg is not None and not isinstance(cfg, dict):
					errors.append("%s: propConfig[%r].binding.config must be an "
									"object" % (label, dotted))
				trs = binding.get("transforms")
				if trs is not None and not isinstance(trs, list):
					errors.append("%s: propConfig[%r].binding.transforms must be "
									"a list" % (label, dotted))
				else:
					for i, tr in enumerate(trs or []):
						if not isinstance(tr, dict):
							errors.append("%s: propConfig[%r] transform[%d] must "
											"be an object" % (label, dotted, i))
							continue
						if tr.get("type") not in TRANSFORM_TYPES:
							errors.append(
								"%s: propConfig[%r] transform[%d] has unknown type "
								"%r (expected one of %s)"
								% (label, dotted, i, tr.get("type"),
									", ".join(TRANSFORM_TYPES)))
			elif binding is not None:
				errors.append("%s: propConfig[%r].binding must be an object"
								% (label, dotted))
			if "transforms" in v:
				errors.append(
					"%s: propConfig[%r] has transforms beside binding; "
					"transforms nest inside the binding object"
					% (label, dotted))
			unknownNested = [nk for nk, nv in v.items()
								if nk not in _PROPCONFIG_RESERVED
								and isinstance(nv, dict)
								and ("binding" in nv or "transforms" in nv)]
			if unknownNested:
				errors.append(
					"%s: propConfig[%r] nests further prop levels (%s); flatten "
					"them into sibling keys like %r"
					% (label, dotted, ", ".join(sorted(unknownNested)),
						propconfigKey(dotted + "." + sorted(unknownNested)[0])))

	def _check(node, path, parentType):
		if not isinstance(node, dict):
			errors.append("%s is not a dict" % path)
			return
		ntype = node.get("type")
		nname = (node.get("meta") or {}).get("name")
		if not ntype:
			warnings.append("%s missing 'type'" % path)
		if not nname:
			warnings.append("%s missing meta.name" % path)
		elif nname in seen:
			errors.append("duplicate meta.name %r (also at %s)" % (nname, seen[nname]))
		else:
			seen[nname] = path

		label = nname or path

		# Bindings belong under propConfig, never inline in props.
		props = node.get("props")
		if isinstance(props, dict):
			for k, v in props.items():
				if isinstance(v, dict) and v.get("type") in BINDING_TYPES \
						and "config" in v:
					errors.append(
						"%s: props.%s looks like a binding placed inline; move it "
						"to propConfig.%s.binding" % (label, k, k))

		pc = node.get("propConfig")
		if pc is not None and not isinstance(pc, dict):
			errors.append("%s: propConfig must be an object" % label)
		elif isinstance(pc, dict):
			_checkPropconfig(pc, label)

		events = node.get("events")
		if events is not None and not isinstance(events, dict):
			errors.append("%s: events must be an object" % label)
		elif isinstance(events, dict):
			for ev, handler in events.items():
				if not isinstance(handler, dict):
					errors.append("%s: events.%s must be an object" % (label, ev))
					continue
				scope = handler.get("scope")
				cfg = handler.get("config")
				if isinstance(cfg, dict) and "scope" in cfg:
					errors.append(
						"%s: events.%s has 'scope' nested inside 'config'; scope "
						"is a sibling of config" % (label, ev))
				elif scope is None:
					warnings.append("%s: events.%s missing 'scope' (G or C)"
									% (label, ev))
				if scope is not None and scope not in ("G", "C"):
					errors.append("%s: events.%s scope must be 'G' or 'C', got %r"
									% (label, ev, scope))

		pos = node.get("position")
		if pos is not None and not isinstance(pos, dict):
			errors.append("%s: position must be an object" % label)
		elif isinstance(pos, dict) and parentType in _POSITION_KEYS:
			allowed = _POSITION_KEYS[parentType]
			for k in pos.keys():
				if k not in allowed:
					warnings.append(
						"%s: position.%s is not meaningful inside a %s parent "
						"(expected one of %s)"
						% (label, k, parentType, ", ".join(allowed)))

		kids = node.get("children")
		if kids is not None and not isinstance(kids, list):
			errors.append("%s: children must be a list" % label)
		else:
			for i, child in enumerate(kids or []):
				_check(child, "%s.children[%d]" % (path, i), ntype)

	_check(root, "root", None)
	return {"ok": not errors, "errors": errors, "warnings": warnings,
			"suggestions": suggestions}


def validateChildAdd(data, parentName, name, componentType, props=None,
						position=None):
	"""Pre-flight a child insertion against the loaded view.

	Returns {ok, errors[], warnings[], suggestions[]}. Errors mean the write
	would produce an invalid view and should be refused.
	"""
	errors, warnings, suggestions = [], [], []

	root = viewRoot(data)
	if root is None:
		return {"ok": False,
				"errors": ["view.json has no recognizable component tree root"],
				"warnings": [], "suggestions": []}

	if not name:
		errors.append("name is required")
	elif nameExists(data, name):
		errors.append("duplicate meta.name: %r already exists in this view" % name)

	if not componentType:
		errors.append("componentType is required")
	elif "." not in str(componentType):
		errors.append("componentType %r is not a qualified type (expected "
						"something like 'ia.display.label')" % componentType)

	parent = root
	if parentName and parentName != "root":
		parent, _ = findByName(data, parentName)
		if parent is None:
			known = ", ".join(sorted(collectNames(data))) or "<none>"
			errors.append("no parent named %r; existing names: %s"
							% (parentName, known))

	if parent is not None:
		ptype = parent.get("type")
		if ptype and ptype not in CONTAINER_TYPES \
				and not str(ptype).startswith("ia.container."):
			warnings.append("parent %r is a %s, which is not a container; it may "
							"not render children" % (parentName or "root", ptype))
		if isinstance(position, dict) and position and ptype in _POSITION_KEYS:
			allowed = _POSITION_KEYS[ptype]
			unexpected = [k for k in position.keys() if k not in allowed]
			if unexpected:
				warnings.append("position keys %s are not meaningful inside a %s "
								"parent (expected one of %s)"
								% (", ".join(unexpected), ptype, ", ".join(allowed)))
		elif not position and ptype == "ia.container.coord":
			suggestions.append("a coordinate-container child usually needs "
								"position {x, y, width, height}")

	if props is not None and not isinstance(props, dict):
		errors.append("props must be an object")
	elif isinstance(props, dict):
		for k, v in props.items():
			if isinstance(v, dict) and v.get("type") in BINDING_TYPES \
					and "config" in v:
				errors.append("props.%s looks like a binding; add the component "
								"first, then bind it with viewSetBinding" % k)

	return {"ok": not errors, "errors": errors, "warnings": warnings,
			"suggestions": suggestions}


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

def pageConfigPath(project):
	return "{root}/{p}/{dir}/config.json".format(
		root=projectRoot(), p=project, dir=PAGE_CONFIG_DIR
	)


def loadPageConfig(project):
	cfg = safeLoad(pageConfigPath(project), default={"pages": {}})
	if not isinstance(cfg, dict):
		return {"pages": {}}
	return cfg


def savePageConfig(project, cfg):
	safeWrite(pageConfigPath(project), cfg)


def upsertPage(project, alias, viewPath, title=None):
	"""Read-modify-write a page entry without dropping sibling keys."""
	cfg = loadPageConfig(project)
	pages = cfg.get("pages")
	if not isinstance(pages, dict):
		pages = {}
		cfg["pages"] = pages
	entry = pages.get(alias)
	if not isinstance(entry, dict):
		entry = {}
	entry["viewPath"] = viewPath
	if title is not None:
		entry["title"] = title
	pages[alias] = entry
	savePageConfig(project, cfg)
	return cfg


def removePage(project, alias):
	"""Remove a page entry. Returns (config, removed)."""
	cfg = loadPageConfig(project)
	pages = cfg.get("pages") or {}
	removed = alias in pages
	if removed:
		del pages[alias]
		savePageConfig(project, cfg)
	return cfg, removed


# ---------------------------------------------------------------------------
# Stylesheet + style classes
# ---------------------------------------------------------------------------
# saveStylesheet accepts either raw CSS text (written verbatim, which is what
# Perspective's styles/stylesheet.css actually holds) or a dict (serialized as
# JSON). The dict path is retained for the styleClass* tools, which model a
# sheet as {"classes": {...}} -- that JSON-in-a-.css-file representation is not
# what the gateway parses, so those tools are structured bookkeeping only.

def stylesheetPath(project, name=None):
	base = "{root}/{p}/{dir}".format(
		root=projectRoot(), p=project, dir=STYLESHEET_DIR)
	if name:
		return base + "/" + name
	return base


def loadStylesheet(project, name):
	return safeLoad(stylesheetPath(project, name), default={})


def loadStylesheetText(project, name):
	"""Raw file contents of a stylesheet, or None if missing."""
	return readText(stylesheetPath(project, name))


def saveStylesheet(project, name, data):
	safeWrite(stylesheetPath(project, name), data)


def listStylesheets(project):
	base = stylesheetPath(project)
	if not isDir(base):
		return []
	out = []
	for f in _listDir(base):
		if str(f).endswith(".css"):
			out.append(str(f))
	return out


def collectStyleClasses(stylesheets):
	"""Class names defined across a set of parsed stylesheets."""
	out = []
	for entry in stylesheets:
		if not isinstance(entry, dict):
			continue
		for cn in (entry.get("classes") or {}).keys():
			out.append(cn)
	return out


# ---------------------------------------------------------------------------
# Named sessions
# ---------------------------------------------------------------------------

def namedSessionDir(project):
	return "{root}/{p}/{dir}".format(
		root=projectRoot(), p=project, dir=NAMED_SESSION_DIR)


def namedSessionPath(project, name):
	return namedSessionDir(project) + "/" + str(name)


def listNamedSessions(project):
	base = namedSessionDir(project)
	if not isDir(base):
		return []
	return [str(e) for e in _listDir(base)]


def loadNamedSession(project, name):
	return safeLoad(namedSessionPath(project, name) + "/session.json",
					default={})


def saveNamedSession(project, name, data):
	safeWrite(namedSessionPath(project, name) + "/session.json", data)


def deleteNamedSession(project, name):
	return deletePath(namedSessionPath(project, name))


# ---------------------------------------------------------------------------
# View-component tree helpers
# ---------------------------------------------------------------------------

def newComponent(componentType, name, props=None, custom=None, position=None):
	"""Build a minimal component dict. The caller passes the props it wants;
	we scaffold the meta block and the standard fields."""
	return {
		"type": componentType,
		"meta": {"name": name},
		"props": props or {},
		"custom": custom or {},
		"position": position or {},
	}


def addChild(data, parentName, child):
	"""Append child to parent (or the tree root if parentName is 'root'/None).

	meta.name uniqueness is enforced here -- it is the handle bindings and
	scripts use, so a duplicate silently breaks the view.
	"""
	root = viewRoot(data)
	if root is None:
		return {"ok": False,
				"error": "view.json has no recognizable component tree root"}
	childName = (child.get("meta") or {}).get("name") \
		if isinstance(child, dict) else None
	if childName and nameExists(data, childName):
		return {"ok": False,
				"error": "duplicate meta.name: %r already exists in this view"
						% childName}
	if parentName == "root" or parentName is None:
		root.setdefault("children", []).append(child)
		return {"ok": True, "parent": root,
				"parent_name": (root.get("meta") or {}).get("name")}
	parent, _ = findByName(data, parentName)
	if parent is None:
		return {"ok": False, "error": "no parent named %s" % parentName}
	parent.setdefault("children", []).append(child)
	return {"ok": True, "parent": parent, "parent_name": parentName}


def moveChild(data, name, newParentName, newPosition=None):
	root = viewRoot(data)
	if root is None:
		return {"ok": False,
				"error": "view.json has no recognizable component tree root"}
	node, _ = findByName(data, name)
	if node is None:
		return {"ok": False, "error": "no child named %s" % name}
	oldParent = parentOf(data, name)
	if oldParent is None:
		return {"ok": False,
				"error": "%s is the view root and cannot be moved" % name}
	if newParentName == "root" or newParentName is None:
		newParent = root
	else:
		newParent, _ = findByName(data, newParentName)
		if newParent is None:
			return {"ok": False, "error": "no new parent named %s" % newParentName}
	# Reparenting a node into its own subtree would detach it from the tree.
	if _containsNode(node, newParent):
		return {"ok": False, "error": "cannot move %s into its own subtree" % name}
	if newPosition is not None:
		node["position"] = newPosition
	oldParent["children"] = [
		c for c in (oldParent.get("children") or [])
		if not (isinstance(c, dict) and (c.get("meta") or {}).get("name") == name)]
	newParent.setdefault("children", []).append(node)
	return {"ok": True, "node": node}


def renameNode(data, oldName, newName):
	if not newName:
		return {"ok": False, "error": "newName is required"}
	if nameExists(data, newName):
		return {"ok": False, "error": "name %s already exists" % newName}
	node, _ = findByName(data, oldName)
	if node is None:
		return {"ok": False, "error": "no child named %s" % oldName}
	node.setdefault("meta", {})["name"] = newName
	return {"ok": True, "node": node}


# ---------------------------------------------------------------------------
# Tool-runner envelope
# ---------------------------------------------------------------------------

def run(intent, fn, *args, **kwargs):
	"""Standard envelope: never throw, return {ok, ...} on success or failure."""
	try:
		if intent is None or (isinstance(intent, basestring) and not intent.strip()):
			return {"ok": False,
					"error": "missing intent: pass a short reason for this call"}
		result = fn(*args, **kwargs)
		if isinstance(result, dict):
			result.setdefault("ok", True)
			return result
		return {"ok": True, "result": result}
	except:
		# Bare except: fn usually calls system.*, whose Java exceptions
		# "except Exception" would let escape the envelope
		info = sys.exc_info()
		logger.warn("%s failed: %s" % (intent, info[1]))
		name = getattr(info[0], "__name__", str(info[0]))
		try:
			trace = traceback.format_exc()
		except Exception:
			trace = None
		return {
			"ok": False,
			"error": "%s: %s" % (name, info[1]),
			"trace": trace,
		}
