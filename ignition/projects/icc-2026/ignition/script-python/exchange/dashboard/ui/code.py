"""Button and binding logic for the Dashboard Agent's views.

Everything that persists a dashboard is ``exchange.dashboard.configs``; this module is
only the view-facing layer on top of it -- what each toolbar, dock and row
button does, and the one-line status text it leaves behind. Every button on
those views is a single call into here.

The views talk to each other by page-scoped message because the dashboard
component, the save dock and the saved-list popup are three different views:

	| Message                  | Sent by                    | Handled by              |
	|--------------------------|----------------------------|-------------------------|
	| ``exchange.dashboard.load``       | ``openSaved``              | Dashboard view root     |
	| ``exchange.dashboard.saved``      | ``saveFromDock``           | Dashboard view root     |
	| ``exchange.dashboard.setWidgets`` | the agent's write tool     | Dashboard view root     |
	| ``exchange.dashboard.manageStatus`` | row actions here         | Manage Dashboards root  |
"""

import sys
import time

import exchange.dashboard.configs

logger = system.util.getLogger("exchange.dashboard.script.ui.Actions")

SAVE_DOCK_ID = "dashboard-save"
MANAGE_POPUP_ID = "dashboard-manage"

# The name hint re-evaluates on every keystroke, so it reads the saved names
# from this cache instead of querying the database each time.
NAME_CACHE_SECS = 5
_nameCache = {"at": 0.0, "names": set()}


def _manageStatus(text):
	"""Show a line of status text in the saved-dashboards popup.

	Args:
		text (str): The message to show.
	"""
	system.perspective.sendMessage(messageType="exchange.dashboard.manageStatus", payload={"text": text}, scope="page")


def openSaveDock(widgets, name, isDemo):
	"""Open the save dock for the dashboard currently on screen.

	A dock rather than a popup: a popup re-focuses its own root on every
	re-render, so the name field inside one on a page full of polling widgets
	loses focus as fast as it can be typed into.

	Args:
		widgets (object): ``view.custom.widgets``, the live layout.
		name (str): The name the layout was last opened or saved under.
		isDemo (bool): Whether that saved row is flagged as a demo.

	Returns:
		str: Toast text for the toolbar -- empty when the dock opened.
	"""
	plain = exchange.dashboard.configs.plainWidgets(widgets)
	if not len(plain):
		return "Nothing to save yet -- ask the agent for a dashboard first."
	system.perspective.openDock(SAVE_DOCK_ID, params={"widgets": plain, "name": name, "isDemo": isDemo})
	return ""


def saveFromDock(name, widgets, isDemo):
	"""Save the layout from the save dock, then tell the page and close the dock.

	Args:
		name (str): The name typed into the dock. An existing name is updated.
		widgets (list): The layout passed to the dock when it opened.
		isDemo (bool): The dock's demo checkbox.

	Returns:
		str: Status text for the dock -- the validation message on failure.
	"""
	try:
		result = exchange.dashboard.configs.saveConfig(name, widgets, isDemo=isDemo)
	except:
		logger.warn("Saving dashboard %r failed: %s" % (name, sys.exc_info()[1]))
		return "Save failed: %s" % sys.exc_info()[1]

	# The cached names are stale the moment a new one is written
	_nameCache["at"] = 0.0
	if result["status"] in ("created", "updated"):
		# The Dashboard view owns the component; tell it what it is now called
		# so the toolbar stops saying "Unsaved" and a second Save updates the row
		payload = {"name": result["name"], "id": result["id"], "isDemo": result["isDemo"]}
		system.perspective.sendMessage(messageType="exchange.dashboard.saved", payload=payload, scope="page")
		system.perspective.closeDock(SAVE_DOCK_ID)
	return result.get("message") or ""


def _savedNames():
	"""Return the lower-cased names of every saved dashboard, cached briefly.

	Returns:
		set: Lower-cased dashboard names.
	"""
	if time.time() - _nameCache["at"] > NAME_CACHE_SECS:
		try:
			names = set((row["name"] or u"").strip().lower() for row in exchange.dashboard.configs.listConfigs())
		except:
			logger.warn("Could not list saved dashboards: %s" % sys.exc_info()[1])
			names = _nameCache["names"]
		_nameCache["names"] = names
		_nameCache["at"] = time.time()
	return _nameCache["names"]


