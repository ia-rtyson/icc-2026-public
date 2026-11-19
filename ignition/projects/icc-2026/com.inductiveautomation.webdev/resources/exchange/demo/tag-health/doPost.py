def doPost(request, session):
	# Receives the YouTrack column-change webhook.
	#
	#   POST /system/webdev/icc-2026/exchange/issue-report/issue-stage
	#   X-Pipeline-Token: <shared secret>
	#   {"issueId": "UI-4", "stage": "Validate"}
	#
	# Responds immediately and runs the agent on a background thread: an agent
	# turn can take minutes and YouTrack's workflow HTTP call will not wait that
	# long. A 202 means "accepted", not "done" -- the outcome lands as a comment
	# on the ticket, which is the only place it matters.
	#
	# Project library imports MUST be inside the handler. A python-resource that
	# imports one at module level does not see the project scripting context, and
	# the endpoint silently serves an empty body with a 200.
	import system
	import exchange.issueReport.pipeline

	# DEMO ONLY: this secret is hardcoded as an example, to keep the demo stack
	# easy to stand up with nothing to configure. It must be hardened before this
	# runs in a production environment -- move it to an environment variable or a
	# secret store, rotate it, and compare the supplied token in constant time
	# (e.g. java.security.MessageDigest.isEqual) rather than with != below.
	SHARED_SECRET = "icc-2026-issue-pipeline"

	def out(payload, code=200):
		# NOTE: this gateway ignores the status-code key on a python-resource --
		# both "code" and "response-code" were tried and every reply still comes
		# back HTTP 200. So callers must branch on the "status" field in the body,
		# not on the HTTP status. The code is kept here for when that is fixed.
		return {"json": payload, "code": code}

	headers = request.get("headers") or {}
	supplied = None
	for key in headers:
		if unicode(key).lower() == "x-pipeline-token":
			supplied = headers[key]
			break
	if isinstance(supplied, (list, tuple)):
		supplied = supplied[0] if supplied else None

	if unicode(supplied or "") != SHARED_SECRET:
		return out({"status": "unauthorized",
		            "error": "Missing or wrong X-Pipeline-Token header."}, 401)

	raw = request.get("postData")
	if isinstance(raw, dict):
		body = raw
	elif isinstance(raw, basestring):
		try:
			body = system.util.jsonDecode(raw)
		except Exception, e:
			return out({"status": "bad_request",
			            "error": "Body is not valid JSON: %s" % str(e)}, 400)
	else:
		return out({"status": "bad_request", "error": "Expected a JSON body."}, 400)

	issue_id = unicode(body.get("issueId") or "").strip()
	stage = unicode(body.get("stage") or "").strip()

	if not issue_id:
		return out({"status": "bad_request", "error": "issueId is required."}, 400)
	if not stage:
		return out({"status": "bad_request", "error": "stage is required."}, 400)

	# A move into Submitted is a real webhook but nobody owns that column, so it
	# is a quiet no-op rather than an error -- otherwise the workflow logs noise
	# every time a ticket is filed.
	if stage not in exchange.issueReport.pipeline.STAGE_AGENTS:
		return out({"status": "ignored", "issue": issue_id, "stage": stage,
		            "reason": "No agent is bound to that column."}, 200)

	return out(exchange.issueReport.pipeline.dispatchAsync(issue_id, stage), 202)
