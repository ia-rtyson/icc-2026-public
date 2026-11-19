def onToolCalled(builder, event_id, include_alarms):
	# Query collected alarm-flood events.
	#
	#   event_id       (integer, optional) target flood event id (ex_icc_alarm_flood_event.id). When
	#                  omitted/None/0, returns the list of all events (most recent first).
	#   include_alarms (boolean, optional) when returning a single event, whether to
	#                  include the full sequence-of-events alarm list. Defaults to true.
	#
	# Logic lives in exchange.aiTools.floodEvents (Exchange/AlarmFlood/* named queries and
	# exchange.alarmFlood.data.getFloodEvent underneath).
	import exchange.aiTools.floodEvents

	result = exchange.aiTools.floodEvents.queryEvents(event_id, include_alarms)
	return builder.text(system.util.jsonEncode(result, 2))
