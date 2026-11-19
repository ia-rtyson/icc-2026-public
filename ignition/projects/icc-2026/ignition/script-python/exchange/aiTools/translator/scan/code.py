# Discover literal text in a Perspective view graph and register it as
# translations for a target locale.
#
# Callers: the Translation Manager Agent's translationDiscoverAndRegister tool
# (discoverAndRegister) and the shared top bar's Translate button, through
# exchange.translation.ui.translatePage (scanView). translateDeep / listTermsDeep have no
# caller in this project at present; they are the deep pass kept from upstream.
import json
import os
import sys

logger = system.util.getLogger('exchange.aiTools.TranslatorScan')

DEFAULT_PROJECT = 'icc-2026'

# The AI agent both translate paths call through system.ai.sendMessage.
AGENT_NAME = 'Translation Manager Agent'


def _projectRoot(project=None):
	"""Project directory, resolved through the shared helper so the gateway's
	actual data/projects location (Linux container or Windows install) is used."""
	return os.path.join(exchange.aiTools.perspective.helpers.projectRoot(),
						project or DEFAULT_PROJECT)


def _viewsRoot(project=None):
	return os.path.join(_projectRoot(project),
						'com.inductiveautomation.perspective', 'views')


TEXT_PROPS = {
	'ia.display.label': ['text'],
	'ia.input.button': ['text'],
	'ia.input.textfield': ['text', 'placeholder'],
	'ia.input.textarea': ['text', 'placeholder'],
	'ia.input.numericentry': ['text'],
}
EMBEDDED_VIEW_TYPES = ('ia.display.view',)


def _safeViewPath(viewPath):
	rel = (viewPath or '').strip('/').replace('\\', '/')
	if not rel or '..' in rel.split('/'):
		raise ValueError('Invalid Perspective view path: %r' % viewPath)
	return rel


def _readViewJson(viewPath, project=None):
	rel = _safeViewPath(viewPath)
	fp = os.path.join(_viewsRoot(project), rel, 'view.json')
	with open(fp, 'r') as f:
		return json.load(f)


def _bindingPaths(node):
	cfg = node.get('propConfig') or {}
	return set(cfg.keys()) if isinstance(cfg, dict) else set()


def _appendLiteral(out, viewPath, componentName, componentType, propPath, value):
	if isinstance(value, basestring) and value.strip():
		out.append({
			'key': value,
			'sourceText': value,
			'viewPath': viewPath,
			'componentName': componentName,
			'componentType': componentType,
			'sourceProp': propPath,
		})


def _collectTerms(node, viewPath, out, embeddedViews):
	if not isinstance(node, dict):
		return
	ctype = node.get('type', '')
	meta = node.get('meta') or {}
	name = meta.get('name') or ctype
	props = node.get('props') or {}
	bound = _bindingPaths(node)

	for propName in TEXT_PROPS.get(ctype, []):
		if 'props.%s' % propName not in bound:
			_appendLiteral(out, viewPath, name, ctype, propName, props.get(propName))

	if ctype == 'ia.input.dropdown':
		options = props.get('options') or []
		if 'props.options' not in bound and isinstance(options, list):
			for i, option in enumerate(options):
				if isinstance(option, dict):
					_appendLiteral(out, viewPath, '%s.option[%d]' % (name, i), ctype,
									'options[%d].label' % i, option.get('label'))

	if ctype in EMBEDDED_VIEW_TYPES:
		path = props.get('path')
		if isinstance(path, basestring) and path.strip() and 'props.path' not in bound:
			embeddedViews.append(path.strip('/'))

	children = node.get('children')
	if isinstance(children, list):
		for child in children:
			_collectTerms(child, viewPath, out, embeddedViews)


