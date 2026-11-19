def onToolCalled(builder, path):
	# Browse one level of the tag tree. A blank path browses [default]; a path
	# without a [provider] prefix is assumed [default]. Bounded in exchange.aiTools.tagAccess.
	import exchange.aiTools.tagAccess

	result = exchange.aiTools.tagAccess.browseChildren(path)
	return builder.text(system.util.jsonEncode(result, 2))
