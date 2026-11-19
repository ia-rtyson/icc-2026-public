def onToolCalled(builder):
	# The files are bind-mounted into the gateway, so this is the real directory
	# listing rather than a hardcoded manifest -- drop a file in reference/line1
	# on the host and the agent can see it on the next call.
	import exchange.aiTools.tagImportAgent

	result = exchange.aiTools.tagImportAgent.listReferenceDocuments()
	return builder.text(system.util.jsonEncode(result, 2))
