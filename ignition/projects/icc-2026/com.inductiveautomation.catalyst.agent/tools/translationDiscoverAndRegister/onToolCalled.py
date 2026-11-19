def onToolCalled(builder=None, viewPath=None, targetLocale=None, pageUrl=None, pageParams=None, viewParams=None):
	"""Discover and register identity translations for a Perspective view graph.

	Delegates to exchange.aiTools.translationApi.discoverAndRegister, which never raises:
	a failure comes back under failed in the usual result shape.
	"""
	import exchange.aiTools.translationApi

	return exchange.aiTools.translationApi.discoverAndRegister(viewPath, targetLocale, pageUrl, pageParams, viewParams)
