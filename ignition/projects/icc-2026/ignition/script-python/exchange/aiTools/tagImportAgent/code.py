"""Tool-facing flows for the Tag Import Agent.

Backs save_proposal, accept_proposal, reject_proposal, create_proposed_structure
and list_reference_documents. Validation, containment and persistence stay in
exchange.tagImport.core; this module sequences them and shapes the response the model reads,
including the instructions it is told to follow next.
"""
import sys

import exchange.tagImport.core
import exchange.aiTools.toolArgs

logger = system.util.getLogger("exchange.aiTools.TagImportAgent")

_COLLISION_MESSAGE = ("A UDT instance is a leaf, not a folder -- Ignition refuses child "
	"tags under one. Move these beside the instance in its parent "
	"folder, named after the machine (e.g. 'Roaster_BeanTemp'), or add "
	"them to the UDT definition as members, then call save_proposal "
	"again. Nothing was saved.")


def _badArgument(error, toolName):
	"""invalidArgument payload plus the message key these tools always carry."""
	result = exchange.aiTools.toolArgs.invalidArgument(error, toolName)
	result["message"] = result["error"]
	return result


def _proposalId(rawProposalId, toolName):
	"""Coerce proposal_id; returns (id or None, errorPayload or None)."""
	try:
		return exchange.aiTools.toolArgs.optionalInt(rawProposalId, "proposal_id"), None
	except exchange.aiTools.toolArgs.ArgumentError, error:
		return None, _badArgument(error, toolName)


def saveProposal(proposalJson, rationale, uploadId):
	"""Validate, scope and store a proposal the agent wrote.

	Args:
		proposalJson (str): The proposal as a JSON string.
		rationale (str): The agent's reasoning, stored with the proposal.
		uploadId (object): ex_icc_tag_import_upload id; None means the latest upload.

	Returns:
		dict: {status: "saved", proposalId, counts, foldersRewrittenIntoScope,
			message}, or {status: "invalid_json" | "invalid_proposal" |
			"invalid_argument", ...} with nothing saved.

	Raises:
		ValueError: If proposalJson is empty.
	"""
	if proposalJson is None or unicode(proposalJson).strip() == "":
		raise ValueError("proposal_json is required")

	try:
		proposal = system.util.jsonDecode(unicode(proposalJson))
	except:
		error = sys.exc_info()[1]
		logger.warn("save_proposal: proposal_json did not parse: %s" % error)
		return {
			"status": "invalid_json",
			"message": "proposal_json did not parse as JSON: %s" % str(error)
		}

	errors = exchange.tagImport.core.validateProposal(proposal)
	if errors:
		return {
			"status": "invalid_proposal",
			"errors": errors,
			"message": "Fix these and call save_proposal again. Nothing was saved."
		}

	rewritten = exchange.tagImport.core.scopeProposalFolders(proposal)

	collisions = exchange.tagImport.core.instancesUsedAsFolders(proposal)
	if collisions:
		return {"status": "invalid_proposal", "errors": collisions, "message": _COLLISION_MESSAGE}

	try:
		resolvedUploadId = exchange.aiTools.toolArgs.optionalInt(uploadId, "upload_id")
	except exchange.aiTools.toolArgs.ArgumentError, error:
		return _badArgument(error, "save_proposal")

	proposalId = exchange.tagImport.core.saveProposal(resolvedUploadId, proposal, rationale)

	counts = {
		"udt_definitions": len(proposal.get("udt_definitions") or []),
		"udt_instances": len(proposal.get("udt_instances") or []),
		"standalone_tags": len(proposal.get("standalone_tags") or []),
		"unresolved": len(proposal.get("unresolved") or []),
	}
	return {
		"status": "saved",
		"proposalId": proposalId,
		"counts": counts,
		"foldersRewrittenIntoScope": rewritten,
		"message": "Proposal %d saved and is now showing in the tree on the Tag Import "
			"page. Summarize it for the user and ask them to review it and tell you "
			"in the chat whether to go ahead. When they say yes, call "
			"accept_proposal and then the create_ tools; if they object, call "
			"reject_proposal. Create nothing before that." % proposalId
	}