def discoverTerms(viewPath, pageUrl=None, pageParams=None, viewParams=None, project=None):
	rootView = _safeViewPath(viewPath)
	pending = [rootView]
	visited = []
	found = []
	unresolved = []

	while pending:
		current = pending.pop(0)
		if current in visited:
			continue
		visited.append(current)
		try:
			viewJson = _readViewJson(current, project)
		except Exception as e:
			unresolved.append({'viewPath': current, 'error': str(e)})
			continue
		embedded = []
		_collectTerms(viewJson.get('root', {}), current, found, embedded)
		for childPath in embedded:
			if childPath not in visited and childPath not in pending:
				pending.append(childPath)

	byKey = {}
	for entry in found:
		byKey.setdefault(entry['key'], []).append(entry)
	return {
		'rootViewPath': rootView,
		'pageUrl': pageUrl,
		'pageParams': dict(pageParams or {}),
		'viewParams': dict(viewParams or {}),
		'viewsVisited': visited,
		'terms': [entry for entries in byKey.values() for entry in entries],
		'uniqueTerms': sorted(byKey.keys()),
		'unresolvedViews': unresolved,
	}


def _uniqueSourceTerms(terms):
	unique = []
	seen = set()
	for term in terms or []:
		text = term.get('sourceText') if isinstance(term, dict) else term
		if isinstance(text, basestring) and text.strip() and text not in seen:
			seen.add(text)
			unique.append(text)
	return unique


def _translationPrompt(sourceLocale, targetLocale, texts):
	payload = json.dumps(texts, ensure_ascii=False)
	return ("Translate the following UI text from %s to %s. Return ONLY valid JSON with this exact shape: "
			"{\\\"translations\\\":[{\\\"source\\\":\\\"original\\\",\\\"translation\\\":\\\"translated\\\",\\\"translate\\\":true}]}\\n"
			"Include exactly one item for every input string, preserving each source string exactly. "
			"Translate natural-language UI text, labels, placeholders, and option text. Preserve numbers, "
			"URLs, variable-like tokens, punctuation, and markup where appropriate. Do NOT translate a "
			"proper name, person name, brand, product name, place name, or other proper noun; for those "
			"return the original text and set translate to false. Use context and capitalization: for example, "
			"\"Bill\" can be a person's name and should remain \"Bill\", while \"Pay bill\" should be translated. "
			"If uncertain whether a word is a proper name, leave that word unchanged but translate the rest. "
			"Do not add commentary or markdown.\nINPUT:\n%s" % (sourceLocale, targetLocale, payload))


def _parseTranslations(raw, expected, targetLocale):
	# The model routinely wraps its JSON in ``` fences or prefaces it with a
	# sentence of prose. A bare json.loads() fails on both with the opaque
	# "No JSON object could be decoded", which is what made the auto-translate
	# button look broken. _coerceEnvelope is the tolerant parser the deep path
	# already uses (fence-stripping + raw_decode at each bracket); share it
	# rather than parsing two different ways in the same module.
	rows = _coerceEnvelope(raw, 'translations', 'Translation')
	expectedSet = set(expected)
	result = {}
	for row in rows:
		if not isinstance(row, dict):
			continue
		source = row.get('source')
		translation = row.get('translation')
		if source in expectedSet and isinstance(translation, basestring) and translation.strip():
			result[source] = translation
	missing = [text for text in expected if text not in result]
	if missing:
		raise ValueError('AI response omitted %d source terms for %s' % (len(missing), targetLocale))
	return result


def _requestTranslations(sourceLocale, targetLocale, texts):
	prompt = _translationPrompt(sourceLocale, targetLocale, texts)
	raw = system.ai.sendMessage(AGENT_NAME, prompt)
	return _parseTranslations(raw, texts, targetLocale)


def registerTranslations(terms, targetLocale, sourceLocale='en-US', translateFn=None):
	locale = (targetLocale or '').strip()
	if not locale:
		raise ValueError('targetLocale is required')
	unique = _uniqueSourceTerms(terms)
	if locale == sourceLocale:
		translations = dict((text, text) for text in unique)
	elif translateFn is not None:
		translations = translateFn(sourceLocale, locale, unique)
	else:
		translations = _requestTranslations(sourceLocale, locale, unique)

	added = []
	already = []
	failed = []
	for text in unique:
		translated = translations.get(text)
		if not isinstance(translated, basestring) or not translated.strip():
			failed.append({'key': text, 'error': 'AI returned no translation'})
			continue
		existing = system.util.translate(text, locale)
		if existing == translated and translated != text:
			already.append(text)
			continue
		# A term left as-is (a proper noun) is still registered, as an identity
		# translation: system.util.translate cannot tell it apart from a term
		# that was never registered, so without the key the page would never
		# read as translated (exchange.translation.ui.pageStatus).
		try:
			system.util.modifyTranslation(text, translated, locale)
			added.append({'key': text, 'translation': translated})
		except:
			# Bare except: a Java exception from system.util would escape
			# "except Exception" in Jython
			e = sys.exc_info()[1]
			logger.error('translation failed key=%s locale=%s: %s' % (text, locale, e))
			failed.append({'key': text, 'error': str(e)})
	return {
		'targetLocale': locale,
		'sourceLocale': sourceLocale,
		'found': unique,
		'translations': translations,
		'added': added,
		'alreadyPresent': already,
		'failed': failed,
	}


