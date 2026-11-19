def onToolCalled(builder, url):
	# Jython does not auto-load package submodules; import by name.
	import exchange.securityAudit.pages
	inv = exchange.securityAudit.pages.pageInventory()
	target = (url or "").strip()
	if target:
		matches = [pg for pg in inv["pages"] if pg["url"] == target]
		if not matches:
			return builder.text(system.util.jsonEncode({
				"error": "No page registered at '%s'." % target,
				"registeredUrls": [pg["url"] for pg in inv["pages"]],
			}, 2))
		inv = {"project": inv["project"], "file": inv["file"], "pages": matches}
	inv["legend"] = {
		"none": "No permission declared and no runtime identity check found.",
		"declared-only": "A permission block states a requirement, but nothing "
		                 "in the view evaluates identity. Not enforced.",
		"enforced-only": "The view checks identity at runtime but declares no "
		                 "permission, so the rule is invisible to config review.",
		"declared-and-enforced": "Both. This is the intended state.",
	}
	return builder.text(system.util.jsonEncode(inv, 2))
