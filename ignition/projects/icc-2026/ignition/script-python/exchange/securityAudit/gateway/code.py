"""Gateway-wide security posture: properties, security levels, IdPs, zones,
API tokens.

None of this is reachable through a scripting API, so every read here is a
config resource file under ``data/config/resources/core/ignition``. That is the
same tree the repo commits, which means a finding raised here can be fixed in
git and deployed by a scan -- the citation and the fix location are the same
file.

The most important thing this module computes is **security-level
reachability**. A security level is only useful if some identity provider rule
actually grants it to somebody; a level that no rule grants can be required by a
page forever and nobody will ever satisfy it. Ignition will not warn about this,
because from the platform's point of view an unreachable level is
indistinguishable from a level that simply nobody qualifies for right now.
"""

import os

import exchange.securityAudit.core as core

logger = system.util.getLogger("exchange.securityAudit.Gateway")

_IGN = "ignition"

# The two levels Ignition ships with. They exist on every gateway and are not
# evidence that anybody configured anything.
STOCK_LEVELS = ["Authenticated", "Authenticated/Roles"]


def _path(*parts):
	return os.path.join(core.configRoot(), _IGN, *parts)


# ------------------------------------------------------- security properties

def securityProperties():
	"""The gateway's security-properties config, or {} if unreadable."""
	return core.readJson(_path("security-properties", "config.json")) or {}


# ----------------------------------------------------------- security levels

def _flatten(nodes, prefix=""):
	"""Depth-first flatten of the security-level tree into slash paths."""
	out = []
	for n in nodes or []:
		name = unicode(n.get("name") or "")
		if not name:
			continue
		full = "%s/%s" % (prefix, name) if prefix else name
		out.append({
			"path": full,
			"name": name,
			"description": unicode(n.get("description") or ""),
			"depth": full.count("/"),
		})
		out.extend(_flatten(n.get("children"), full))
	return out


def securityLevels():
	"""Every security level as a flat list of {path, name, description, depth}."""
	cfg = core.readJson(_path("security-levels", "config.json")) or {}
	return _flatten(cfg.get("securityLevels"))


def securityLevelPaths():
	"""Just the slash-delimited level paths."""
	return [lv["path"] for lv in securityLevels()]


# -------------------------------------------------------- identity providers

def _collectGrantedLevels(nodes, acc):
	"""Walk an IdP's securityLevelRules tree collecting every level it grants.

	The rule tree nests conditions and the levels they grant; the exact node
	shape has moved between releases, so this reads defensively -- any key that
	names a security level is collected, and unknown node shapes are walked
	rather than rejected.
	"""
	for n in nodes or []:
		if not isinstance(n, dict):
			continue
		for key in ("securityLevel", "name", "grantedLevel", "level"):
			val = n.get(key)
			if isinstance(val, basestring) and val:
				acc.add(unicode(val))
		for childKey in ("children", "nodes", "rules"):
			_collectGrantedLevels(n.get(childKey), acc)
	return acc


def identityProviders():
	"""Every configured IdP with the bits that matter to an audit."""
	root = _path("identity-provider")
	out = []
	for name in core.listDirs(root):
		cfg = core.readJson(os.path.join(root, name, "config.json")) or {}
		profile = cfg.get("profile") or {}
		settings = cfg.get("settings") or {}
		rules = (profile.get("securityLevelRules") or {}).get("nodes") or []
		granted = sorted(_collectGrantedLevels(rules, set()))
		out.append({
			"name": name,
			"type": unicode(profile.get("type") or "unknown"),
			"userSource": unicode(settings.get("userSource") or ""),
			"authMethods": [unicode((m or {}).get("type") or "")
			                for m in (settings.get("authMethods") or [])],
			"sessionInactivityTimeout": settings.get("sessionInactivityTimeout"),
			"sessionExp": settings.get("sessionExp"),
			"ruleCount": len(rules),
			"grantsLevels": granted,
			"file": core.rel(os.path.join(root, name, "config.json")),
		})
	return out


# ------------------------------------------------------------ security zones

def securityZones():
	"""Every security zone with its host/address filters."""
	root = _path("security-zone")
	out = []
	for name in core.listDirs(root):
		cfg = core.readJson(os.path.join(root, name, "config.json")) or {}
		out.append({
			"name": name,
			"config": cfg,
			"hostFilters": cfg.get("hostNames") or cfg.get("hosts") or [],
			"addressFilters": cfg.get("ipAddresses") or cfg.get("addresses") or [],
			"file": core.rel(os.path.join(root, name, "config.json")),
		})
	return out


