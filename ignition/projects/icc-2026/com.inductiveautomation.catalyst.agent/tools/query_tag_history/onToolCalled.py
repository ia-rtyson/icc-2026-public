def onToolCalled(builder, tag_paths, event_id, seconds_back, return_size, aggregation_mode):
	# Query the tag historian for one or more tags.
	#
	#   tag_paths       (string)  one or more tag paths: comma-separated, or a JSON
	#                             array string. Paths without a [provider] prefix are
	#                             assumed to be in [default]. At most 10 per call.
	#   event_id        (integer, optional) flood event id (ex_icc_alarm_flood_event.id). When supplied the
	#                             window comes from that event's stored window (capped
	#                             at 30 minutes, padded 60 s either side) instead of a
	#                             trailing window. It is the only way to get a window
	#                             longer than 60 seconds.
	#   seconds_back    (integer, optional) trailing window size in seconds, used only
	#                             when event_id is not supplied. Default 60, capped at 60.
	#   return_size     (integer, optional) max sample rows. Ignored in As Stored mode.
	#   aggregation_mode(string, optional)  historian aggregation. Default "As Stored".
	#
	# Every limit, the compaction and the sampling live in exchange.aiTools.tagHistory; this
	# handler only forwards the arguments. Returns a wide-format table: a timestamp
	# column plus one column per tag.
	import exchange.aiTools.tagHistory

	result = exchange.aiTools.tagHistory.queryHistory(
		tag_paths, eventId=event_id, secondsBack=seconds_back,
		returnSize=return_size, aggregationMode=aggregation_mode)
	return builder.text(system.util.jsonEncode(result))
