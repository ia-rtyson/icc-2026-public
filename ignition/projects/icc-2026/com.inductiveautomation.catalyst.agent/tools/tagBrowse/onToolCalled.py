def onToolCalled(builder=None, path=None, filter=None):
	# Browse the tag tree at a path with a system.tag.browse filter. Returns
	# structured JSON {path, count, results, truncated}; maxResults is capped in
	# exchange.aiTools.tagAccess.
	import exchange.aiTools.tagAccess

	return system.util.jsonEncode(exchange.aiTools.tagAccess.browse(path, filter), 2)
