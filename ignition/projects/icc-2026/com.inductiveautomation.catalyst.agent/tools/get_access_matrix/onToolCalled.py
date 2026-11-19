def onToolCalled(builder):
	# Jython does not auto-load package submodules; import by name.
	import exchange.securityAudit.matrix
	m = exchange.securityAudit.matrix.build()
	return builder.text(system.util.jsonEncode({
		"markdown": exchange.securityAudit.matrix.toMarkdown(m),
		"roles": m["roles"],
		"securityLevels": m["levels"],
		"rows": m["rows"],
		"note": "A cell of ALL is not access that was granted -- it is access "
		        "that was never restricted. Report those as findings, not as "
		        "working permissions.",
	}, 2))
