"""Everything else that carries a permission: AI agents, MCP servers, agent
tool bundles, WebDev endpoints, named queries.

This is the domain most likely to be missed by a manual review, because none of
it appears on a "security" page in the Gateway UI. An AI agent's permission
block lives in the agent's own config resource; a WebDev endpoint's auth
requirement lives in the endpoint's config.json; an MCP server's tool exposure
lives in the MCP module's config. Nothing collects them, so nothing shows you
that they are all empty at once.

The distinction that matters here is between a resource that *reads* and one
that *acts*. An unprotected tool that browses tags leaks information. An
unprotected tool that creates tags, writes values or runs an update query is a
control-system write path with no authentication in front of it, and this module
grades it accordingly.
"""

import os

import exchange.securityAudit.core as core

logger = system.util.getLogger("exchange.securityAudit.Resources")

# The AI modules were renamed in 2027.2.0-beta1 (com.inductiveautomation.ai ->
# ...catalyst.core, ...ai.agent -> ...catalyst.agent), and a module's config
# folder is named after its id. Newest name first; the old one is the fallback
# for a gateway still on a pre-rename build.
AGENT_MODULES = ("com.inductiveautomation.catalyst.agent",
                 "com.inductiveautomation.ai.agent")


def _moduleDir(base, *parts):
	"""First existing <base>/<agent module>/<parts>, else the newest name.

	Args:
		base (str): configRoot() or projectRoot().
		*parts (str): Path below the module folder, e.g. "agent".

	Returns:
		str: The directory to read. It may not exist; callers treat that as
			"no resources", the same as before the rename.
	"""
	for module in AGENT_MODULES:
		path = os.path.join(base, module, *parts)
		if os.path.isdir(path):
			return path
	return os.path.join(base, AGENT_MODULES[0], *parts)

# Substrings in a tool's implementation that mean it can change something.
WRITE_MARKERS = [
	"system.tag.write",
	"system.tag.configure",
	"system.tag.deleteTag",
	"system.db.runUpdateQuery",
	"system.db.runPrepUpdate",
	"system.db.runNamedQuery",  # a named query can be an INSERT/UPDATE
	"system.user.addUser",
	"system.user.editUser",
	"system.user.removeUser",
	"system.user.addRole",
	"system.file.writeFile",
	"system.perspective.sendMessage",
	"system.util.sendMessage",
]

# Tool-name prefixes that conventionally indicate a mutation in this project.
WRITE_NAME_PREFIXES = ["create_", "save_", "set_", "apply_", "delete_",
                       "update_", "write_", "start_", "run_"]


def _permLevels(perm):
	"""The security level names inside a permission block ([] when open)."""
	if not isinstance(perm, dict):
		return []
	out = []
	for entry in perm.get("securityLevels") or []:
		if isinstance(entry, basestring):
			out.append(unicode(entry))
		elif isinstance(entry, dict):
			for key in ("name", "path", "securityLevel", "level"):
				val = entry.get(key)
				if isinstance(val, basestring) and val:
					out.append(unicode(val))
					break
	return out


# ---------------------------------------------------------------- AI agents

def aiAgents():
	"""Every AI agent config resource on the gateway."""
	root = _moduleDir(core.configRoot(), "agent")
	out = []
	for name in core.listDirs(root):
		cfgPath = os.path.join(root, name, "config.json")
		cfg = core.readJson(cfgPath) or {}
		resCfg = core.readJson(os.path.join(root, name, "resource.json")) or {}
		toolsMap = cfg.get("tools") or {}
		toolNames = []
		for scope, names in toolsMap.items():
			if isinstance(names, list):
				for t in names:
					toolNames.append("%s:%s" % (scope, t))
			else:
				toolNames.append("%s:%s" % (scope, names))
		out.append({
			"name": name,
			"enabled": (resCfg.get("attributes") or {}).get("enabled", True),
			"model": (cfg.get("model") or {}).get("modelId"),
			"provider": (cfg.get("model") or {}).get("providerName"),
			"permissionLevels": _permLevels(cfg.get("permissions")),
			"tools": sorted(toolNames),
			"mcpConnections": cfg.get("mcpConnections") or [],
			"maxTurns": cfg.get("maxTurnsPerInvocation"),
			"file": core.rel(cfgPath),
		})
	return out


# -------------------------------------------------------------- MCP servers

def mcpServers():
	"""Every MCP server config, including which projects it exposes."""
	root = os.path.join(core.configRoot(), "com.inductiveautomation.mcp", "server-config")
	out = []
	for dirpath in core.findResourceDirs(root):
		cfgPath = os.path.join(dirpath, "config.json")
		cfg = core.readJson(cfgPath)
		if cfg is None:
			continue
		tools = cfg.get("tools") or {}
		out.append({
			"name": unicode(cfg.get("title") or os.path.basename(dirpath)),
			"version": unicode(cfg.get("version") or ""),
			"permissionLevels": _permLevels(cfg.get("permissions")),
			"tools": tools,
			"wildcards": sorted([k for k, v in tools.items() if v == "*"]),
			"file": core.rel(cfgPath),
		})
	return out


