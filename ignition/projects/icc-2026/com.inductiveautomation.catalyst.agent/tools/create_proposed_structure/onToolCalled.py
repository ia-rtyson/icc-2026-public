def onToolCalled(builder, proposal_id):
	# All the work -- the acceptance gate, the containment rewrite, the ordering
	# and the batching -- is in exchange.tagImport.core.createFromProposal. The structure is read
	# from the stored proposal, so the agent never re-sends 117 tags it already
	# wrote once.
	import exchange.aiTools.tagImportAgent

	result = exchange.aiTools.tagImportAgent.createStructure(proposal_id)
	return builder.text(system.util.jsonEncode(result, 2))
