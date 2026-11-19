def onToolCalled(builder):
	# Jython does not auto-load package submodules; import by name.
	import exchange.securityAudit.users
	inv = exchange.securityAudit.users.inventory()
	return builder.text(system.util.jsonEncode(inv, 2))