# ------------------------------------------------------------- tool bundles

def toolBundles(project=None):
	"""Every AI agent tool bundle in a project, graded read vs. write."""
	project = project or core.PROJECT
	root = _moduleDir(core.projectRoot(project), "tools")
	out = []
	for dirpath in core.findResourceDirs(root):
		name = os.path.basename(dirpath)
		resCfg = core.readJson(os.path.join(dirpath, "resource.json")) or {}
		attrs = resCfg.get("attributes") or {}
		code = core.readText(os.path.join(dirpath, "onToolCalled.py")) or ""

		markers = [m for m in WRITE_MARKERS if m in code]
		byName = any([name.startswith(p) for p in WRITE_NAME_PREFIXES])
		out.append({
			"name": name,
			"permissionLevels": _permLevels(attrs.get("permissions")),
			"writes": bool(markers) or byName,
			"writeMarkers": markers,
			"writeByName": byName,
			"file": core.rel(os.path.join(dirpath, "resource.json")),
		})
	return sorted(out, key=lambda t: t["name"])


# --------------------------------------------------------- WebDev endpoints

def webdevEndpoints(project=None):
	"""Every WebDev endpoint with its per-verb auth requirements."""
	project = project or core.PROJECT
	root = os.path.join(core.projectRoot(project),
	                    "com.inductiveautomation.webdev", "resources")
	out = []
	for dirpath in core.findResourceDirs(root):
		cfgPath = os.path.join(dirpath, "config.json")
		cfg = core.readJson(cfgPath)
		if cfg is None:
			continue
		name = core.rel(dirpath).split("resources/")[-1]
		verbs = []
		for verb in ("doGet", "doPost", "doPut", "doDelete", "doPatch",
		             "doHead", "doOptions", "doTrace"):
			vc = cfg.get(verb) or {}
			if not vc.get("enabled"):
				continue
			verbs.append({
				"verb": verb,
				"requireAuth": bool(vc.get("require-auth")),
				"requireHttps": bool(vc.get("require-https")),
				"requiredRoles": unicode(vc.get("required-roles") or ""),
			})
		out.append({
			"name": name,
			"type": unicode(cfg.get("resource-type") or ""),
			"verbs": verbs,
			"openVerbs": [v["verb"] for v in verbs if not v["requireAuth"]],
			"file": core.rel(cfgPath),
		})
	return sorted(out, key=lambda e: e["name"])


# ------------------------------------------------------------ named queries

def namedQueries(project=None):
	"""Every named query, flagged by whether it is an update query."""
	project = project or core.PROJECT
	root = os.path.join(core.projectRoot(project), "ignition", "named-query")
	out = []
	for dirpath in core.findResourceDirs(root):
		name = core.rel(dirpath).split("named-query/")[-1]
		cfg = core.readJson(os.path.join(dirpath, "config.json")) or {}
		sql = ""
		for fn in os.listdir(dirpath):
			if fn.endswith(".sql"):
				sql = core.readText(os.path.join(dirpath, fn)) or ""
				break
		if not sql:
			sql = unicode(cfg.get("query") or "")
		head = sql.strip().lstrip("-").strip().upper()
		isUpdate = head.startswith("INSERT") or head.startswith("UPDATE") \
			or head.startswith("DELETE") or head.startswith("CREATE") \
			or head.startswith("DROP") or head.startswith("ALTER")
		out.append({
			"name": name,
			"isUpdate": isUpdate,
			"database": unicode(cfg.get("database") or ""),
			"file": core.rel(dirpath),
		})
	return sorted(out, key=lambda q: q["name"])


# ------------------------------------------------------------------ summary

def inventory(project=None):
	project = project or core.PROJECT
	return {
		"project": project,
		"aiAgents": aiAgents(),
		"mcpServers": mcpServers(),
		"toolBundles": toolBundles(project),
		"webdevEndpoints": webdevEndpoints(project),
		"namedQueries": namedQueries(project),
	}