def discoverAndRegister(viewPath, targetLocale, pageUrl=None, pageParams=None, viewParams=None, sourceLocale='en-US', translateFn=None, project=None):
	discovery = discoverTerms(viewPath, pageUrl, pageParams, viewParams, project)
	registration = registerTranslations(discovery['uniqueTerms'], targetLocale, sourceLocale, translateFn)
	registration.update({
		'rootViewPath': discovery['rootViewPath'],
		'pageUrl': discovery['pageUrl'],
		'pageParams': discovery['pageParams'],
		'viewParams': discovery['viewParams'],
		'viewsVisited': discovery['viewsVisited'],
		'terms': discovery['terms'],
		'unresolvedViews': discovery['unresolvedViews'],
	})
	return registration


def scanView(viewPath, targetLocale, sourceLocale='en-US', translateFn=None, project=None):
	return discoverAndRegister(viewPath, targetLocale, sourceLocale=sourceLocale, translateFn=translateFn, project=project)


def listTerms(viewPath, project=None):
	return discoverTerms(viewPath, project=project)['terms']


# --- Deep translator: walks the view graph beyond literal props, uses the
# gateway-side agent (system.ai.sendMessage) to extrapolate terms from bindings,
# event-script string literals, and embedded-view params, and lets the agent
# call its assigned tools to verify / explore further. Designed to run alongside
# the literal-only scanView without breaking it.

DEEP_PROMPT_VERSION = 1
CONFIDENCE_LEVELS = ('literal', 'binding', 'script', 'guess')
DEEP_AGENT_NAME = AGENT_NAME


def _stripQuotes(literalString):
	s = literalString
	for prefix in ('r', 'R', 'b', 'B', 'u', 'U'):
		if s.startswith(prefix) and len(s) > len(prefix) + 1 and s[len(prefix)] in ('"', "'"):
			s = s[len(prefix):]
			break
	if len(s) < 2:
		return u''
	quote = s[0]
	if s[-1] != quote:
		return literalString
	inner = s[1:-1]
	try:
		return inner.encode('latin-1').decode('unicode_escape')
	except Exception:
		return inner


def _regexStringLiterals(src):
	"""Last-resort literal extraction: both quote styles, escape-aware."""
	import re as _re
	pat = _re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"'
						r"|'([^'\\]*(?:\\.[^'\\]*)*)'")
	out = []
	for m in pat.finditer(src):
		out.append(m.group(1) if m.group(1) is not None else m.group(2))
	return out


def _scriptStringLiterals(scriptSource):
	if not isinstance(scriptSource, basestring) or not scriptSource.strip():
		return []
	try:
		import ast
		import io
		import tokenize
		from tokenize import STRING
		src = scriptSource
		if isinstance(src, str):
			# io.StringIO requires unicode on Python 2.
			src = src.decode('utf-8', 'replace')
		tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
	except Exception:
		return _regexStringLiterals(scriptSource)

	out = []
	for tok in tokens:
		# Python 2's tokenize yields plain 5-tuples
		# (type, string, start, end, line) -- there is no .type/.string.
		toktype, tokstring = tok[0], tok[1]
		if toktype != STRING:
			continue
		try:
			value = ast.literal_eval(tokstring)
		except Exception:
			try:
				value = _stripQuotes(tokstring)
			except Exception:
				continue
		if isinstance(value, basestring):
			out.append(value)
	return out


