def onToolCalled(builder, event_id, tag_paths, full_window, width):
	# Renders a real trend chart for a flood event and returns the Markdown needed to
	# embed it, plus the per-tag facts (baseline, peak, first deviation) to quote
	# alongside it. Use this INSTEAD of printing a table of history samples -- an
	# onset is visible on a chart and invisible in a column of numbers.
	#
	#   event_id     (integer, required) flood event id (ex_icc_alarm_flood_event.id).
	#   tag_paths    (string, optional)  comma-separated or JSON-array tag paths.
	#                Defaults to the earliest-firing historised tags in the event.
	#   full_window  (boolean, optional) true plots the whole stored event window.
	#                Default false auto-focuses on the measured ramp.
	#   width        (integer, optional) chart width in px. Default 720.
	#
	# Logic lives in exchange.aiTools.floodEvents.trendChart; the chart itself is served by
	# the project's `trend` WebDev endpoint.
	import exchange.aiTools.floodEvents

	result = exchange.aiTools.floodEvents.trendChart(event_id, tag_paths, full_window, width)
	return builder.text(system.util.jsonEncode(result, 2))
