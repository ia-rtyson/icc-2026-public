"""View and tag-reference inspection for the Report Issue / Validate / Implement agents.

Backs get_view_json, get_component_bindings, diagnose_tag_reference and
set_view_custom_property. The view reading, binding extraction, tag diagnosis
and the guarded write all live in exchange.issueReport.report; this module adds the argument
handling and the plain-language verdicts the agents quote.
"""
import sys

import exchange.issueReport.pipeline
import exchange.issueReport.report
import exchange.aiTools.tagPaths

logger = system.util.getLogger("exchange.aiTools.ViewInspect")

_MODES = ("tree", "full")

_BINDINGS_HINT = ("Any path under 'tagReferences' or 'resolvedTagPath' can be handed "
	"straight to diagnose_tag_reference to check whether it actually exists.")


def _requireViewPath(viewPath):
	"""Return the trimmed view path, raising the tools' standard error when blank."""
	if viewPath is None or not unicode(viewPath).strip():
		raise ValueError("view_path is required, e.g. 'Exchange/Report Issue Agent/Line Overview'")
	return unicode(viewPath).strip()


def _componentBase(componentPath):
	"""Normalise a component path so it always starts at root."""
	base = unicode(componentPath or "root").strip().strip("/") or "root"
	if not base.startswith("root"):
		base = "root/" + base
	return base


def viewJson(viewPath, componentPath=None, mode=None):
	"""Read a Perspective view's saved definition, optionally one subtree.

	Returns the saved resource, not runtime state.

	Args:
		viewPath (str): Designer view path, e.g. "Exchange/Report Issue Agent/Line Overview".
		componentPath (str): Slash-separated meta.name chain; defaults to root.
		mode (str): "tree" (default) for a flat component map, "full" for raw JSON.

	Returns:
		dict: The get_view_json payload, or {error, available_views} for an
			unknown view, or {error, view, component_tree} for an unknown component.

	Raises:
		ValueError: If viewPath is blank or mode is not tree/full.
	"""
	resolvedMode = unicode(mode or "tree").strip().lower()
	if viewPath is None or not unicode(viewPath).strip():
		raise ValueError("view_path is required, e.g. 'Exchange/Report Issue Agent/Line Overview'")
	if resolvedMode not in _MODES:
		raise ValueError("mode must be 'tree' or 'full' (got '%s')" % resolvedMode)
	resolvedPath = unicode(viewPath).strip()

	try:
		doc = exchange.issueReport.report.loadViewJson(resolvedPath)
	except IOError:
		# Wrong path is the common failure -- hand back the real list so the
		# agent can retry in the same turn instead of giving up
		logger.info("get_view_json: no view at '%s'" % resolvedPath)
		return {"error": "View '%s' not found." % resolvedPath, "available_views": exchange.issueReport.report.listViews()}

	base = _componentBase(componentPath)
	try:
		node = exchange.issueReport.report.getComponent(doc, base)
	except ValueError, error:
		return {
			"error": str(error),
			"view": resolvedPath,
			"component_tree": exchange.issueReport.report.componentTree(doc.get("root") or {})
		}

	result = {
		"view": resolvedPath,
		"component": base,
		"view_params": doc.get("params") or {},
		"view_custom": doc.get("custom") or {},
	}
	if resolvedMode == "tree":
		result["mode"] = "tree"
		result["components"] = exchange.issueReport.report.componentTree(node, prefix=base)
		result["hint"] = "Call again with mode='full' and a component_path to see a subtree's raw JSON."
	else:
		result["mode"] = "full"
		result["json"] = node
	return result


def componentBindings(viewPath, componentPath=None, includeDescendants=None):
	"""Read the bindings on a component, with indirect tag paths resolved.

	Indirect tag bindings are resolved against the view's saved custom/param
	values, so the caller sees the literal tag path the binding will request --
	which is usually where the defect is.

	Args:
		viewPath (str): Designer view path.
		componentPath (str): Component path; defaults to the view root.
		includeDescendants (object): Also walk children when truthy.

	Returns:
		dict: exchange.issueReport.report.getBindings' result plus resolved paths and a hint, or
			{error, available_views} / {error, hint}.

	Raises:
		ValueError: If viewPath is blank.
	"""
	resolvedPath = _requireViewPath(viewPath)
	descend = bool(includeDescendants) if includeDescendants is not None else False

	try:
		info = exchange.issueReport.report.getBindings(resolvedPath, componentPath, includeDescendants=descend)
	except IOError:
		logger.info("get_component_bindings: no view at '%s'" % resolvedPath)
		return {"error": "View '%s' not found." % resolvedPath, "available_views": exchange.issueReport.report.listViews()}
	except ValueError, error:
		return {"error": str(error), "hint": "Call get_view_json with mode='tree' to see the real component paths."}

	for binding in info["bindings"]:
		if binding.get("type") == "tag" and binding.get("mode") == "indirect":
			resolved, unresolved = exchange.issueReport.report.resolveIndirectTagPath(
				binding.get("tagPathTemplate"), binding.get("references"),
				info.get("viewCustom"), info.get("viewParams"))
			binding["resolvedTagPath"] = resolved
			binding["unresolvedReferences"] = unresolved
			if not unresolved:
				binding["tagReferences"] = [resolved]

	info["hint"] = _BINDINGS_HINT
	return info


