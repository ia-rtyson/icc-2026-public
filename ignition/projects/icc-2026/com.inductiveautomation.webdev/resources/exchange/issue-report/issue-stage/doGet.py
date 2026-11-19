def doGet(request, session):
	# Status view for the pipeline.
	#
	#   GET /system/webdev/icc-2026/exchange/issue-report/issue-stage
	#
	#   GET /system/webdev/icc-2026/exchange/issue-report/issue-stage?agent=Validate%20Agent&limit=20
	#
	# Shows which agent owns which column, whether each is actually registered on
	# the gateway, and the logged activity with its outcome. That last part
	# matters: a crashed agent posts no YouTrack comment, so without the log the
	# only evidence of a failure is a stack trace in the gateway log.
	#
	# Project library imports MUST be inside the handler. A python-resource that
	# imports one at module level does not see the project scripting context, and
	# the endpoint silently serves an empty body with a 200.
	import exchange.issueReport.pipeline

	params = request.get("params", {}) or {}

	def p(name, default=None):
		v = params.get(name, default)
		if isinstance(v, (list, tuple)):
			v = v[0] if v else default
		return v

	try:
		registered = set(a.get("name") for a in exchange.issueReport.pipeline.listAgents())
	except Exception:
		registered = None

	stages = {}
	for stage, agent in exchange.issueReport.pipeline.STAGE_AGENTS.items():
		entry = {"agent": agent}
		if registered is not None:
			entry["registered"] = agent in registered
		stages[stage] = entry

	try:
		limit = int(p("limit", 50) or 50)
	except ValueError:
		limit = 50
	activity = exchange.issueReport.pipeline.recentActivity(p("agent"), limit)

	counts = {"running": 0, "ok": 0, "error": 0}
	for r in activity:
		key = r.get("status") or "error"
		counts[key] = counts.get(key, 0) + 1

	return {"json": {
		"status": "ok",
		"endpoint": "issue-stage",
		"stages": stages,
		"agents": exchange.issueReport.pipeline.activityAgents(),
		"activity_summary": counts,
		"activity": activity,
	}}