def nameHint(name):
	"""Say whether saving under this name creates a dashboard or replaces one.

	Called from a runScript binding on the save dock, so it runs per keystroke;
	the saved names come from a short cache rather than the database.

	Args:
		name (str): The name currently typed into the dock.

	Returns:
		str: A one-line hint, or empty for an empty name.
	"""
	name = (name or u"").strip()
	if not name:
		return ""
	if name.lower() in _savedNames():
		return 'A dashboard called "%s" already exists -- saving replaces it.' % name
	return "Saved as a new dashboard."


def openSaved(configId):
	"""Load a saved dashboard onto the page and close the saved-list popup.

	Args:
		configId (int): The ``ex_icc_dashboard_config`` row id.
	"""
	config = exchange.dashboard.configs.getConfig(configId)
	if config is None:
		_manageStatus("That dashboard is gone -- it may have been deleted.")
		return
	# The dashboard component is on the page and this row is inside a popup,
	# so the layout goes back as a page-scoped message the Dashboard view applies
	payload = {"name": config["name"], "widgets": config["widgets"], "id": config["id"], "isDemo": config["isDemo"]}
	system.perspective.sendMessage(messageType="exchange.dashboard.load", payload=payload, scope="page")
	system.perspective.closePopup(MANAGE_POPUP_ID)


def applyDefault(view):
	"""Put the default dashboard on the page. Called from the view's onStartup.

	The page used to open on an empty grid. Loads
	``exchange.dashboard.configs.DEFAULT_NAME`` from the database, so re-saving a
	layout under that name changes what the page opens on. Never raises: a
	missing row or a database problem leaves the page blank, as it was before.

	Args:
		view (object): The Dashboard view (``self.view`` from the root).
	"""
	try:
		config = exchange.dashboard.configs.getConfig(exchange.dashboard.configs.DEFAULT_NAME)
	except:
		logger.warn("Could not load the default dashboard: %s" % sys.exc_info()[1])
		return
	if config is None:
		logger.warn("No default dashboard %r saved -- see sql/014_dashboard_default.sql" % exchange.dashboard.configs.DEFAULT_NAME)
		return
	view.custom.widgets = config["widgets"]
	view.custom.currentName = config["name"]
	view.custom.currentIsDemo = config["isDemo"]
	view.custom.toast = ""


def toggleDemo(configId, name, isDemo):
	"""Flip a saved dashboard's demo flag, which is what keeps it past midnight.

	Args:
		configId (int): The ``ex_icc_dashboard_config`` row id.
		name (str): Its name, for the status line.
		isDemo (bool): Its current flag.
	"""
	flag = not isDemo
	result = exchange.dashboard.configs.setDemo(configId, flag)
	if result["status"] == "protected":
		_manageStatus("\"%s\" is the default dashboard for this page, so it stays a demo." % name)
		return
	_manageStatus('"%s" is %s a demo dashboard.' % (name, "now" if flag else "no longer"))


def deleteSaved(configId, name, confirming):
	"""Two-click delete of a saved dashboard.

	Two clicks rather than a browser confirm(): a JS modal blocks every
	subsequent Perspective event in the session.

	Args:
		configId (int): The ``ex_icc_dashboard_config`` row id.
		name (str): Its name, for the status line.
		confirming (bool): True when the first click has already happened.

	Returns:
		bool: The row's new ``confirming`` state.
	"""
	if not confirming:
		_manageStatus('Click Delete again to remove "%s".' % name)
		return True
	result = exchange.dashboard.configs.deleteConfig(configId)
	if result["status"] == "protected":
		_manageStatus("\"%s\" is the default dashboard for this page and cannot be deleted." % name)
		return False
	_nameCache["at"] = 0.0
	_manageStatus('Deleted "%s".' % name)
	return False
