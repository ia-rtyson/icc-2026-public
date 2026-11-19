def onToolCalled(builder=None, prefix=None):
	"""List the system.* functions that systemCall is allowed to invoke.

	Args:
		builder: Supplied by the AI module; unused.
		prefix (str): Optional case-insensitive filter on the group name.

	Returns:
		dict: {ok, result, error}; result maps each group to {name, access, usage}.
	"""
	import exchange.aiTools.translationApi

	return exchange.aiTools.translationApi.listAllowed(prefix)
