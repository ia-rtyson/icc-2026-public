def onToolCalled(builder, domain):
	# Jython does not auto-load package submodules; import by name.
	import exchange.securityAudit.report
	valid = ["users", "gateway", "pages", "resources"]
	d = (domain or "").strip().lower() or None
	if d is not None and d not in valid:
		return builder.text(system.util.jsonEncode({
			"error": "Unknown domain '%s'. Valid values: %s" % (d, ", ".join(valid)),
		}, 2))
	result = exchange.securityAudit.report.forAgent(domain=d)
	return builder.text(system.util.jsonEncode(result, 2))