# --------------------------------------------------------------- api tokens

def apiTokens():
	"""Every gateway API token. Secrets are hashed on disk and never read here."""
	root = _path("api-token")
	out = []
	for name in core.listDirs(root):
		cfg = core.readJson(os.path.join(root, name, "config.json")) or {}
		out.append({
			"name": name,
			"type": unicode(cfg.get("type") or ""),
			"description": unicode(cfg.get("description") or ""),
			# Presence only. The value is a hash and is deliberately not
			# included in any audit output.
			"hasHash": bool(cfg.get("tokenHash")),
			"expiration": cfg.get("expiration") or cfg.get("expiresAt"),
			"securityLevels": (cfg.get("permissions") or {}).get("securityLevels") or [],
			"file": core.rel(os.path.join(root, name, "config.json")),
		})
	return out


# ------------------------------------------------------------------ summary

def inventory():
	"""Everything this module knows, in one structure."""
	return {
		"securityProperties": securityProperties(),
		"securityLevels": securityLevels(),
		"identityProviders": identityProviders(),
		"securityZones": securityZones(),
		"apiTokens": apiTokens(),
	}


def _permIsOpen(perm):
	"""True when a permission block requires nothing at all.

	Both an absent block and one with an empty securityLevels list mean the
	same thing in practice: the check passes for anyone who gets that far.
	"""
	if not perm:
		return True
	return not (perm.get("securityLevels") or [])


