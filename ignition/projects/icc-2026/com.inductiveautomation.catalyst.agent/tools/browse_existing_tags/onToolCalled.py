def onToolCalled(builder, path):
	# Read-only reconnaissance. system.tag.browse cannot mutate anything, so this
	# tool is safe to point at any path -- but it is only ever a naming/reuse
	# check. Nothing outside the Exchange/Tag Import Agent folder may be written.
	result = exchange.tagImport.core.browse(path)
	result["note"] = (
		"Read-only. Writes are restricted to the '%s' folder regardless of what "
		"you find here." % exchange.tagImport.core.ROOT_FOLDER
	)
	return builder.text(system.util.jsonEncode(result, 2))
