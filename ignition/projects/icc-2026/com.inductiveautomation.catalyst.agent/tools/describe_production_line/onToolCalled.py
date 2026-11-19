def onToolCalled(builder, line_path=None):
	# Snapshot of the Alarm Flood line: stations, what each one measures, and how
	# it is running right now. Lets the Dashboard Agent compose from the line's
	# actual state rather than from tag-path guesswork.
	#
	# Logic lives in exchange.aiTools.productionLine.describeLine, which reads
	# exchange.alarmFlood.model and exchange.dashboard.widgets' public read API.
	import exchange.aiTools.productionLine

	result = exchange.aiTools.productionLine.describeLine(line_path)
	return builder.text(system.util.jsonEncode(result, 2))
