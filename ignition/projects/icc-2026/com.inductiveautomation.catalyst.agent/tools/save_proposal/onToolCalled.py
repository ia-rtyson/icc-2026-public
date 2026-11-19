def onToolCalled(builder, proposal_json, rationale, upload_id):
	# Validate, scope and store the agent's proposed structure so it shows in the
	# review tree. Nothing is created here -- the user approves in the chat first.
	#
	# Validation and containment live in exchange.tagImport.core (validateProposal,
	# scopeProposalFolders, instancesUsedAsFolders); exchange.aiTools.tagImportAgent
	# sequences them and shapes the response.
	import exchange.aiTools.tagImportAgent

	result = exchange.aiTools.tagImportAgent.saveProposal(proposal_json, rationale, upload_id)
	return builder.text(system.util.jsonEncode(result, 2))
