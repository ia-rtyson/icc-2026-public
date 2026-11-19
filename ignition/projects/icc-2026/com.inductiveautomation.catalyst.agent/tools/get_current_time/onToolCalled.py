def onToolCalled(builder):
	now = system.date.now()
	result = {
		"iso": system.date.format(now, "yyyy-MM-dd'T'HH:mm:ss.SSS"),
		"timezone": system.date.getTimeZone().getID()
	}
	return builder.text(system.util.jsonEncode(result, 2))