def _verdict(result):
	"""Spell out what a broken path's diagnosis implies, so the agent quotes evidence."""
	if result.get("parentExists") and result.get("suggestions"):
		best = result["suggestions"][0]
		return ("'%s' does not exist, but its parent folder does and contains '%s' "
			"(edit distance %d). This is consistent with a typo in the tag path."
			% (result["path"], best["name"], best["distance"]))
	if result.get("parentExists"):
		return ("'%s' does not exist. The parent folder exists but contains no similarly "
			"named tag, so the tag is likely missing rather than misspelled." % result["path"])
	return ("'%s' does not exist and neither does its parent folder -- suspect a wrong "
		"folder, a wrong tag provider, or a provider that is offline." % result["path"])


def diagnoseTagReferences(tagPaths):
	"""Check whether tag paths resolve, and suggest the intended tag when not.

	Args:
		tagPaths (object): Comma-separated paths or a JSON array string.

	Returns:
		dict: {count, broken_count, results, verdicts}.

	Raises:
		ValueError: If tagPaths is empty.
	"""
	if tagPaths is None or not unicode(tagPaths).strip():
		raise ValueError("tag_paths is required (comma-separated paths or a JSON array string)")
	paths = exchange.aiTools.tagPaths.parseTagPaths(tagPaths)

	results = []
	for path in paths:
		try:
			results.append(exchange.issueReport.report.diagnoseTagPath(path))
		except:
			# Bare except: a Java exception from system.tag.* would escape
			# "except Exception" in Jython
			error = sys.exc_info()[1]
			logger.warn("diagnoseTagPath failed for %s: %s" % (path, error))
			results.append({"path": path, "error": str(error)})

	broken = [r for r in results if not r.get("exists")]
	return {
		"count": len(results),
		"broken_count": len(broken),
		"results": results,
		"verdicts": [_verdict(r) for r in broken],
	}


def setViewCustomProperty(viewPath, propertyName, newValue, expectedCurrentValue, confirm):
	"""Change one entry in a view's top-level custom object, guarded.

	Without confirm this is a dry run that shows the diff and proves the guard
	holds; with confirm it writes through exchange.issueReport.report.setViewCustomProperty and
	requests a project scan so the running session picks the change up.

	Args:
		viewPath (str): Designer view path.
		propertyName (str): Key in the view's custom object.
		newValue (object): Value to write.
		expectedCurrentValue (object): What the caller believes is there now.
		confirm (object): Truthy to write; otherwise dry run.

	Returns:
		dict: {status: "pending_confirmation" | "guard_failed" | "error" |
			"applied" | "no_change", ...}.

	Raises:
		ValueError: If a required argument is missing.
	"""
	resolvedPath = _requireViewPath(viewPath)
	if propertyName is None or not unicode(propertyName).strip():
		raise ValueError("property_name is required")
	if newValue is None:
		raise ValueError("new_value is required")
	if expectedCurrentValue is None or not unicode(expectedCurrentValue).strip():
		raise ValueError(
			"expected_current_value is required. State the value you believe you are "
			"replacing -- read it with get_view_json first. This is what stops a stale "
			"ticket overwriting something that has since changed.")
	name = unicode(propertyName).strip()

	if not confirm:
		doc = exchange.issueReport.report.loadViewJson(resolvedPath)
		custom = doc.get("custom") or {}
		if name not in custom:
			return {
				"status": "error",
				"reason": "View '%s' has no custom property '%s'." % (resolvedPath, name),
				"available": sorted(custom.keys()),
			}
		actual = custom[name]
		matches = unicode(actual) == unicode(expectedCurrentValue)
		return {
			"status": "pending_confirmation" if matches else "guard_failed",
			"view": resolvedPath,
			"property": name,
			"current_value": actual,
			"expected_current_value": expectedCurrentValue,
			"proposed_value": newValue,
			"guard_ok": matches,
			"message": ("Nothing written yet. Show this diff, get agreement, then call again "
				"with confirm=true.") if matches
				else ("The property does not hold the value you expected. Do NOT retry "
					"with confirm=true -- re-read the resource and work out why."),
		}

	result = exchange.issueReport.report.setViewCustomProperty(
		viewPath=resolvedPath, name=name, value=newValue, expectedCurrent=expectedCurrentValue)

	# The gateway holds the old resource in memory until it re-reads from disk
	if result.get("changed"):
		exchange.issueReport.pipeline.requestScan()
		result["reloaded"] = True
		logger.info("set_view_custom_property wrote %s.custom.%s" % (resolvedPath, name))
	result["status"] = "applied" if result.get("changed") else "no_change"
	return result
