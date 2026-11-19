def doGet(request, session):
	# Serves a stored flood event's tag-history trend as an SVG image, so a
	# Markdown report can embed a real chart with ![Trend](.../trend?event_id=7).
	#
	# Query params:
	#   event_id  required. A positive ex_icc_alarm_flood_event.id -- window, trip marker
	#             and default tag selection are all derived from it
	#   tags      optional comma-separated tag paths to plot instead of the default
	#             pick. Contained to [default]Exchange/Alarm Flood/ and capped in count by
	#             exchange.alarmFlood.trend; the window is always the event's own
	#   width     SVG width in px, clamped to 480-1600 (default 720)
	#   full      1 to plot the whole stored event window instead of
	#             auto-focusing on the fault onset
	#
	# There is deliberately no ad-hoc "tags + minutes_back" mode any more. This
	# endpoint needs no login, and that mode let anyone pull an uncapped window
	# of raw 1 Hz history for any tag on any provider. The render_trend_chart
	# tool only ever asks for an event, so an event is the only thing served.
	import system, traceback
	import exchange.alarmFlood.trend as T

	params = request.get('params', {}) or {}

	def _p(name, default=None):
		v = params.get(name, default)
		if isinstance(v, (list, tuple)):
			v = v[0] if v else default
		return v

	try:
		rawEvent = unicode(_p('event_id', '') or '').strip()
		if not rawEvent.isdigit() or int(rawEvent) <= 0:
			raise ValueError('event_id is required and must be a positive integer')
		eventId = int(rawEvent)

		# Same clamp as the render_trend_chart tool, so both agree on size.
		try:
			width = max(480, min(1600, int(_p('width', 720) or 720)))
		except:
			width = 720

		rawTags = _p('tags', '') or ''
		tags = [t.strip() for t in unicode(rawTags).split(',') if t.strip()] or None
		full = unicode(_p('full', '0') or '0').lower() in ('1', 'true', 'yes')
		svg = T.svgForEvent(eventId, tagPaths=tags, width=width, focus=not full)

		# WebDev takes the body under 'response' -- 'bytes' is not a recognised key
		# and makes the module report "No response from ...:doGet".
		return {'contentType': 'image/svg+xml', 'response': svg}
	except:
		# Render the failure *as an image* -- an <img> tag cannot show a JSON error,
		# so a broken chart would otherwise be a silently empty box in the report.
		import sys
		errType, errValue = sys.exc_info()[:2]
		msg = '%s: %s' % (getattr(errType, '__name__', str(errType)), errValue)
		system.util.getLogger('exchange.alarmFlood.Trend').warn('trend endpoint failed -- %s\n%s'
													   % (msg, traceback.format_exc()))
		safe = msg.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
		svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="720" height="56">'
			   '<rect width="720" height="56" fill="#FDECEA"/>'
			   '<text x="12" y="24" font-family="sans-serif" font-size="12" fill="#B02020">'
			   'Trend chart unavailable</text>'
			   '<text x="12" y="42" font-family="sans-serif" font-size="10" fill="#B02020">'
			   + safe[:140] + '</text></svg>')
		return {'contentType': 'image/svg+xml', 'response': svg}
