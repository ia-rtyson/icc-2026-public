"""Tag-path argument parsing shared by the AI agent tool bundles.

Several tools take a ``tag_paths`` string argument that may be either a
comma-separated list or a JSON array string. There used to be four drifting
copies of that parser, and one of them still carried the original bug: it
treated any input starting with ``[`` as JSON. A provider-qualified path
(``[default]Exchange/Alarm Flood/...``) also starts with ``[``, so ``jsonDecode``
mangled the whole list into one bogus path and every read came back null.

The rule here is the fixed one from ``query_tag_history``: only treat the
input as JSON when it has the full array shape -- opens with ``[``, closes
with ``]`` and contains a quote character.
"""

logger = system.util.getLogger("exchange.aiTools.TagPaths")


def parseTagPaths(raw, defaultProvider=None):
	"""Split a ``tag_paths`` tool argument into a list of paths.

	Args:
		raw (str): Comma-separated paths, or a JSON array string of paths.
		defaultProvider (str): When given (e.g. ``"default"``), any path without
			a ``[provider]`` prefix gets ``[defaultProvider]`` prepended. When
			None, paths are returned exactly as supplied (trimmed).

	Returns:
		list: The non-empty, trimmed paths, in the order supplied. Empty if
		``raw`` is None or blank.
	"""
	if raw is None:
		return []
	text = unicode(raw).strip()
	if not text:
		return []

	paths = []
	# A JSON array and a provider-qualified path both start with "[", so the
	# closing bracket and a quote are what tell them apart.
	if text.startswith("[") and text.endswith("]") and ('"' in text or "'" in text):
		try:
			decoded = system.util.jsonDecode(text)
			if isinstance(decoded, list):
				paths = [unicode(p).strip() for p in decoded if unicode(p).strip()]
		except:
			# Not valid JSON after all -- fall through to the comma split.
			paths = []
	if not paths:
		paths = [p.strip() for p in text.split(",") if p.strip()]

	if defaultProvider:
		prefix = "[%s]" % defaultProvider
		paths = [p if p.startswith("[") else prefix + p for p in paths]
	return paths
