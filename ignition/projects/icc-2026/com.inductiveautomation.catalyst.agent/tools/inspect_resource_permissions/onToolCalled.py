def onToolCalled(builder, kind):
	# Jython does not auto-load package submodules; import by name.
	import exchange.securityAudit.resources
	inv = exchange.securityAudit.resources.inventory()
	kind = (kind or "").strip().lower()
	keys = {
		"agents": "aiAgents",
		"mcp": "mcpServers",
		"tools": "toolBundles",
		"webdev": "webdevEndpoints",
		"queries": "namedQueries",
	}
	if kind:
		if kind not in keys:
			return builder.text(system.util.jsonEncode({
				"error": "Unknown kind '%s'. Valid: %s" % (kind, ", ".join(sorted(keys.keys()))),
			}, 2))
		inv = {"project": inv["project"], keys[kind]: inv[keys[kind]]}
	return builder.text(system.util.jsonEncode(inv, 2))
