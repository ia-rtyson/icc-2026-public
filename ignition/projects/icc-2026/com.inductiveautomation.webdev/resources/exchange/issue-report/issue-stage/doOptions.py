def doOptions(request, session):
	return {"json": {"error": "Method not allowed on this endpoint."}, "response-code": 405}
