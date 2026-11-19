def onToolCalled(builder, tag_paths):
	# Check whether one or more tag paths actually resolve, and suggest the
	# intended tag when one does not.
	#
	#   tag_paths (string)  One or more paths, comma-separated or as a JSON array
	#                       string. A missing [provider] prefix is assumed [default].
	#
	# For each path: does the tag exist, what quality does a live read return, does
	# the parent folder exist, and which siblings are within a small edit distance
	# of the requested leaf name. Logic lives in exchange.aiTools.viewInspect.
	import exchange.aiTools.viewInspect

	result = exchange.aiTools.viewInspect.diagnoseTagReferences(tag_paths)
	return builder.text(system.util.jsonEncode(result, 2))