def audit(inv=None):
	"""Findings for the gateway-posture domain."""
	inv = inv or inventory()
	out = []

	props = inv["securityProperties"]
	propCite = "config/resources/core/ignition/security-properties/config.json"

	if props.get("forceIdpAuth") is False:
		out.append(core.finding(
			"G001", "CRITICAL", "gateway",
			"Gateway does not force identity-provider authentication",
			"forceIdpAuth is false, so the gateway will serve pages without "
			"pushing the visitor through the configured identity provider "
			"first. Every page-level and view-level permission downstream is "
			"then evaluated against an unauthenticated session.",
			propCite,
			"Set forceIdpAuth to true.",
			{"forceIdpAuth": props.get("forceIdpAuth")}))

	if props.get("allowUserAdmin") is True:
		out.append(core.finding(
			"G002", "HIGH", "gateway",
			"User administration is exposed outside the Gateway config pages",
			"allowUserAdmin is true, which permits user and role management "
			"from outside the Gateway configuration section. That widens who "
			"can grant themselves a role well beyond the people who administer "
			"the gateway.",
			propCite,
			"Set allowUserAdmin to false unless a specific workflow needs it.",
			{"allowUserAdmin": True}))

	if props.get("allowDesignerSSO") is True:
		out.append(core.finding(
			"G003", "MEDIUM", "gateway",
			"Designer single sign-on is enabled",
			"allowDesignerSSO is true, so a browser session can be traded for "
			"Designer access without a fresh credential prompt. The Designer "
			"can rewrite every project resource on this gateway, which makes it "
			"a poor place to skip re-authentication.",
			propCite,
			"Disable Designer SSO and require an explicit login for Designer "
			"access.",
			{"allowDesignerSSO": True}))

	for key, label in (("readPermissions", "read"),
	                   ("writePermissions", "write"),
	                   ("designerPermissions", "Designer"),
	                   ("accessPermissions", "gateway access")):
		perm = props.get(key)
		if _permIsOpen(perm):
			sev = "HIGH" if key in ("writePermissions", "designerPermissions") else "MEDIUM"
			out.append(core.finding(
				"G004", sev, "gateway",
				"Gateway %s permission requires no security level" % label,
				"%s is configured with an empty securityLevels list, so it "
				"places no security-level requirement on %s. Access then falls "
				"back to whatever coarser mechanism is left -- here the "
				"designerRoleName setting (%s) -- rather than to the security "
				"level model this gateway otherwise uses."
				% (key, label, props.get("designerRoleName") or "unset"),
				propCite,
				"Populate %s with the security levels that should be required." % key,
				{"property": key, "value": perm}))

	timeout = props.get("userInactivityTimeout")
	if timeout == 0:
		out.append(core.finding(
			"G007", "MEDIUM", "gateway",
			"User sessions never expire on inactivity",
			"userInactivityTimeout is 0, so an authenticated session left open "
			"on an unattended HMI stays authenticated indefinitely.",
			propCite,
			"Set an inactivity timeout appropriate to the area -- minutes on a "
			"shared plant-floor terminal.",
			{"userInactivityTimeout": timeout}))

	# --- security level reachability -------------------------------------
	levels = inv["securityLevels"]
	granted = set()
	for idp in inv["identityProviders"]:
		for lv in idp["grantsLevels"]:
			granted.add(lv)

	customLevels = [lv for lv in levels if lv["path"] not in STOCK_LEVELS]
	if not customLevels:
		out.append(core.finding(
			"G006", "HIGH", "gateway",
			"No security levels beyond the two Ignition ships with",
			"The security-level tree contains only %s. Every permission check "
			"on this gateway therefore has nothing finer than 'is this person "
			"logged in' to test against, which is why so many permission blocks "
			"elsewhere in this report are empty -- there is nothing to put in "
			"them." % ", ".join(STOCK_LEVELS),
			"config/resources/core/ignition/security-levels/config.json",
			"Define a security-level tree that mirrors how access actually "
			"differs -- by area, by function, or by both -- then map roles onto "
			"it in the identity provider.",
			{"levels": [lv["path"] for lv in levels]}))

	for lv in customLevels:
		if lv["name"] not in granted and lv["path"] not in granted:
			out.append(core.finding(
				"G005", "MEDIUM", "gateway",
				"Security level %s is not granted by any identity provider" % lv["path"],
				"The level is defined in the security-level tree, but no "
				"identity provider rule grants it to anyone. Any page or "
				"resource that requires it is unreachable by every user, and "
				"Ignition raises no warning -- an unreachable level looks "
				"exactly like a level nobody currently qualifies for.",
				"config/resources/core/ignition/security-levels/config.json",
				"Add an identity-provider rule granting %s, or remove the level."
				% lv["path"],
				{"level": lv["path"]}))

	for idp in inv["identityProviders"]:
		if idp["ruleCount"] == 0:
			out.append(core.finding(
				"G006", "HIGH", "gateway",
				"Identity provider %s maps no roles to security levels" % idp["name"],
				"securityLevelRules is empty, so this IdP grants only the stock "
				"Authenticated level. The roles held in user source %s never "
				"become security levels, so no permission block anywhere on the "
				"gateway can distinguish one role from another."
				% (idp["userSource"] or "its user source"),
				idp["file"],
				"Add securityLevelRules mapping each role onto the security "
				"level it should confer.",
				{"idp": idp["name"], "userSource": idp["userSource"]}))

		if "basic" in idp["authMethods"] and idp["type"] == "internal":
			out.append(core.finding(
				"G010", "LOW", "gateway",
				"Identity provider %s authenticates with internal basic auth" % idp["name"],
				"This is fine for a demo or an isolated gateway, but it means "
				"credentials, password policy, lockout and MFA are all handled "
				"by Ignition's internal user source rather than by a corporate "
				"IdP.",
				idp["file"],
				"For production, federate to an external IdP (SAML/OIDC) so "
				"password policy and MFA are enforced centrally.",
				{"idp": idp["name"], "type": idp["type"]}))

	# --- api tokens -------------------------------------------------------
	for tok in inv["apiTokens"]:
		if not tok["expiration"]:
			out.append(core.finding(
				"G009", "MEDIUM", "gateway",
				"API token %s has no expiration" % tok["name"],
				"A non-expiring gateway API token is a long-lived credential "
				"that grants programmatic access, including the scan endpoints "
				"that reload configuration. If it leaks there is no point at "
				"which it stops working.",
				tok["file"],
				"Set an expiration and rotate the token on a schedule.",
				{"token": tok["name"]}))

	# --- security zones ---------------------------------------------------
	for zone in inv["securityZones"]:
		if not zone["hostFilters"] and not zone["addressFilters"]:
			out.append(core.finding(
				"G008", "LOW", "gateway",
				"Security zone %s has no host or address filter" % zone["name"],
				"The zone defines no host names and no IP addresses, so it "
				"either matches everything or nothing depending on how it is "
				"referenced. Either way it is not narrowing access.",
				zone["file"],
				"Give the zone real host/address criteria, or delete it if it "
				"is left over from a template.",
				{"zone": zone["name"]}))

	return core.sortFindings(out)
