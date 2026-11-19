"""The shared top bar's Translate button (Exchange/.../Navigation/TopNavigation).

The button translates whichever page is open: ``page-config`` is the single
source of truth for which view backs a URL, so the root view is resolved from
the live page path rather than pinned to one page. The button is a single call
into ``translatePage``; the status label binds to the string it returns.

``pageStatus`` tells the top bar which languages the open page is already
translated into, so each locale button can show green or grey and the
Translate button can hide itself once there is nothing left to do.
"""

import json
import os
import re
import sys

# exchange.aiTools is reached through the project library's global namespace, the way
# exchange.aiTools itself references its own packages, rather than imported here

logger = system.util.getLogger("exchange.translation.script.ui.Translate")

SOURCE_LOCALE = "en-US"

# The locale buttons in the top bar, in the order they appear there.
LOCALES = ("en-US", "es-MX", "de-DE", "fr-FR")

# How many untranslated terms the status tooltip lists before summarising.
MAX_LISTED = 12

# A term with no letters in it ("1,742", "%", "3") reads the same in every
# language, so it never counts against a page being translated.
_HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


def _resolveViewPath(pagePath):
	"""Return the root view path registered for a page URL, or None.

	Args:
		pagePath (str): ``page.props.path``, e.g. ``/alarm-flood-event``.

	Returns:
		str: The view path, or None when no page is registered for it.
	"""
	return exchange.aiTools.translator.pagePath.resolveViewPath(pagePath)


def translatePage(pagePath, targetLocale):
	"""Scan the page's root view and register translations for its literals.

	Args:
		pagePath (str): ``page.props.path`` of the page being viewed.
		targetLocale (str): ``session.props.locale``, the language to add.

	Returns:
		str: A status line for the top bar.

		Example: "Done: added=31 already=13 failed=0"
	"""
	targetLocale = targetLocale or SOURCE_LOCALE
	viewPath = _resolveViewPath(pagePath)
	if not viewPath:
		return "No view registered for %s" % pagePath
	if targetLocale == SOURCE_LOCALE:
		return "Pick a target language first"
	try:
		result = exchange.aiTools.translator.scan.scanView(viewPath, targetLocale)
	except:
		error = sys.exc_info()[1]
		logger.warn("Translating %s to %s failed: %s" % (viewPath, targetLocale, error))
		return "Error: %s" % error
	added = len(result.get("added") or [])
	already = len(result.get("alreadyPresent") or [])
	failed = len(result.get("failed") or [])
	return "Done: added=%s already=%s failed=%s" % (added, already, failed)


def _localeKeys(locale):
	"""Return the set of terms registered for a locale, or None if unreadable.

	The gateway stores each locale's translations as a key -> translation map
	in ``data/config/.../ignition/translations/<locale>.json``. Reading the file
	is the only way to tell "registered with an identical translation" (a
	proper noun) apart from "never registered": ``system.util.translate``
	returns the source text in both cases, and ``system.i18n`` exposes no
	per-locale key list.

	Args:
		locale (str): A locale code such as ``es-MX``.

	Returns:
		set: The registered terms. Empty when the locale has no file yet;
			None when the translations folder itself cannot be read.
	"""
	folder = os.path.join(exchange.securityAudit.core.configRoot(), "ignition", "translations")
	if not os.path.isdir(folder):
		return None
	for name in (locale, locale.split("-")[0]):
		path = os.path.join(folder, name + ".json")
		if os.path.isfile(path):
			try:
				with open(path, "r") as handle:
					data = json.load(handle)
			except:
				logger.warn("Could not read translations file %s: %s" % (path, sys.exc_info()[1]))
				return None
			return set(key for key, value in data.items() if value is not None)
	return set()


def _isTranslated(term, locale, keys):
	"""True when a term has a translation for a locale.

	Either source is enough. The file catches a term registered as itself (a
	proper noun) that the live lookup cannot see; the live lookup catches a
	translation the gateway is serving from memory after the file was reset
	(the deploy's ``git reset --hard`` rewrites it every night).
	"""
	if keys is not None and term in keys:
		return True
	return system.util.translate(term, locale) != term


def _flag(locale):
	"""``es-MX`` -> ``esMX``: an expression-safe key for a locale."""
	return locale.replace("-", "")


def pageStatus(pagePath, refresh=None):
	"""Report which top-bar languages the open page is translated into.

	A page counts as translated into a locale when every literal the Translate
	button would scan has a translation for it -- the same term set
	``translatePage`` registers, so pressing the button is what turns a locale
	green. Terms with no letters are left out. The source locale is always
	translated.

	Args:
		pagePath (str): ``page.props.path`` of the page being viewed.
		refresh (object): Ignored. The top bar passes its status line here so
			the binding re-evaluates when a translate run finishes.

	Returns:
		dict: ``terms`` (literals on the page), and ``translated`` /
			``missing`` / ``missingText`` (the untranslated terms, one per
			line) keyed by expression-safe locale (``esMX``).

		Example: {"terms": 31, "translated": {"enUS": True, "esMX": True, "deDE": False, "frFR": False},
			"missing": {"enUS": 0, "esMX": 0, "deDE": 31, "frFR": 31}}
	"""
	status = {
		"terms": 0,
		"translated": dict((_flag(locale), locale == SOURCE_LOCALE) for locale in LOCALES),
		"missing": dict((_flag(locale), 0) for locale in LOCALES),
		"missingText": dict((_flag(locale), "") for locale in LOCALES),
	}
	viewPath = _resolveViewPath(pagePath)
	if not viewPath:
		return status
	try:
		terms = exchange.aiTools.translator.scan.discoverTerms(viewPath)["uniqueTerms"]
	except:
		logger.warn("Scanning %s for translation status failed: %s" % (viewPath, sys.exc_info()[1]))
		return status
	terms = [term for term in terms if _HAS_LETTER.search(term)]
	status["terms"] = len(terms)
	for locale in LOCALES:
		if locale == SOURCE_LOCALE:
			continue
		keys = _localeKeys(locale)
		missing = [term for term in terms if not _isTranslated(term, locale, keys)]
		status["translated"][_flag(locale)] = bool(terms) and not missing
		status["missing"][_flag(locale)] = len(missing)
		# For the status label's tooltip, so "2 terms untranslated" can be read
		shown = [term if len(term) <= 80 else term[:77] + "..." for term in missing[:MAX_LISTED]]
		if len(missing) > MAX_LISTED:
			shown.append("... and %d more" % (len(missing) - MAX_LISTED))
		status["missingText"][_flag(locale)] = "\n".join(shown)
	return status