def _walkDeepContext(node, viewPath, context):
	if not isinstance(node, dict):
		return
	ctype = node.get('type') or ''
	meta = node.get('meta') or {}
	name = meta.get('name') or ctype or '?'
	props = node.get('props') or {}
	propConfig = node.get('propConfig') or {}

	if isinstance(propConfig, dict):
		for propKey, cfg in propConfig.items():
			if not isinstance(cfg, dict):
				continue
			binding = cfg.get('binding') if isinstance(cfg.get('binding'), dict) else None
			if binding:
				context['bindings'].append({
					'viewPath': viewPath,
					'componentName': name,
					'componentType': ctype,
					'prop': propKey,
					'bindingType': binding.get('type'),
					'config': binding.get('config'),
				})
			for alt in ('tag', 'property', 'expression', 'query'):
				altCfg = cfg.get(alt)
				if altCfg and isinstance(altCfg, dict):
					context['bindings'].append({
						'viewPath': viewPath,
						'componentName': name,
						'componentType': ctype,
						'prop': propKey,
						'bindingType': alt,
						'config': altCfg,
					})

	events = node.get('events') or {}
	if isinstance(events, dict):
		for eventName, eventBlock in events.items():
			if not isinstance(eventBlock, dict):
				continue
			inner = eventBlock.get('event') or eventBlock
			if not isinstance(inner, dict):
				continue
			cfg = inner.get('config') or {}
			script = cfg.get('script') if isinstance(cfg, dict) else None
			if isinstance(script, basestring) and script.strip():
				literals = _scriptStringLiterals(script)
				if literals:
					context['scripts'].append({
						'viewPath': viewPath,
						'componentName': name,
						'componentType': ctype,
						'event': eventName,
						'literals': literals,
					})

	if ctype == 'ia.display.view':
		path = props.get('path') if isinstance(props, dict) else None
		if isinstance(path, basestring) and path.strip():
			clean = path.strip('/')
			inline = props.get('params')
			params = dict(inline) if isinstance(inline, dict) else {}
			context['embedded'].append({'viewPath': viewPath, 'path': clean, 'params': params})
	inlineParams = node.get('params')
	if isinstance(inlineParams, dict) and ctype != 'ia.display.view':
		context['embeddedParams'].append({
			'viewPath': viewPath,
			'componentName': name,
			'componentType': ctype,
			'params': dict(inlineParams),
		})

	children = node.get('children')
	if isinstance(children, list):
		for child in children:
			_walkDeepContext(child, viewPath, context)


def discoverDeepContext(viewPath, project=None):
	rootView = _safeViewPath(viewPath)
	pending = [rootView]
	visited = []
	unresolved = []
	context = {
		'rootViewPath': rootView,
		'viewsVisited': [],
		'bindings': [],
		'scripts': [],
		'embedded': [],
		'embeddedParams': [],
		'unresolvedViews': [],
	}
	while pending:
		current = pending.pop(0)
		if current in visited:
			continue
		visited.append(current)
		try:
			viewJson = _readViewJson(current, project)
		except Exception as exc:
			unresolved.append({'viewPath': current, 'error': str(exc)})
			continue
		_walkDeepContext(viewJson.get('root', {}), current, context)
		for entry in context['embedded']:
			childPath = entry.get('path')
			if childPath and childPath not in visited and childPath not in pending:
				pending.append(childPath)
	context['viewsVisited'] = visited
	context['unresolvedViews'] = unresolved
	return context


def _stringLiteralPool(context):
	seen = set()
	pool = []
	for entry in context.get('scripts') or []:
		for value in entry.get('literals') or []:
			if not isinstance(value, basestring):
				continue
			v = value.strip()
			if not v or v in seen:
				continue
			seen.add(v)
			pool.append(v)
	return pool


def _bindingSummaryText(context):
	lines = []
	for b in context.get('bindings') or []:
		cfg = b.get('config')
		try:
			cfgText = json.dumps(cfg, ensure_ascii=False) if cfg is not None else u'<none>'
		except Exception:
			cfgText = repr(cfg)
		if len(cfgText) > 240:
			cfgText = cfgText[:237] + u'...'
		lines.append(u"- {vp} :: {name} ({ctype}).{prop} -> {bt} {cfg}".format(
			vp=b.get('viewPath'), name=b.get('componentName'), ctype=b.get('componentType'),
			prop=b.get('prop'), bt=b.get('bindingType'), cfg=cfgText))
	return u"\n".join(lines)


