DEFAULT_PROJECT = 'icc-2026'


def resolveViewPath(pageUrl, project=None):
	"""Look up a page's viewPath in the project's page-config resource.

	Reads through exchange.aiTools.perspective.helpers so the gateway's actual
	data/projects location is used rather than a hardcoded container path.
	Returns None if the config, the page, or the viewPath is missing.
	"""
	h = exchange.aiTools.perspective.helpers
	data = h.safeLoad(h.pageConfigPath(project or DEFAULT_PROJECT), default=None)
	if not isinstance(data, dict):
		return None
	pages = data.get('pages')
	if not isinstance(pages, dict):
		return None
	page = pages.get(pageUrl)
	if not isinstance(page, dict):
		return None
	return page.get('viewPath')
