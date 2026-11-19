def onToolCalled(builder, view_path, component_path, include_descendants):
	# Read the binding definitions attached to a Perspective component, with
	# indirect tag paths resolved against the view's saved custom/param values so
	# the agent sees the literal tag path the binding will request. Feed that
	# path to diagnose_tag_reference. Logic lives in exchange.aiTools.viewInspect.
	import exchange.aiTools.viewInspect

	result = exchange.aiTools.viewInspect.componentBindings(view_path, component_path, include_descendants)
	return builder.text(system.util.jsonEncode(result, 2))
