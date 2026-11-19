def onToolCalled(builder=None, function=None, args=None, kwargs=None):
	"""Invoke one of a fixed allow-list of Ignition translation functions.

	The allow-list, the lookup and the serialization live in
	exchange.aiTools.translationApi; anything not on the list is refused with a
	structured error that names what is allowed.

	Args:
		builder: Supplied by the AI module; unused.
		function (str): Dotted name under system.*, e.g. "util.translate".
		args (list): Positional arguments for the call. Defaults to [].
		kwargs (dict): Keyword arguments for the call. Defaults to {}.

	Returns:
		dict: {ok, result, error}, plus allowed on a refusal.
	"""
	import exchange.aiTools.translationApi

	return exchange.aiTools.translationApi.callAllowed(function, args, kwargs)
