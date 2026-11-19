"""JSON-safe conversion shared by the AI agent tool bundles.

Tool results go back to the model through system.util.jsonEncode, which cannot
encode a java.util.Date, a Map, or most other Java values a system.* call
returns. Every tool used to carry its own copy of this conversion; this is the
one copy.
"""

logger = system.util.getLogger("exchange.aiTools.Serialize")

ISO_FORMAT = "yyyy-MM-dd'T'HH:mm:ss.SSS"

# Recursion ceiling for jsonSafe; anything nested deeper is stringified
MAX_DEPTH = 20


def isDate(value):
	"""Return True for a java.util.Date or Timestamp, but not for a Map.

	Args:
		value (object): Any value.

	Returns:
		bool: True when the value behaves like a Java date.
	"""
	return hasattr(value, "getTime") and not hasattr(value, "keySet")


def isoDate(value):
	"""Format a Java date as an ISO-8601 local timestamp with milliseconds.

	Args:
		value (Date): The date to format.

	Returns:
		unicode: For example 2026-09-30T09:52:57.283. Falls back to unicode(value)
			when the value cannot be formatted.
	"""
	try:
		return system.date.format(value, ISO_FORMAT)
	except:
		return unicode(value)


def jsonSafe(obj, depth=0):
	"""Recursively convert a value into types system.util.jsonEncode accepts.

	Dates become ISO strings, Python dicts and Java Maps become dicts with
	unicode keys, lists and tuples become lists, and anything else that is not a
	JSON scalar becomes unicode(value).

	Args:
		obj (object): The value to convert.
		depth (int): Current recursion depth. Callers leave this at 0.

	Returns:
		object: None, bool, a number, a string, a list or a dict.
	"""
	if depth > MAX_DEPTH:
		return unicode(obj)
	if obj is None or isinstance(obj, (bool, int, long, float, basestring)):
		return obj
	if isDate(obj):
		return isoDate(obj)
	if isinstance(obj, dict):
		out = {}
		for key, value in obj.items():
			out[unicode(key)] = jsonSafe(value, depth + 1)
		return out
	if hasattr(obj, "keySet"):
		out = {}
		for key in obj.keySet():
			out[unicode(key)] = jsonSafe(obj.get(key), depth + 1)
		return out
	if isinstance(obj, (list, tuple)):
		return [jsonSafe(item, depth + 1) for item in obj]
	return unicode(obj)
