"""Bounded live tag reads and browses for the AI agent tools.

Backs read_tag_values, browse_tags, tagRead, tagBrowse and tagProviders. The
last three used to return str() of the Java result, which a model had to parse
out of "<PyWrapper>: [{u'fullPath': [default]..." text; they now return the same
structured JSON the snake_case tools do. Every entry point caps how much one
call can read.
"""
import sys

import exchange.aiTools.serialize
import exchange.aiTools.tagPaths

logger = system.util.getLogger("exchange.aiTools.TagAccess")

# Tag paths per read. readBlocking is one round trip regardless, but the
# response goes into a model's context
MAX_READ_PATHS = 50

# Results per browse. A browse is one folder level unless the caller asks for
# recursion, and either way its result is bounded here
MAX_BROWSE_RESULTS = 500

READ_TIMEOUT_MS = 10000


def _capPaths(paths):
	"""Split paths into (kept, dropped) at MAX_READ_PATHS."""
	return paths[:MAX_READ_PATHS], paths[MAX_READ_PATHS:]


def _qualifiedValueEntry(path, qv):
	"""Shape one QualifiedValue as {path, value, quality, good, timestamp}."""
	value = qv.value
	if value is not None and exchange.aiTools.serialize.isDate(value):
		value = exchange.aiTools.serialize.isoDate(value)
	else:
		value = exchange.aiTools.serialize.jsonSafe(value)
	timestamp = qv.timestamp
	return {
		"path": path,
		"value": value,
		"quality": unicode(qv.quality),
		"good": bool(qv.quality.isGood()),
		"timestamp": exchange.aiTools.serialize.isoDate(timestamp) if timestamp is not None else None
	}


def readValues(paths):
	"""Read live values for a bounded list of tag paths.

	Args:
		paths (list): Tag paths, already parsed. Only the first MAX_READ_PATHS
			are read.

	Returns:
		dict: {count, values: [{path, value, quality, good, timestamp}]} plus a
			notice naming any paths dropped by the cap.
	"""
	kept, dropped = _capPaths(paths)
	try:
		qvs = system.tag.readBlocking(kept, READ_TIMEOUT_MS)
	except:
		logger.warn("readBlocking failed for %d paths: %s" % (len(kept), sys.exc_info()[1]))
		raise
	values = [_qualifiedValueEntry(kept[i], qvs[i]) for i in range(len(kept))]
	result = {"count": len(values), "values": values}
	if dropped:
		result["notice"] = ("Only the first %d paths were read; %d more were dropped. "
			"Split them across several calls." % (MAX_READ_PATHS, len(dropped)))
	return result


def readTagValues(tagPaths):
	"""Entry point for read_tag_values: parse a tag_paths string and read it.

	Args:
		tagPaths (object): Comma-separated paths or a JSON array string. A
			missing [provider] prefix is assumed [default].

	Returns:
		dict: See readValues.

	Raises:
		ValueError: If tagPaths is empty.
	"""
	if tagPaths is None or not unicode(tagPaths).strip():
		raise ValueError("tag_paths is required (comma-separated paths or a JSON array string)")
	return readValues(exchange.aiTools.tagPaths.parseTagPaths(tagPaths, defaultProvider="default"))


def readTagList(tagPaths):
	"""Entry point for tagRead: accepts a list, a JSON array string or a CSV string.

	Paths are passed through as given (no default provider is added), matching
	what tagRead has always done.

	Args:
		tagPaths (object): A list of paths, or a string parseTagPaths accepts.

	Returns:
		dict: See readValues, or {error} when no path was supplied.
	"""
	if tagPaths is None:
		paths = []
	elif isinstance(tagPaths, basestring):
		paths = exchange.aiTools.tagPaths.parseTagPaths(tagPaths)
	else:
		paths = [unicode(p).strip() for p in tagPaths if p is not None and unicode(p).strip()]
	if not paths:
		return {"error": "tagPaths is required: an array of tag path strings.", "count": 0, "values": []}
	return readValues(paths)


def _browseEntry(item):
	"""Shape one browse result as a JSON-safe dict of every key it carries."""
	entry = {}
	try:
		keys = list(item.keys())
	except:
		keys = ["name", "fullPath", "hasChildren", "tagType", "dataType", "typeId", "valueSource"]
	for key in keys:
		value = item.get(key)
		if value is None:
			continue
		if hasattr(value, "getQuality") and hasattr(value, "getValue"):
			value = {"value": exchange.aiTools.serialize.jsonSafe(value.getValue()), "quality": unicode(value.getQuality())}
		elif isinstance(value, bool):
			pass
		else:
			value = exchange.aiTools.serialize.jsonSafe(value)
		entry[unicode(key)] = value
	if "hasChildren" in entry:
		entry["hasChildren"] = bool(entry["hasChildren"])
	return entry


def browse(path, tagFilter=None):
	"""Browse one tag path with a bounded result count.

	Args:
		path (str): Folder, UDT instance or provider to browse, e.g. "[default]Line1".
		tagFilter (dict): system.tag.browse filter. maxResults is clamped to
			MAX_BROWSE_RESULTS and set when absent.

	Returns:
		dict: {path, count, results, truncated}.
	"""
	browseFilter = dict(tagFilter or {})
	try:
		requested = int(browseFilter.get("maxResults") or MAX_BROWSE_RESULTS)
	except:
		requested = MAX_BROWSE_RESULTS
	browseFilter["maxResults"] = max(1, min(requested, MAX_BROWSE_RESULTS))
	try:
		results = system.tag.browse(path, browseFilter)
	except:
		logger.warn("tag.browse failed for %s: %s" % (path, sys.exc_info()[1]))
		raise
	entries = [_browseEntry(item) for item in results.getResults()]
	return {
		"path": path,
		"count": len(entries),
		"results": entries,
		"truncated": len(entries) >= browseFilter["maxResults"],
	}


def browseChildren(path):
	"""Entry point for browse_tags: one level of children in its compact shape.

	Args:
		path (str): Path to browse. Blank means [default]; a missing
			[provider] prefix is assumed [default].

	Returns:
		dict: {path, count, children: [{name, fullPath, hasChildren, tagType,
			dataType}]} plus truncated: True when the cap was hit.
	"""
	if path is None or not unicode(path).strip():
		path = "[default]"
	path = unicode(path).strip()
	if not path.startswith("["):
		path = "[default]" + path

	try:
		results = system.tag.browse(path, {"maxResults": MAX_BROWSE_RESULTS})
	except:
		logger.warn("tag.browse failed for %s: %s" % (path, sys.exc_info()[1]))
		raise

	children = []
	for item in results.getResults():
		children.append({
			"name": item.get("name"),
			"fullPath": unicode(item.get("fullPath")),
			"hasChildren": bool(item.get("hasChildren")),
			"tagType": unicode(item.get("tagType")) if item.get("tagType") is not None else None,
			"dataType": unicode(item.get("dataType")) if item.get("dataType") is not None else None
		})
	result = {"path": path, "count": len(children), "children": children}
	if len(children) >= MAX_BROWSE_RESULTS:
		result["truncated"] = True
	return result


def browseProviders():
	"""List the tag providers on this gateway.

	Returns:
		dict: {count, providers: [{name, fullPath, tagType, hasChildren}]}.
	"""
	listing = browse("", {})
	return {"count": listing["count"], "providers": listing["results"]}