def audit(inv=None, knownProjects=None):
	"""Findings for the resources domain."""
	inv = inv or inventory()
	out = []

	toolsByName = {}
	for t in inv["toolBundles"]:
		toolsByName[t["name"]] = t

	# --- AI agents --------------------------------------------------------
	openAgents = []
	for agent in inv["aiAgents"]:
		if agent["permissionLevels"]:
			continue
		openAgents.append(agent["name"])

		# Does this agent hold any tool that can act?
		writeTools = []
		for entry in agent["tools"]:
			toolName = entry.split(":")[-1]
			t = toolsByName.get(toolName)
			if t and t["writes"]:
				writeTools.append(toolName)

		sev = "CRITICAL" if writeTools else "HIGH"
		detail = ("Agent %s has an empty permissions block, so any session that "
		          "can reach a chat component bound to it can invoke it."
		          % agent["name"])
		if writeTools:
			detail += (" It holds %d tool(s) that change gateway state: %s. "
			           "Invoking this agent is therefore a write path into the "
			           "system that authenticates nobody."
			           % (len(writeTools), ", ".join(sorted(writeTools))))
		else:
			detail += (" Its tools are read-only, so the exposure is disclosure "
			           "rather than control -- but the model can still be asked "
			           "to summarise anything those tools can see.")

		out.append(core.finding(
			"R001", sev, "resources",
			"AI agent %s requires no security level" % agent["name"],
			detail,
			agent["file"],
			"Populate the agent's permissions block with the security level "
			"that should be required to invoke it.",
			{"agent": agent["name"], "model": agent["model"],
			 "writeTools": sorted(writeTools), "toolCount": len(agent["tools"])}))

	if len(openAgents) > 2:
		out.append(core.finding(
			"R007", "HIGH", "resources",
			"All %d AI agents on this gateway are unrestricted" % len(openAgents),
			"Not one agent config carries a security level: %s. Whatever the "
			"individual exposures, the pattern is the finding -- AI agents were "
			"added to this gateway without access control being part of the "
			"process." % ", ".join(openAgents),
			core.rel(_moduleDir(core.configRoot(), "agent")) + "/",
			"Define a security level for AI agent use and apply it to every "
			"agent, then make it part of the checklist for adding a new one.",
			{"agents": openAgents}))

	# --- MCP servers ------------------------------------------------------
	for srv in inv["mcpServers"]:
		if srv["wildcards"]:
			out.append(core.finding(
				"R002", "HIGH", "resources",
				"MCP server %s exposes every tool in %s" % (srv["name"], ", ".join(srv["wildcards"])),
				"The tools map uses a wildcard, so every tool the named "
				"project defines is exposed to any MCP client that "
				"authenticates -- including tools added later, which are "
				"published the moment they are scanned in and never appear in "
				"any review of this file.",
				srv["file"],
				"Replace the wildcard with an explicit list of the tools the "
				"MCP server should publish.",
				{"server": srv["name"], "wildcards": srv["wildcards"]}))

		if not srv["permissionLevels"]:
			out.append(core.finding(
				"R008", "HIGH", "resources",
				"MCP server %s requires no security level" % srv["name"],
				"The server's permissions block is empty, so access is gated "
				"only by possession of an API token. There is no second check "
				"tying the caller to a role.",
				srv["file"],
				"Add the security level an MCP caller must hold.",
				{"server": srv["name"]}))

		if knownProjects is not None:
			for key in (srv["tools"] or {}).keys():
				if not key.startswith("project/"):
					continue
				proj = key.split("/", 1)[1]
				if proj not in knownProjects:
					out.append(core.finding(
						"R005", "MEDIUM", "resources",
						"MCP server %s references project %s, which does not exist"
						% (srv["name"], proj),
						"The tools map points at project %s, but the only "
						"project(s) on this gateway are %s. The mapping is "
						"stale. It is harmless while the project is missing and "
						"becomes an unreviewed wildcard grant the moment a "
						"project of that name is deployed."
						% (proj, ", ".join(sorted(knownProjects))),
						srv["file"],
						"Remove the stale mapping, or point it at the project "
						"that actually exists.",
						{"server": srv["name"], "missingProject": proj}))

	# --- tool bundles -----------------------------------------------------
	openWriters = [t for t in inv["toolBundles"]
	               if t["writes"] and not t["permissionLevels"]]
	for t in openWriters:
		why = ", ".join(t["writeMarkers"]) if t["writeMarkers"] \
			else "its name follows the project's mutation-tool convention"
		out.append(core.finding(
			"R003", "HIGH", "resources",
			"Tool %s can change gateway state and requires no security level" % t["name"],
			"This tool bundle carries an empty permissions block but is a "
			"mutation path (%s). Any agent it is bound to can call it, and no "
			"agent on this gateway restricts who can invoke it." % why,
			t["file"],
			"Add a security level to the tool's resource attributes, so the "
			"check holds even if an agent is later misconfigured.",
			{"tool": t["name"], "markers": t["writeMarkers"]}))

	# --- WebDev endpoints -------------------------------------------------
	for ep in inv["webdevEndpoints"]:
		if not ep["openVerbs"]:
			continue
		out.append(core.finding(
			"R004", "HIGH", "resources",
			"WebDev endpoint %s serves %s without authentication"
			% (ep["name"], ", ".join(ep["openVerbs"])),
			"require-auth is false for %s. The endpoint answers any caller that "
			"can reach the gateway over HTTP, with no session and no role "
			"check. Unlike a Perspective screen there is no login redirect in "
			"front of it -- the URL is the whole access control."
			% ", ".join(ep["openVerbs"]),
			ep["file"],
			"Set require-auth true, or document why this endpoint is "
			"deliberately public and confirm it exposes nothing sensitive.",
			{"endpoint": ep["name"], "openVerbs": ep["openVerbs"]}))

	return core.sortFindings(out)
