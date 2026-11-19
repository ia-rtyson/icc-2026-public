def onToolCalled(builder, reason, proposal_id):
	# Mark the proposal Rejected on the review panel; nothing is created or deleted.
	import exchange.aiTools.tagImportAgent

	result = exchange.aiTools.tagImportAgent.rejectProposal(reason, proposal_id)
	return builder.text(system.util.jsonEncode(result, 2))