_KEY_LIKE_PARENTS = frozenset(['dataSources', 'series', 'legend', 'axes', 'categories',
								'labels', 'markers', 'datasets', 'columns', 'rows',
								'options', 'items'])

_LEAF_VALUE_SKIP_KEYS = frozenset(['x', 'y', 'width', 'height', 'name', 'id', 'tagPath', 'path',
									'url', 'URL', 'sql', 'format', 'mode', 'style', 'color',
									'background', 'border', 'position', 'value', 'fallback',
									'enabled', 'visible', 'selectable', 'selected', 'time',
									'step', 'direction', 'wrap', 'justifyContent', 'alignItems',
									'basis', 'minHeight', 'maxHeight', 'minWidth', 'maxWidth',
									'gap', 'padding', 'margin', 'render', 'opacity', 'source',
									'target', 'class', 'dataType', 'family', 'weight', 'size',
									'grow', 'shrink', 'primarySort', 'renderTime'])

import re as _re


def _isUserFacingText(s):
	if not isinstance(s, basestring):
		return False
	t = s.strip()
	if not t or len(t) < 2 or len(t) > 250:
		return False
	if t in ('true', 'false', 'null', 'inherit'):
		return False
	if _re.match(r'^#\w+', t) and len(t) <= 9:
		return False
	if _re.match(r'^\d', t):
		return False
	return True


def _buildSourceSkeleton(node):
	"""Walk a Perspective view JSON and produce a compact list of (path, value) lines.
	Captures every user-facing source string plus every label-like key inside
	dataSources/series/legend/etc. The line set is ~10x smaller than the
	minified view.json, which keeps the discovery prompt under the gateway
	non-streaming limit. Returns a single newline-joined string.
	"""
	out = []
	def _walk(n, path):
		if isinstance(n, dict):
			for k, v in n.items():
				childPath = path + (str(k),)
				if k in _KEY_LIKE_PARENTS and isinstance(v, dict):
					for subKey in v.keys():
						if isinstance(subKey, basestring) and _isUserFacingText(subKey):
							out.append('%s.<key> = %s' % ('.'.join(childPath), json.dumps(subKey, ensure_ascii=False)))
				_walk(v, childPath)
		elif isinstance(n, list):
			for i, item in enumerate(n):
				_walk(item, path + (str(i),))
		elif isinstance(n, basestring) and _isUserFacingText(n):
			last = path[-1] if path else ''
			if last in _LEAF_VALUE_SKIP_KEYS:
				return
			if _re.match(r'^[\w./:_\[\]<>%,\-]+', n) and not _re.search(r' ', n):
				if not _re.search(r'[A-Z][a-z]|[a-z][A-Z]', n):
					return
			out.append('%s = %s' % ('.'.join(path), json.dumps(n, ensure_ascii=False)))
	_walk(node, ())
	seen = set()
	deduped = []
	for line in out:
		if line in seen:
			continue
		seen.add(line)
		deduped.append(line)
	return '\n'.join(deduped)


def _deepDiscoveryPrompt(sourceLocale, targetLocale, viewPath, skeleton):
	template = (
		"Inspect this SKELETON of an Ignition Perspective view for translation candidates. "
		"Each line is \"<dotted.path.to.prop> = <value>\" or \"<dotted.path>.<key> = <key>\". "
		"Find every user-visible source string and preserve each source exactly. "
		"Exclude tag paths, URLs, SQL, CSS, identifiers, format tokens, data keys, numbers, units, brands, "
		"and proper names unless clearly displayed text. "
		"Return exactly one JSON object with a top-level sources array. "
		"Required shape: {{\"sources\":[{{\"source\":\"exact text\",\"confidence\":\"literal\",\"translate\":true,\"reason\":\"short\"}}],\"context_notes\":[\"...\"]}}. "
		"Do not return a bare key, a list, translations, markdown, or code fences. "
		"Translate discovered sources from {src} to {tgt}.\nVIEW_PATH: {path}\nSKELETON:\n{skel}"
	)
	return template.format(src=sourceLocale, tgt=targetLocale, path=viewPath, skel=skeleton)


