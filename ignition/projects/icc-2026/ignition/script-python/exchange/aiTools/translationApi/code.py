"""Allow-listed translation API access for the Translation Manager Agent.

Backs the systemCall and systemList tools. systemCall used to resolve any dotted
path under system.* and call it, which gave the agent the whole scripting API --
tag writes, project and config edits, user management. The translation workflow
needs five functions, so those are the only five it can reach.

Lookup is an exact match against ALLOW_LIST, never a getattr walk over the
agent's string, so a path like "util.translate.__class__" cannot reach anything
the list does not name. ALLOW_LIST is the single declaration both tools read.
"""
import sys

logger = system.util.getLogger("exchange.aiTools.TranslationApi")

# (group, function, access, usage), in the order systemList reports them
ALLOW_LIST = [
	("util", "translate", "read", "translate(term, locale) -- look up a term's translation."),
	("util", "modifyTranslation", "translation-write", "modifyTranslation(term, translation, locale) -- add or correct one term."),
	("i18n", "translate", "read", "translate([terms], locale) -- look up several terms; returns {term: translation}."),
	("i18n", "listKeys", "read", "listKeys() -- the registered translation terms."),
	("i18n", "modifyTranslations", "translation-write", "modifyTranslations(values={term: translation}, locale=...) -- add or correct terms in bulk."),
]


def allowedNames():
	"""Return the allow-listed dotted names, sorted, e.g. ["i18n.listKeys", ...]."""
	return sorted(["%s.%s" % (group, name) for group, name, _, _ in ALLOW_LIST])


def serialize(value):
	"""Recursively coerce a return value to JSON-safe types.

	Args:
		value (object): Any value returned by a system.* call.

	Returns:
		object: None / bool / number / string / list / dict, with repr() for
			anything Java-backed.
	"""
	if value is None or isinstance(value, bool):
		return value
	if isinstance(value, (int, long, float, basestring)):
		return value
	if isinstance(value, (list, tuple)):
		return [serialize(item) for item in value]
	if isinstance(value, dict):
		return dict((str(key), serialize(item)) for key, item in value.items())
	# Java collections (e.g. a key list) arrive as java.util types
	try:
		from java.util import Collection
		if isinstance(value, Collection):
			return [serialize(item) for item in value]
	except:
		pass
	return repr(value)


def callAllowed(function, args=None, kwargs=None):
	"""Invoke one allow-listed translation function.

	Args:
		function (str): Dotted name under system.*, e.g. "util.translate". The
			"system." prefix is optional.
		args (list): Positional arguments. A single dict is treated as kwargs,
			because the tool-call protocol tends to deliver keyword-only
			parameters that way.
		kwargs (dict): Keyword arguments.

	Returns:
		dict: {ok, result, error}, plus allowed on a refusal so the agent can
			correct itself.
	"""
	out = {"ok": False, "result": None, "error": None}

	if not isinstance(function, basestring) or not function.strip():
		out["error"] = "'function' must be a non-empty string"
		out["allowed"] = allowedNames()
		return out

	path = function.strip()
	if path.startswith("system."):
		path = path[len("system."):]

	if path not in allowedNames():
		logger.warn("Refused system.%s -- not on the translation allow-list" % path)
		out["error"] = ("system.%s is not allowed. This tool only reaches the translation "
			"functions listed in 'allowed'; use tagRead / tagBrowse for tag data." % path)
		out["allowed"] = allowedNames()
		return out

	if args is None:
		args = []
	if kwargs is None:
		kwargs = {}
	if not isinstance(args, (list, tuple)):
		out["error"] = "'args' must be a list"
		return out
	if not isinstance(kwargs, dict):
		out["error"] = "'kwargs' must be an object"
		return out

	# Resolve exactly two attribute hops, both taken from the allow-list key
	groupName, funcName = path.split(".", 1)
	try:
		target = getattr(getattr(system, groupName), funcName)
	except:
		logger.warn("system.%s is allow-listed but did not resolve on this gateway" % path)
		out["error"] = "system.%s is not available on this gateway" % path
		return out

	if not kwargs and len(args) == 1 and isinstance(args[0], dict):
		kwargs = dict(args[0])
		args = []

	try:
		out["result"] = serialize(target(*args, **kwargs))
		out["ok"] = True
	except:
		errType, errValue = sys.exc_info()[:2]
		logger.warn("system.%s failed: %s" % (path, errValue))
		out["error"] = "%s: %s" % (getattr(errType, "__name__", str(errType)), errValue)
	return out


def listAllowed(prefix=None):
	"""List the allow-listed functions that resolve on this gateway.

	Args:
		prefix (str): Optional case-insensitive filter on the group name, e.g.
			"util" or "i18n".

	Returns:
		dict: {ok, result, error}. result maps each group to a list of
			{name, access, usage}.
	"""
	out = {"ok": False, "result": None, "error": None}
	filterText = (prefix or "").strip().lower()
	if filterText.startswith("system."):
		filterText = filterText[len("system."):]

	found = {}
	for groupName, funcName, access, usage in ALLOW_LIST:
		if filterText and not groupName.lower().startswith(filterText):
			continue
		# Only list what resolves here, so the agent never plans around a ghost
		try:
			getattr(getattr(system, groupName), funcName)
		except:
			logger.debug("system.%s.%s not available; omitted" % (groupName, funcName))
			continue
		found.setdefault(groupName, []).append({"name": funcName, "access": access, "usage": usage})

	out["result"] = found
	out["ok"] = True
	return out


def discoverAndRegister(viewPath, targetLocale, pageUrl=None, pageParams=None, viewParams=None):
	"""Run exchange.aiTools.translator.scan.discoverAndRegister, never raising.

	Backs the translationDiscoverAndRegister tool. A failure comes back in the
	same shape as a success, with the error under failed, so the agent can
	quote it.

	Args:
		viewPath (str): Root Perspective view path.
		targetLocale (str): Locale to register, e.g. "es-MX".
		pageUrl (str): Page URL, passed through for the report.
		pageParams (dict): Page params, passed through.
		viewParams (dict): Root view params, passed through.

	Returns:
		dict: {rootViewPath, targetLocale, found, added, alreadyPresent, failed,
			viewsVisited, unresolvedViews, ...}.
	"""
	import exchange.aiTools.translator.scan
	try:
		return exchange.aiTools.translator.scan.discoverAndRegister(
			viewPath, targetLocale, pageUrl, pageParams or {}, viewParams or {})
	except:
		# Bare except: the scan makes system.util / system.ai calls, whose Java
		# exceptions "except Exception" does not catch in Jython
		errType, errValue = sys.exc_info()[:2]
		logger.warn("discoverAndRegister failed for %s -> %s: %s" % (viewPath, targetLocale, errValue))
		return {
			"rootViewPath": viewPath,
			"targetLocale": targetLocale,
			"found": [],
			"added": [],
			"alreadyPresent": [],
			"failed": [{"error": "%s: %s" % (getattr(errType, "__name__", str(errType)), str(errValue))}],
			"viewsVisited": [],
			"unresolvedViews": []
		}
