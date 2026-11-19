def onToolCalled(builder, view_path, component_path, mode):
	# Read a Perspective view's saved definition.
	#
	#   view_path      (string)  Designer view path, e.g.
	#                            "Exchange/Report Issue Agent/Line Overview".
	#   component_path (string)  Optional. Slash-separated meta.name chain, e.g.
	#                            "root/Body/TorqueCard/TorqueValue".
	#   mode           (string)  "tree" (default) -> flat component map, cheap.
	#                            "full" -> the raw view.json subtree.
	#
	# Deliberately narrow: this returns the *saved resource*, not runtime state.
	# Logic lives in exchange.aiTools.viewInspect.viewJson.
	import exchange.aiTools.viewInspect

	result = exchange.aiTools.viewInspect.viewJson(view_path, component_path, mode)
	return builder.text(system.util.jsonEncode(result, 2))
