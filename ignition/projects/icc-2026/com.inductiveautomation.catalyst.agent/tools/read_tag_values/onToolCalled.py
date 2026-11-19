def onToolCalled(builder, tag_paths):
	# Read current (live) values for one or more tags.
	#
	#   tag_paths (string)  one or more tag paths: comma-separated, or a JSON array
	#                       string. Paths without a [provider] prefix are assumed to
	#                       be in [default]. At most 50 per call.
	#
	# Returns value, quality, good flag, and timestamp for each path. Logic lives in
	# exchange.aiTools.tagAccess.
	import exchange.aiTools.tagAccess

	result = exchange.aiTools.tagAccess.readTagValues(tag_paths)
	return builder.text(system.util.jsonEncode(result, 2))
