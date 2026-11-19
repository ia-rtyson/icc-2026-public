def onToolCalled(builder, filename):
	import sys
	name = (filename or "").strip() or exchange.tagImport.core.PRIMARY_REFERENCE_FILE

	result = exchange.tagImport.core.readReferenceDocument(name)
	if result["status"] != "ok":
		return builder.text(system.util.jsonEncode(result, 2))

	# save_proposal keys a proposal to an upload row. The upload widget is gone,
	# so reading the tag export is what creates that row -- otherwise the agent
	# gets "No upload on file" the moment it tries to save its proposal.
	if result["filename"] == exchange.tagImport.core.PRIMARY_REFERENCE_FILE:
		try:
			upload = exchange.tagImport.core.ensureUploadFromReference(result["filename"])
			result["uploadId"] = upload["uploadId"]
			result["rowCount"] = upload["rowCount"]
		except:
			e = sys.exc_info()[1]
			result["uploadWarning"] = str(e)

	return builder.text(system.util.jsonEncode(result, 2))