def acceptProposal(rawProposalId):
	"""Accept a proposal on the user's say-so in the chat.

	The user's instruction in the chat IS the acceptance -- there is no Accept
	button on the page. Archived and rejected proposals are refused.

	Args:
		rawProposalId (object): proposal_id argument; None means the latest.

	Returns:
		dict: {status: "accepted" | "no_proposal" | "archived" | "rejected" |
			"error" | "invalid_argument", ...}.
	"""
	proposalId, badArgument = _proposalId(rawProposalId, "accept_proposal")
	if badArgument:
		return badArgument
	proposal = exchange.tagImport.core.getProposal(proposalId)
	if proposal is None:
		return {
			"status": "no_proposal",
			"message": "There is no saved proposal to accept. Call save_proposal first."
		}
	if proposal["status"] == "archived":
		return {
			"status": "archived",
			"proposalId": proposal["proposalId"],
			"message": "Proposal %d was cleared from the page and is no longer on screen, "
				"so the user cannot have been approving it. Save a fresh proposal "
				"and let them review it." % proposal["proposalId"]
		}
	if proposal["status"] == "rejected":
		return {
			"status": "rejected",
			"proposalId": proposal["proposalId"],
			"message": "Proposal %d was rejected. Revise it and call save_proposal again "
				"instead of accepting this one." % proposal["proposalId"]
		}

	try:
		acceptedId = exchange.tagImport.core.acceptProposal(proposal["proposalId"])
	except:
		error = sys.exc_info()[1]
		logger.warn("accept_proposal %s failed: %s" % (proposal["proposalId"], error))
		return {"status": "error", "message": str(error)}

	return {
		"status": "accepted",
		"proposalId": acceptedId,
		"message": "Proposal %d is accepted. Create in this order: UDT definitions, then "
			"instances, then standalone tags, then report the final tag paths." % acceptedId
	}


def rejectProposal(reason, rawProposalId):
	"""Mark a proposal rejected on the review panel.

	Args:
		reason (str): Why, as the user put it.
		rawProposalId (object): proposal_id argument; None means the latest.

	Returns:
		dict: {status: "rejected" | "no_proposal" | "error" | "invalid_argument", ...}.
	"""
	proposalId, badArgument = _proposalId(rawProposalId, "reject_proposal")
	if badArgument:
		return badArgument
	proposal = exchange.tagImport.core.getProposal(proposalId)
	if proposal is None:
		return {"status": "no_proposal", "message": "There is no saved proposal to reject."}

	try:
		rejectedId = exchange.tagImport.core.rejectProposal(proposal["proposalId"])
	except:
		error = sys.exc_info()[1]
		logger.warn("reject_proposal %s failed: %s" % (proposal["proposalId"], error))
		return {"status": "error", "message": str(error)}

	return {
		"status": "rejected",
		"proposalId": rejectedId,
		"reason": unicode(reason or ""),
		"message": "Proposal %d is marked Rejected on the review panel. Nothing was "
			"created or deleted. Ask what to change, then call save_proposal with a "
			"revised structure -- the new one replaces it on the page." % rejectedId
	}


def createStructure(rawProposalId):
	"""Build an accepted proposal's structure via exchange.tagImport.core.createFromProposal.

	The acceptance gate, containment rewrite, ordering and batching all live in
	exchange.tagImport.core.createFromProposal; the structure is read back from the stored
	proposal, so the agent never re-sends the tags it already wrote once.

	Args:
		rawProposalId (object): proposal_id argument; None means the latest.

	Returns:
		dict: createFromProposal's result plus a summary message, or
			{status: "error" | "invalid_argument", message}.
	"""
	proposalId, badArgument = _proposalId(rawProposalId, "create_proposed_structure")
	if badArgument:
		return badArgument
	try:
		result = exchange.tagImport.core.createFromProposal(proposalId)
	except:
		error = sys.exc_info()[1]
		logger.warn("create_proposed_structure %s failed: %s" % (proposalId, error))
		return {"status": "error", "message": str(error)}

	if result.get("status") in ("created", "partial"):
		created = result["created"]
		result["message"] = (
			"Created %d UDT definition(s), %d instance(s) and %d standalone tag(s)."
			% (created["udt_definitions"], created["udt_instances"],
				created["standalone_tags"])
		)
		if result.get("failures"):
			result["message"] += (
				" %d item(s) failed -- report them to the user with the reason; do "
				"not retry them one by one without fixing the cause."
				% len(result["failures"])
			)
	return result


def listReferenceDocuments():
	"""List the mounted reference documents with their descriptions.

	The files are bind-mounted into the gateway, so this is the real directory
	listing rather than a hardcoded manifest.

	Returns:
		dict: {status: "ok", count, primaryTagExport, documents} or
			{status: "empty", message}.
	"""
	documents = []
	for entry in exchange.tagImport.core.referenceFiles():
		documents.append({
			"filename": entry["name"],
			"sizeKb": entry["sizeKb"],
			"note": exchange.tagImport.core.referenceBlurb(entry["name"]),
			"isPrimaryTagExport": entry["name"] == exchange.tagImport.core.PRIMARY_REFERENCE_FILE,
		})

	if not documents:
		logger.warn("No reference documents found in %s" % exchange.tagImport.core.REFERENCE_DIR)
		return {
			"status": "empty",
			"message": "No reference documents are mounted on this gateway. Tell the user "
				"the reference folder is missing rather than inventing tag names.",
		}
	return {
		"status": "ok",
		"count": len(documents),
		"primaryTagExport": exchange.tagImport.core.PRIMARY_REFERENCE_FILE,
		"documents": documents,
	}