def _deepTranslationPrompt(sourceLocale, targetLocale, sources):
	return (
		"Translate each source string below from {src} to {tgt}. Preserve source exactly and "
		"return ONLY valid JSON, no Markdown, with exactly {{\"translations\":[{{\"source\":\"exact source\",\"translation\":\"translated text\",\"translate\":true}}]}}. "
		"For translate:false use the original text. Do not omit or rename sources. Preserve "
		"placeholders and formatting tokens. INPUT SOURCES: {items}"
	).format(src=sourceLocale, tgt=targetLocale, items=json.dumps(sources, ensure_ascii=False, separators=(',', ':')))


def _coerceJsonObject(raw):
	"""Parse the AI response as JSON without raising on shape; return whatever shape comes back.

	Robust to:
		* triple-backtick fences (with or without a language tag) anywhere in the string
		* prose before and after the JSON
		* top-level arrays as well as dicts

	On success: returns the parsed value (dict, list, scalar, or None for empty input).
	On failure: raises ValueError whose message includes a 240-char preview of the raw input.
	"""
	text = raw if isinstance(raw, basestring) else str(raw) if raw is not None else ''
	s = text.strip()
	if not s:
		return None

	def _stripFence(body):
		if body.startswith('\x60\x60\x60'):
			if '\n' in body:
				body = body.split('\n', 1)[1]
			else:
				body = body[3:]
			stripped = body.rstrip()
			if stripped.endswith('\x60\x60\x60'):
				stripped = stripped[:-3]
			return stripped.strip()
		fenceOpen = body.find('\n\x60\x60\x60')
		if fenceOpen >= 0:
			afterOpen = body.find('\n', fenceOpen + 1)
			if afterOpen >= 0:
				fenceClose = body.rfind('\n\x60\x60\x60')
				if fenceClose > afterOpen:
					return body[afterOpen + 1:fenceClose].strip()
		return body

	s = _stripFence(s)

	decoder = json.JSONDecoder()
	bracketPositions = []
	for openChar in ('{', '['):
		idx = -1
		while True:
			idx = s.find(openChar, idx + 1)
			if idx < 0:
				break
			bracketPositions.append(idx)
	bracketPositions.sort()

	lastExc = None
	try:
		return json.loads(s)
	except Exception as exc:
		lastExc = exc

	candidates = []
	for pos in bracketPositions:
		try:
			value, _end = decoder.raw_decode(s[pos:])
			candidates.append((pos, value))
		except Exception:
			continue
	if candidates:
		pos, value = candidates[0]
		return value

	preview = s[:240].replace('\n', ' ')
	raise ValueError('AI response was not valid JSON (preview=%r): %s' % (preview, lastExc))


def _coerceEnvelope(raw, key, kind):
	"""Coerce + shape-check an AI response that should be `{key: [...]}`. Accepts: dict with that key as a list, or a top-level list (wrapped). Raises a ValueError that includes a 240-char preview when neither shape fits."""
	data = _coerceJsonObject(raw)
	try:
		head = raw if isinstance(raw, basestring) else repr(raw)
		preview = head[:240].replace('\n', ' ')
	except Exception:
		preview = '<unrepr-able>'
	if isinstance(data, dict):
		rows = data.get(key)
		if isinstance(rows, list):
			return rows
		raise ValueError('%s response must contain a %s array (got dict with key=%r; preview=%r)' % (kind, key, type(rows).__name__, preview))
	if isinstance(data, list):
		return data
	raise ValueError('%s response must be a JSON object with a %s array (got %s; preview=%r)' % (kind, key, type(data).__name__, preview))


def _jsonObject(raw):
	data = _coerceJsonObject(raw)
	if not isinstance(data, dict):
		raise ValueError('AI response must be a JSON object (got %s)' % type(data).__name__)
	return data


