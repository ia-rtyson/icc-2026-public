"""Browser-reachable URLs for the demo services sitting beside this gateway.

Every service in this compose stack -- YouTrack, the Gmail look-alike over
Mailpit, Mailpit's own UI, pgAdmin -- is published on the **same host** as the
gateway, on its own port. So the only unknown in a link to one of them is the
hostname the operator's browser used, and hardcoding it pins the demo to one
machine: ``localhost`` works on the demo laptop and is simply wrong on the AI
server, where the page is served from ``demo-server.example.com``.

**``session.props.gateway.address`` is the one thing that knows that hostname.**
Perspective fills it in with the address the browser actually connected to,
published port included (``http://localhost:8088`` here, where the gateway
itself only ever sees ``:8088`` inside its container). Nothing gateway-side
substitutes: ``system.util.getGatewayAddress()`` and the servlet's own view of
itself return the container-internal address, and ``session.props.host`` is the
*client's* IP (the docker bridge), not a hostname.

That means **these functions need a session** -- pass the address in from a
Perspective script. An agent tool or a gateway timer has no session and will
fall back to ``localhost``, which is only right on the gateway's own machine.
For container-to-container calls use the internal address instead (see
``exchange.issueReport.pipeline``'s ``YOUTRACK_INTERNAL_URL``), never one of these.

Each service takes two environment overrides for a deployment where it is not
simply beside the gateway (reverse proxy, separate box): a full base URL, which
wins outright, and a port-only override. Both are read from the gateway
*process* environment, so they have to be passed into the container by the
ignition service's ``environment:`` block in docker-compose.yml, and the
container recreated (``docker compose up -d ignition``) -- a rescan will not
pick up a new env var.

    | Service         | Function          | URL override    | Port override    | Default |
    |-----------------|-------------------|-----------------|------------------|---------|
    | Gmail/Mailpit   | ``mailboxUrl``    | ``GMAIL_URL``   | ``GMAIL_PORT``   | 8090    |
    | YouTrack        | ``youtrackUrl``   | ``YOUTRACK_URL``| ``YOUTRACK_PORT``| 8089    |

``exchange.issueReport.report.youtrackUrl`` is the long-standing public name for the YouTrack
one and delegates here, so there is a single host parser rather than a copy per
caller.
"""

from java.lang import System as JavaSystem
import os

logger = system.util.getLogger("exchange.demo.Hosts")

#: Published ports from docker-compose.yml. Overridable per service by env var.
GMAIL_PORT = "8090"
YOUTRACK_PORT = "8089"


def env(name):
	"""A gateway-process environment variable, or None if unset/blank."""
	val = JavaSystem.getenv(name)
	if not val:
		val = os.environ.get(name)
	return (val or "").strip() or None


def hostOf(address):
	"""The hostname out of a URL -- no scheme, no port, no path.

	Done by hand rather than with ``urlparse`` so a bracketed IPv6 literal
	(``http://[::1]:8088``) survives intact.

	Args:
		address: a URL, typically ``session.props.gateway.address``.

	Returns:
		str hostname, or None if there was nothing to read.
	"""
	if not address:
		return None
	addr = unicode(address).strip()
	if "://" in addr:
		addr = addr.split("://", 1)[1]
	addr = addr.split("/", 1)[0]
	if addr.startswith("["):
		close = addr.find("]")
		return addr[:close + 1] if close != -1 else addr
	return addr.split(":", 1)[0] or None


def serviceUrl(gatewayAddress, defaultPort, urlEnv=None, portEnv=None, path=None):
	"""A browser-reachable base URL for a service published beside this gateway.

	Swapping the gateway address's port for the service's is the whole trick;
	see the module docstring for why that address is the only usable source.

	Args:
		gatewayAddress: value of ``session.props.gateway.address``. Falls back
			to localhost when empty, which is only right on the gateway's own
			machine.
		defaultPort: the service's published port, used when nothing overrides it.
		urlEnv: name of an env var holding a full base URL, which wins outright.
		portEnv: name of an env var holding just a port.
		path: optional route to append, e.g. ``issue/UI-14``.

	Returns:
		str, with no trailing slash.
	"""
	base = env(urlEnv) if urlEnv else None
	if not base:
		host = hostOf(gatewayAddress) or "localhost"
		port = (env(portEnv) if portEnv else None) or defaultPort
		base = "http://%s:%s" % (host, port)
	base = base.rstrip("/")
	if path:
		base = "%s/%s" % (base, unicode(path).strip().lstrip("/"))
	return base


def mailboxUrl(gatewayAddress=None, path=None):
	"""The Gmail look-alike inbox over the Mailpit sink (compose service ``gmail``).

	Where the Alarm Notification Agent's emails land -- nothing leaves the box,
	Mailpit is an SMTP sink. Overrides: ``GMAIL_URL`` / ``GMAIL_PORT``.
	"""
	return serviceUrl(gatewayAddress, GMAIL_PORT, "GMAIL_URL", "GMAIL_PORT", path)


def youtrackUrl(gatewayAddress=None, path=None):
	"""The YouTrack board behind the Report -> Build -> Execute pipeline.

	Overrides: ``YOUTRACK_URL`` / ``YOUTRACK_PORT``. Note this is the
	*browser-facing* URL; a gateway-side REST call wants
	``YOUTRACK_INTERNAL_URL`` instead.
	"""
	return serviceUrl(gatewayAddress, YOUTRACK_PORT, "YOUTRACK_URL", "YOUTRACK_PORT", path)


# ---------------------------------------------------------------------------
# Perspective button actions
#
# The Alarm Flood Event pages' mail button and Line Overview's YouTrack button
# are single calls into these, passing ``self.session.props.gateway.address``.
# navigate(), not openUrl(): there is no system.perspective.openUrl on this
# build, and calling it fails only in the gateway log, so the button would look
# inert.
# ---------------------------------------------------------------------------

import sys


def _openInNewTab(url):
	"""Open a URL in a new browser tab for the calling Perspective session.

	Args:
		url (str): The absolute URL to open.
	"""
	try:
		system.perspective.navigate(url=url, newTab=True)
	except:
		logger.warn("Could not open %s: %s" % (url, sys.exc_info()[1]))


def openMailbox(gatewayAddress=None):
	"""Open the Gmail look-alike inbox in a new tab, beside this gateway.

	Args:
		gatewayAddress (str): ``session.props.gateway.address``, the host the
			browser used. Falls back to localhost when empty.
	"""
	_openInNewTab(mailboxUrl(gatewayAddress))


def openYouTrack(gatewayAddress=None):
	"""Open the YouTrack board in a new tab, beside this gateway.

	Args:
		gatewayAddress (str): ``session.props.gateway.address``, the host the
			browser used. Falls back to localhost when empty.
	"""
	_openInNewTab(youtrackUrl(gatewayAddress))
