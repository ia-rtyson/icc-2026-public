def onToolCalled(builder, proposal_id):
	# The user's instruction in the chat IS the acceptance -- there is no Accept
	# button on the page any more. Only call this when they have actually said so.
	# Archived and rejected proposals are refused in exchange.aiTools.tagImportAgent.
	import exchange.aiTools.tagImportAgent

	result = exchange.aiTools.tagImportAgent.acceptProposal(proposal_id)
	return builder.text(system.util.jsonEncode(result, 2))