def _parseDiscovery(raw):
	try:
		data = _coerceJsonObject(raw)
		if isinstance(data, list):
			data = {'sources': data}
		if not (isinstance(data, dict) and isinstance(data.get('sources'), list)):
			raise ValueError('Discovery response must contain a sources array')
		rows = data['sources']
	except Exception:
		logger.error('two-step deep: discovery parse failed: %s' % sys.exc_info()[1])
		raise
	parsed, seen = [], set()
	for row in rows:
		if not isinstance(row, dict):
			continue
		src = row.get('source')
		if not isinstance(src, basestring) or not src or src in seen:
			continue
		conf = row.get('confidence') or 'literal'
		if conf not in CONFIDENCE_LEVELS:
			conf = 'literal'
		seen.add(src)
		parsed.append({'source': src, 'confidence': conf,
						'translate': bool(row.get('translate', True)),
						'reason': row.get('reason') if isinstance(row.get('reason'), basestring) else ''})
	notes = data.get('context_notes') if isinstance(data.get('context_notes'), list) else []
	return parsed, notes


def _parseDeepTranslations(raw, expectedSources):
	try:
		data = _coerceJsonObject(raw)
		if isinstance(data, list):
			data = {'translations': data}
		if not (isinstance(data, dict) and isinstance(data.get('translations'), list)):
			raise ValueError('Translation response must contain a translations array')
		rows = data['translations']
	except Exception:
		logger.error('two-step deep: translation parse failed: %s' % sys.exc_info()[1])
		raise
	parsed, seen = [], set()
	for row in rows:
		if not isinstance(row, dict):
			continue
		src = row.get('source')
		if isinstance(src, basestring) and src and src not in seen:
			seen.add(src)
			parsed.append({'source': src,
							'translation': row.get('translation') if isinstance(row.get('translation'), basestring) else '',
							'translate': bool(row.get('translate', True))})
	return parsed


def _requestTwoStep(sourceLocale, targetLocale, viewPath, skeleton, agentName):
	skelLen = len(skeleton) if isinstance(skeleton, basestring) else 0
	logger.info("two-step deep: view=%s agent=%s skeleton_chars=%d" % (viewPath, agentName, skelLen))
	try:
		discoveryRaw = system.ai.sendMessage(agentName, _deepDiscoveryPrompt(sourceLocale, targetLocale, viewPath, skeleton))
	except:
		# Bare except: system.ai.sendMessage raises Java exceptions, which
		# "except Exception" does not catch in Jython
		exc = sys.exc_info()[1]
		try:
			preview = repr(exc)[:500]
		except:
			preview = '<unrepr-able>'
		logger.error("two-step deep: discovery call raised type=%s msg=%r preview=%s" % (type(exc).__name__, str(exc), preview))
		raise
	try:
		rawType = type(discoveryRaw).__name__
		rawLen = len(discoveryRaw) if isinstance(discoveryRaw, basestring) else -1
		rawHead = (discoveryRaw[:500] if isinstance(discoveryRaw, basestring) else repr(discoveryRaw))
		logger.info("two-step deep: discovery response type=%s bytes=%d head=%r" % (rawType, rawLen, rawHead))
	except Exception as logExc:
		logger.error("two-step deep: could not log discovery response: %s" % logExc)
	discovered, notes = _parseDiscovery(discoveryRaw)
	if not discovered:
		raise ValueError('Discovery response contained no sources')
	translationRaw = system.ai.sendMessage(agentName, _deepTranslationPrompt(sourceLocale, targetLocale, discovered))
	try:
		tType = type(translationRaw).__name__
		tLen = len(translationRaw) if isinstance(translationRaw, basestring) else -1
		tHead = (translationRaw[:500] if isinstance(translationRaw, basestring) else repr(translationRaw))
		logger.info('two-step deep: translation response type=%s bytes=%d head=%r' % (tType, tLen, tHead))
	except Exception as logExc:
		logger.error('two-step deep: could not log translation response: %s' % logExc)
	translations = _parseDeepTranslations(translationRaw, discovered)
	bySource = {row['source']: row for row in translations}
	merged = []
	missing = []
	for row in discovered:
		tr = bySource.get(row['source'])
		if tr is None:
			missing.append(row['source'])
			continue
		tr.update({'confidence': row['confidence'], 'reason': row['reason']})
		merged.append(tr)
	return {'translations': merged, 'missing': missing, 'contextNotes': notes, 'discovered': discovered}


