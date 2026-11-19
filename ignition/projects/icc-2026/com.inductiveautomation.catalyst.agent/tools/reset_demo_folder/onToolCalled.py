def onToolCalled(builder, confirm):
	import sys
	# Containment is in exchange.tagImport.core.resetRoot: it only ever browses and deletes the
	# children of ROOT_PATH and TYPES_ROOT_PATH, so no argument of this tool can
	# widen what it touches. confirm exists so a stray call cannot wipe the demo.
	if confirm is not True and unicode(confirm).lower() not in ("true", "yes", "1"):
		return builder.text(system.util.jsonEncode({
			"status": "not_confirmed",
			"message": "Pass confirm=true to delete everything under the Exchange/Tag Import Agent "
			           "folder. Ask the user first; nothing was deleted."
		}, 2))

	try:
		result = exchange.tagImport.core.resetRoot(True)
	except:
		e = sys.exc_info()[1]
		return builder.text(system.util.jsonEncode({"status": "error", "message": str(e)}, 2))

	result["message"] = ("Removed %d objects. The Exchange/Tag Import Agent tag folder and its "
	                     "_types_ folder are empty; everything outside them is untouched."
	                     % result["removedCount"])
	return builder.text(system.util.jsonEncode(result, 2))
