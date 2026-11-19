def onToolCalled(builder, view_path, property_name, new_value, expected_current_value, confirm):
	# Change one entry in a Perspective view's top-level `custom` object, then
	# reload the project so the running session picks it up.
	#
	# This is the only tool in the pipeline that writes to a project resource.
	# It is deliberately narrow: one property, on one view, with a required
	# statement of what you believe you are replacing. Without confirm it is a dry
	# run. Logic lives in exchange.aiTools.viewInspect.setViewCustomProperty.
	import exchange.aiTools.viewInspect

	result = exchange.aiTools.viewInspect.setViewCustomProperty(
		view_path, property_name, new_value, expected_current_value, confirm)
	return builder.text(system.util.jsonEncode(result, 2))
