def doGet(request, session):
	# Is gateway-scope tag access working?
	#
	#   GET /system/webdev/icc-2026/exchange/demo/tag-health
	#   -> {"ok": true, "checked": [...]}  or  {"ok": false, "error": "..."}
	#
	# Called by the deploy workflow's tag-health watch. This dev build sometimes
	# breaks every system.tag.* call from gateway scope -- a NullPointerException
	# in TagReferencePath.addPath, a few minutes after a project or config scan
	# -- and only a gateway restart clears it. The pages still render while it is
	# broken, so it is invisible until someone runs a flood.
	#
	# Branch on "ok", not the HTTP status: this gateway ignores the status code a
	# python-resource sets and always answers 200. Read-only and returns no tag
	# values, so it needs no auth.
	import sys
	import system

	paths = ["[System]Gateway/CurrentDateTime",
	         "[default]Exchange/Alarm Flood/Simulator/Phase"]
	try:
		qvs = system.tag.readBlocking(paths)
		bad = [p for p, qv in zip(paths, qvs) if not qv.quality.isGood()]
		if bad:
			return {"json": {"ok": False, "error": "bad quality", "bad": bad}}
		return {"json": {"ok": True, "checked": paths}}
	except:
		# Bare except: the platform NPE is a Java exception, which
		# "except Exception" does not catch in Jython.
		return {"json": {"ok": False, "error": str(sys.exc_info()[1])}}
