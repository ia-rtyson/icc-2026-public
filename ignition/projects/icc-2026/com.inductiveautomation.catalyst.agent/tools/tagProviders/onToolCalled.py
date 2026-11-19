def onToolCalled(builder=None):
	# List the tag providers as structured JSON {count, providers}.
	import exchange.aiTools.tagAccess

	return system.util.jsonEncode(exchange.aiTools.tagAccess.browseProviders(), 2)