def translateDeep(viewPath, targetLocale, sourceLocale='en-US', agentName=DEEP_AGENT_NAME, project=None):
	"""Discover user-facing values from the full view, then translate only that list."""
	locale = (targetLocale or '').strip()
	if not locale:
		raise ValueError('targetLocale is required')
	rootViewJson = _readViewJson(viewPath, project)
	try:
		skeleton = _buildSourceSkeleton(rootViewJson)
	except Exception as exc:
		raise ValueError('Unable to build view skeleton for deep translation: %s' % exc)

	literalDiscovery = discoverTerms(viewPath, project=project)
	context = discoverDeepContext(viewPath, project=project)
	literalPool = list(literalDiscovery.get('uniqueTerms') or [])
	scriptPool = _stringLiteralPool(context)
	try:
		result = _requestTwoStep(sourceLocale, locale, viewPath, skeleton, agentName)
	except:
		# Bare except: the two-step path makes system.ai.sendMessage calls,
		# whose Java exceptions "except Exception" would let escape
		exc = sys.exc_info()[1]
		logger.error('two-step deep translation failed: %s' % exc)
		return {'targetLocale': locale, 'sourceLocale': sourceLocale, 'mode': 'deep',
				'agentName': agentName, 'promptVersion': DEEP_PROMPT_VERSION,
				'literalPool': literalPool, 'scriptPool': scriptPool,
				'added': [], 'alreadyPresent': [], 'failed': [],
				'notInResponse': [], 'counts': {'added': 0, 'already': 0, 'failed': 1, 'notInResponse': 0,
												'byConfidence': {'literal': 0, 'script': 0, 'binding': 0, 'guess': 0}},
				'missingInResponse': {'literals': literalPool, 'scripts': scriptPool},
				'contextNotes': ['two-step deep translation failed: %s' % exc],
				'error': str(exc)}

	added, already, failed = [], [], []
	for row in result['translations']:
		text = row['source']
		translated = row.get('translation') if row.get('translate', True) else text
		if not isinstance(translated, basestring) or not translated.strip():
			failed.append({'key': text, 'error': 'AI returned no translation'})
			logger.warn('Failed to deep translate <%s>: AI returned no translation'  %(text))
			continue
		try:
			existing = system.util.translate(text, locale)
		except:
			logger.warn('translate lookup failed for <%s>: %s' % (text, sys.exc_info()[1]))
			existing = None
		if existing == translated:
			already.append({'key': text, 'confidence': row.get('confidence')})
			continue
		try:
			system.util.modifyTranslation(text, translated, locale)
			added.append({'key': text, 'translation': translated, 'confidence': row.get('confidence'), 'reason': row.get('reason')})
		except:
			exc = sys.exc_info()[1]
			failed.append({'key': text, 'error': str(exc)})
			logger.warn('Failed to deep translate <%s>: %s'  %(text, str(exc)))

	byConfidence = {'literal': 0, 'script': 0, 'binding': 0, 'guess': 0}
	for row in added:
		byConfidence[row.get('confidence') or 'literal'] += 1
	return {'targetLocale': locale, 'sourceLocale': sourceLocale, 'mode': 'deep',
			'agentName': agentName, 'promptVersion': DEEP_PROMPT_VERSION,
			'literalPool': literalPool, 'scriptPool': scriptPool,
			'added': added, 'alreadyPresent': already, 'failed': failed,
			'notInResponse': [{'key': x, 'pool': 'discovered'} for x in result['missing']],
			'counts': {'added': len(added), 'already': len(already), 'failed': len(failed),
						'notInResponse': len(result['missing']), 'byConfidence': byConfidence},
			'missingInResponse': {'literals': [], 'scripts': result['missing']},
			'contextNotes': result['contextNotes'], 'discoveredCount': len(result['discovered'])}

def listTermsDeep(viewPath, project=None):
	"""Convenience helper: walk the view and return both the literal terms and
	the event-script string literals. Lighter than translateDeep -- makes no
	LLM call."""
	literalDiscovery = discoverTerms(viewPath, project=project)
	context = discoverDeepContext(viewPath, project=project)
	scriptPool = _stringLiteralPool(context)
	return {
		'literals': literalDiscovery.get('uniqueTerms') or [],
		'literalTerms': literalDiscovery.get('terms') or [],
		'scriptLiterals': scriptPool,
		'bindings': context.get('bindings') or [],
		'embeddedViews': context.get('embedded') or [],
		'viewsVisited': context.get('viewsVisited') or [],
	}
