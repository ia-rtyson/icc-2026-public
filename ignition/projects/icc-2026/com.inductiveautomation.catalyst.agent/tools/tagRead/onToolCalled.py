def onToolCalled(builder=None, tagPaths=None):
	# Read live values for a list of tag paths as structured JSON
	# {count, values: [{path, value, quality, good, timestamp}]}. At most 50 paths
	# per call; the cap is in exchange.aiTools.tagAccess.
	import exchange.aiTools.tagAccess

	return system.util.jsonEncode(exchange.aiTools.tagAccess.readTagList(tagPaths), 2)
