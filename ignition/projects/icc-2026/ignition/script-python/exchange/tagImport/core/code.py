"""exchange.tagImport.core — the logic behind the Tag Import Agent.

Every tag-creation path in the demo funnels through this module. The AI agent's
tool bundles, the Perspective Accept button, and any script-console testing all
call the same functions, so the containment rule is enforced in exactly one place.

CONTAINMENT RULE
----------------
Nothing this module creates may land outside the ``Exchange/Tag Import Agent`` folder.
Two trees are involved, because a UDT *definition* physically cannot live in the
normal tag tree:

	[default]Exchange/Tag Import Agent/...            UDT instances and standalone tags
	[default]_types_/Exchange/Tag Import Agent/...    UDT definitions

Both are namespaced by the same folder path. ``scopedFolder()`` rewrites every
agent-supplied path into one of those two subtrees; there is no argument that
reaches ``system.tag.configure`` with a base path outside them. Deletion is not
exposed to the agent at all -- ``resetRoot()`` exists for demo resets and must be
called deliberately from a script console or a Perspective button.

Jython 2.7. No f-strings, no type hints.
"""

import os
import sys

ROOT_SEGMENTS = ["Exchange", "Tag Import Agent"]
"""The root folder, one entry per level. Both trees end in these segments."""

ROOT_FOLDER = "/".join(ROOT_SEGMENTS)
PROVIDER = "default"
ROOT_PATH = "[%s]%s" % (PROVIDER, ROOT_FOLDER)
TYPES_ROOT_PATH = "[%s]_types_/%s" % (PROVIDER, ROOT_FOLDER)

PROJECT = "icc-2026"
DB = "postgres"

# Reference documents. The host folder ./reference/line1 is bind-mounted here and
# published by the 'reference' WebDev mounted-folder resource, so the same files
# are version-controlled in the repo and downloadable from the Tag Import page.
REFERENCE_DIR = "/reference/line1"
REFERENCE_URL_BASE = "/system/webdev/%s/exchange/tag-import/reference" % PROJECT

# The tag export the demo actually imports. The other reference documents are
# context the agent may read, not the thing it turns into tags.
PRIMARY_REFERENCE_FILE = "Line1_ControllerTags_Export.CSV"

# A proposal older than this is not shown on the page. The page binds to "the
# most recent row in ex_icc_tag_import_proposal", which without a window means it opens
# showing whatever the last demo produced -- days ago -- as if the agent had just
# written it. See latestProposalSummary().
PROPOSAL_TTL_MINUTES = 45

# Guard on anything read off the reference folder and handed to a model.
MAX_REFERENCE_CHARS = 200000

# Bound on anything an LLM can ask for in one call.
MAX_BROWSE_CHILDREN = 500
MAX_UDT_MEMBERS = 200

logger = system.util.getLogger("exchange.tagImport.Core")


# ---------------------------------------------------------------------------
# Datatype mapping
# ---------------------------------------------------------------------------

# IEC 61131 / TwinCAT types (what the PLC export carries) -> Ignition tag types.
# Also accepts Ignition names directly so the agent can pass either.
_DATATYPE_MAP = {
	# IEC / Beckhoff
	"BOOL": "Boolean",
	"BYTE": "Int2",
	"SINT": "Int1",
	"USINT": "Int2",
	"INT": "Int2",
	"UINT": "Int4",
	"WORD": "Int4",
	"DINT": "Int4",
	"UDINT": "Int8",
	"DWORD": "Int8",
	"LINT": "Int8",
	"ULINT": "Int8",
	"REAL": "Float4",
	"LREAL": "Float8",
	"STRING": "String",
	"WSTRING": "String",
	"TIME": "Int8",
	"DATE": "DateTime",
	"DT": "DateTime",
	"DATE_AND_TIME": "DateTime",
	# Ignition native names, passed through
	"BOOLEAN": "Boolean",
	"INT1": "Int1",
	"INT2": "Int2",
	"INT4": "Int4",
	"INT8": "Int8",
	"FLOAT4": "Float4",
	"FLOAT8": "Float8",
	"DATETIME": "DateTime",
	"DOCUMENT": "Document",
	# Loose aliases an LLM is likely to reach for
	"FLOAT": "Float4",
	"DOUBLE": "Float8",
	"INTEGER": "Int4",
	"LONG": "Int8",
	"SHORT": "Int2",
	"TEXT": "String",
	"STR": "String",
}


def mapDataType(datatype):
	"""Map a Logix/IEC or Ignition datatype name to an Ignition tag dataType.

	Raises ValueError on anything unrecognized rather than silently guessing --
	a wrong datatype is worse than a failed create the agent can report.
	"""
	if datatype is None:
		raise ValueError("datatype is required")
	key = unicode(datatype).strip().upper()
	if key in _DATATYPE_MAP:
		return _DATATYPE_MAP[key]
	raise ValueError(
		"Unrecognized datatype '%s'. Supported: %s"
		% (datatype, ", ".join(sorted(set(_DATATYPE_MAP.keys()))))
	)


def _defaultValue(ignitionType):
	"""A sane initial value for a memory tag of the given Ignition type."""
	if ignitionType == "Boolean":
		return False
	if ignitionType == "String":
		return ""
	if ignitionType in ("Float4", "Float8"):
		return 0.0
	if ignitionType in ("Int1", "Int2", "Int4", "Int8"):
		return 0
	return None


# ---------------------------------------------------------------------------
# Containment
# ---------------------------------------------------------------------------

class ScopeError(Exception):
	"""Raised when a caller tries to reach outside the Tag Import Agent folder."""
	pass


def _cleanSegments(raw):
	"""Split a folder string into validated path segments."""
	text = unicode(raw or "").strip().replace("\\", "/")

	# Strip a leading [provider] prefix, rejecting a foreign provider outright.
	if text.startswith("["):
		close = text.find("]")
		if close == -1:
			raise ScopeError("Malformed provider prefix in path: %s" % raw)
		provider = text[1:close].strip()
		if provider and provider.lower() != PROVIDER:
			raise ScopeError(
				"Provider '%s' is out of scope. This agent may only touch [%s]%s."
				% (provider, PROVIDER, ROOT_FOLDER)
			)
		text = text[close + 1:]

	segments = []
	for part in text.split("/"):
		part = part.strip()
		if part == "" or part == ".":
			continue
		if part == "..":
			raise ScopeError("Path traversal ('..') is not allowed: %s" % raw)
		if part == "_types_":
			raise ScopeError(
				"Do not name _types_ explicitly -- UDT definitions are placed there "
				"automatically, inside the %s folder." % ROOT_FOLDER
			)
		segments.append(part)
	return segments


def scopedFolder(folder):
	"""Normalize an agent-supplied folder to a path inside the root folder.

	Returns a provider-less relative path always beginning with ROOT_FOLDER.
	A folder that already names the root is used as-is; anything else is placed
	*underneath* the root rather than rejected, so a confused agent produces a
	contained result instead of an error loop. The rewritten path is always
	reported back so the caller can see what happened.
	"""
	segments = _cleanSegments(folder)
	depth = len(ROOT_SEGMENTS)
	if segments[:depth] == ROOT_SEGMENTS:
		segments = segments[depth:]
	elif segments[:1] == ROOT_SEGMENTS[-1:]:
		# The pre-Exchange root ('Tag Import Agent/Line1'): same folder, one level short
		segments = segments[1:]
	return "/".join(ROOT_SEGMENTS + segments)


def scopedPath(folder):
	"""Full provider-qualified path for a folder inside the root folder."""
	return "[%s]%s" % (PROVIDER, scopedFolder(folder))


def scopedTypesFolder(folder):
	"""Same, but in the _types_ tree where UDT definitions must live."""
	return "_types_/%s" % scopedFolder(folder)


def scopedTypesPath(folder):
	return "[%s]%s" % (PROVIDER, scopedTypesFolder(folder))


def validateName(name, what):
	"""Validate a single tag/UDT/folder name. Returns the cleaned name."""
	if name is None:
		raise ValueError("%s name is required" % what)
	clean = unicode(name).strip()
	if clean == "":
		raise ValueError("%s name is required" % what)
	for bad in ("/", "\\", "[", "]", ".."):
		if bad in clean:
			raise ValueError(
				"%s name '%s' may not contain '%s'" % (what, name, bad)
			)
	return clean


# ---------------------------------------------------------------------------
# Folder management
# ---------------------------------------------------------------------------

def udtInstanceAncestor(relFolder):
	"""The UDT instance a folder path runs through, or None.

	A UDT instance is a leaf: Ignition will not accept child tags under one, and
	the error it raises for the attempt talks about overrides rather than saying
	so ("does not have item 'BeanTemp' for overrides, and cannot accept children
	tags"). Checking first lets the tools say what actually went wrong.
	"""
	segments = [seg for seg in unicode(relFolder or "").split("/") if seg]
	built = ""
	for seg in segments:
		built = (built + "/" + seg) if built else seg
		path = "[%s]%s" % (PROVIDER, built)
		if not system.tag.exists(path):
			return None
		try:
			configs = system.tag.getConfiguration(path, False)
		except:
			return None
		if configs and unicode(configs[0].get("tagType") or "") == "UdtInstance":
			return path
	return None


def _ensureFolderPath(relFolder):
	"""Create every missing folder along a relative path, one level at a time.

	Uses collision policy 'a' (abort) on each individual create, so an existing
	folder is never overwritten and its children are never disturbed.
	"""
	segments = [s for s in relFolder.split("/") if s]
	built = ""
	for seg in segments:
		parentPath = "[%s]%s" % (PROVIDER, built) if built else "[%s]" % PROVIDER
		fullPath = "[%s]%s" % (PROVIDER, (built + "/" + seg) if built else seg)
		if not system.tag.exists(fullPath):
			system.tag.configure(
				parentPath,
				[{"name": seg, "tagType": "Folder"}],
				"a",
			)
			logger.info("Created folder %s" % fullPath)
		built = (built + "/" + seg) if built else seg
	return "[%s]%s" % (PROVIDER, built)


def ensureRoot():
	"""Make sure both root folders exist. Idempotent."""
	_ensureFolderPath(ROOT_FOLDER)
	_ensureFolderPath("_types_/" + ROOT_FOLDER)
	return {"tagRoot": ROOT_PATH, "typeRoot": TYPES_ROOT_PATH}


def _checkQuality(results, target):
	"""Raise on any bad quality returned by system.tag.configure."""
	problems = []
	for q in results or []:
		if not q.good:
			problems.append(unicode(q))
	if problems:
		raise Exception(
			"Failed to configure %s: %s" % (target, "; ".join(problems))
		)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def browse(path):
	"""Browse one folder level. Read-only, any path, no provider restriction.

	This is reconnaissance for naming and reuse decisions. It deliberately does
	not enforce the containment rule -- reading is safe, and the agent needs to
	see the wider tree to avoid duplicating an existing UDT. Nothing here can
	mutate anything: system.tag.browse is a read.
	"""
	target = unicode(path or "").strip()
	if target == "":
		target = "[%s]" % PROVIDER
	if not target.startswith("["):
		target = "[%s]%s" % (PROVIDER, target)

	results = system.tag.browse(target)
	children = []
	truncated = False
	for r in results.getResults():
		if len(children) >= MAX_BROWSE_CHILDREN:
			truncated = True
			break
		children.append({
			"name": unicode(r.get("name")),
			"fullPath": unicode(r.get("fullPath")),
			"hasChildren": bool(r.get("hasChildren")),
			"tagType": unicode(r.get("tagType")) if r.get("tagType") is not None else None,
			"dataType": unicode(r.get("dataType")) if r.get("dataType") is not None else None,
		})

	return {
		"path": target,
		"count": len(children),
		"truncated": truncated,
		"children": children,
		"readOnly": True,
	}


def existsInScope(relPath):
	"""True if a path inside the root folder already exists."""
	return bool(system.tag.exists("[%s]%s" % (PROVIDER, relPath)))


def listCreated():
	"""Every path that currently exists under the two root folders."""
	tags = _walk(ROOT_PATH)
	types = _walk(TYPES_ROOT_PATH)
	return {"tagRoot": ROOT_PATH, "tags": tags, "typeRoot": TYPES_ROOT_PATH, "types": types}


def verifyContainment():
	"""Audit the two root folders. Counts only, so it survives a size-capped caller.

	``outsideRoots`` must always be empty -- it is the assertion that the
	containment rule actually held, rather than merely being intended.
	"""
	tags = _walk(ROOT_PATH)
	types = _walk(TYPES_ROOT_PATH)
	allowed = ("[%s]%s/" % (PROVIDER, ROOT_FOLDER),
			   "[%s]_types_/%s/" % (PROVIDER, ROOT_FOLDER))
	outside = [e["path"] for e in tags + types if not e["path"].startswith(allowed)]
	return {
		"atomicTags": len([e for e in tags if e["tagType"] == "AtomicTag"]),
		"udtInstances": len([e for e in tags if e["tagType"] == "UdtInstance"]),
		"folders": len([e for e in tags if e["tagType"] == "Folder"]),
		"udtTypes": len([e for e in types if e["tagType"] == "UdtType"]),
		"outsideRootsCount": len(outside),
		"outsideRoots": outside[:20],
	}


def _walk(path, depth=0):
	"""Recursive browse, depth-capped. Used only inside the root folders."""
	out = []
	if depth > 8 or not system.tag.exists(path):
		return out
	for r in system.tag.browse(path).getResults():
		full = unicode(r.get("fullPath"))
		entry = {
			"path": full,
			"name": unicode(r.get("name")),
			"tagType": unicode(r.get("tagType")) if r.get("tagType") is not None else None,
			"dataType": unicode(r.get("dataType")) if r.get("dataType") is not None else None,
		}
		out.append(entry)
		if r.get("hasChildren"):
			out.extend(_walk(full, depth + 1))
	return out


# ---------------------------------------------------------------------------
# Writes -- all three funnel through scopedFolder()
# ---------------------------------------------------------------------------

def _memberConfigs(typeName, members):
	"""Validated member configs for a UDT definition.

	Shared by createUdtDefinition() and the batch path in createFromProposal(),
	so a member is built exactly one way whichever door it comes in through.
	"""
	if members is None or len(members) == 0:
		raise ValueError("A UDT definition needs at least one member")
	if len(members) > MAX_UDT_MEMBERS:
		raise ValueError(
			"UDT '%s' has %d members, over the %d limit"
			% (typeName, len(members), MAX_UDT_MEMBERS)
		)

	configs = []
	seen = set()
	for m in members:
		mName = validateName(m.get("name"), "UDT member")
		if mName.lower() in seen:
			raise ValueError("Duplicate member '%s' in UDT '%s'" % (mName, typeName))
		seen.add(mName.lower())
		mType = mapDataType(m.get("datatype") or m.get("dataType"))
		cfg = {
			"name": mName,
			"tagType": "AtomicTag",
			"dataType": mType,
			"valueSource": "memory",
			"value": _defaultValue(mType),
		}
		if m.get("description"):
			cfg["documentation"] = unicode(m.get("description"))
		configs.append(cfg)
	return configs


def _overrideTags(overrides):
	"""Member-override configs for a UDT instance."""
	out = []
	for memberName, override in (overrides or {}).items():
		mName = validateName(memberName, "override member")
		if isinstance(override, dict):
			entry = {"name": mName}
			for key, val in override.items():
				entry[unicode(key)] = val
			# An opcItemPath with no explicit source is meant to be an OPC tag.
			if "opcItemPath" in entry and "valueSource" not in entry:
				entry["valueSource"] = "opc"
		else:
			entry = {"name": mName, "value": override}
		out.append(entry)
	return out


def _atomicConfig(name, datatype, valueSource):
	"""One standalone tag's config. Returns (tagName, config)."""
	tagName = validateName(name, "Tag")
	ignitionType = mapDataType(datatype)
	config = {"name": tagName, "tagType": "AtomicTag", "dataType": ignitionType}
	source = unicode(valueSource or "memory").strip()

	if source == "" or source.lower() == "memory":
		config["valueSource"] = "memory"
		config["value"] = _defaultValue(ignitionType)
	elif source.lower().startswith("opc:"):
		rest = source[4:]
		if ":" not in rest:
			raise ValueError(
				"OPC value_source must be 'opc:<serverName>:<itemPath>', got '%s'" % valueSource
			)
		serverName, itemPath = rest.split(":", 1)
		config["valueSource"] = "opc"
		config["opcServer"] = serverName.strip()
		config["opcItemPath"] = itemPath.strip()
	elif source.lower().startswith("expression:"):
		config["valueSource"] = "expr"
		config["expression"] = source[len("expression:"):].strip()
	else:
		# Treat as a literal seed value for a memory tag.
		config["valueSource"] = "memory"
		config["value"] = source
	return tagName, config


def createUdtDefinition(name, members, folder):
	"""Create a UDT type definition under _types_/Exchange/Tag Import Agent.

	members: list of dicts with keys name, datatype, and optionally description
	         and value_source ('memory' by default).
	"""
	typeName = validateName(name, "UDT")
	relFolder = scopedFolder(folder)
	typesRel = "_types_/" + relFolder
	basePath = "[%s]%s" % (PROVIDER, typesRel)

	if members is None or len(members) == 0:
		raise ValueError("A UDT definition needs at least one member")
	if len(members) > MAX_UDT_MEMBERS:
		raise ValueError(
			"UDT '%s' has %d members, over the %d limit"
			% (typeName, len(members), MAX_UDT_MEMBERS)
		)

	memberConfigs = _memberConfigs(typeName, members)

	_ensureFolderPath(typesRel)

	fullTypePath = "%s/%s" % (basePath, typeName)
	if system.tag.exists(fullTypePath):
		raise Exception(
			"UDT definition '%s' already exists at %s. Reuse it instead of "
			"recreating it, or pick a different name." % (typeName, fullTypePath)
		)

	quality = system.tag.configure(
		basePath,
		[{"name": typeName, "tagType": "UdtType", "tags": memberConfigs}],
		"a",
	)
	_checkQuality(quality, fullTypePath)

	# typeId is the path under _types_, without the _types_ prefix.
	typeId = "%s/%s" % (relFolder, typeName)
	logger.info("Created UDT definition %s (typeId %s)" % (fullTypePath, typeId))
	return {
		"status": "created",
		"objectType": "udt_definition",
		"name": typeName,
		"typeId": typeId,
		"path": fullTypePath,
		"memberCount": len(memberConfigs),
		"members": [{"name": c["name"], "dataType": c["dataType"]} for c in memberConfigs],
	}


def resolveTypeId(udtName):
	"""Resolve a UDT name to a typeId, wherever inside the root folder it lives.

	The agent naturally passes a bare name ('Machine') while the definition may
	have been created in a subfolder ('Exchange/Tag Import Agent/Line1/Machine'), so a
	literal path join is not enough. Order: exact scoped path, then a search of
	the _types_ subtree by leaf name. An ambiguous name is an error listing the
	candidates rather than a coin flip.
	"""
	raw = unicode(udtName or "").strip().strip("/")
	if raw == "":
		raise ValueError("udt_name is required")

	candidate = scopedFolder(raw)
	if system.tag.exists("[%s]_types_/%s" % (PROVIDER, candidate)):
		return candidate

	leaf = candidate.split("/")[-1].lower()
	prefix = "[%s]_types_/" % PROVIDER
	matches = []
	for entry in _walk(TYPES_ROOT_PATH):
		if entry["name"].lower() != leaf:
			continue
		# Only type definitions -- a UDT member could share the name.
		if entry["tagType"] not in ("UdtType", "UdtInstance"):
			continue
		path = entry["path"]
		if path.startswith(prefix):
			matches.append(path[len(prefix):])

	if len(matches) == 1:
		return matches[0]
	if len(matches) > 1:
		raise Exception(
			"'%s' is ambiguous -- %d definitions match: %s. Pass the full type path."
			% (udtName, len(matches), ", ".join(matches))
		)
	raise Exception(
		"No UDT definition named '%s' under %s. Create the definition first with "
		"create_udt_definition, or check the name." % (udtName, TYPES_ROOT_PATH)
	)


def createUdtInstance(udtName, instanceName, folder, overrides):
	"""Instantiate an existing UDT definition inside the root folder.

	udtName may be a bare name ('Machine') or a typeId path
	('Exchange/Tag Import Agent/Machine'). overrides is an optional dict keyed by member
	name; each value may be a scalar (initial value) or a dict of tag properties
	such as {"opcItemPath": "...", "opcServer": "...", "valueSource": "opc"}.
	"""
	instance = validateName(instanceName, "UDT instance")
	relFolder = scopedFolder(folder)
	basePath = "[%s]%s" % (PROVIDER, relFolder)

	typeId = resolveTypeId(udtName)
	typePath = "[%s]_types_/%s" % (PROVIDER, typeId)

	_ensureFolderPath(relFolder)

	fullPath = "%s/%s" % (basePath, instance)
	if system.tag.exists(fullPath):
		raise Exception(
			"'%s' already exists at %s. Pick a different instance name." % (instance, fullPath)
		)

	config = {"name": instance, "tagType": "UdtInstance", "typeId": typeId}

	overrideTags = _overrideTags(overrides)
	if overrideTags:
		config["tags"] = overrideTags

	quality = system.tag.configure(basePath, [config], "a")
	_checkQuality(quality, fullPath)

	logger.info("Created UDT instance %s of %s" % (fullPath, typeId))
	return {
		"status": "created",
		"objectType": "udt_instance",
		"name": instance,
		"typeId": typeId,
		"path": fullPath,
		"overrideCount": len(overrideTags),
	}


def createTag(name, datatype, folder, valueSource):
	"""Create one standalone tag inside the root folder.

	valueSource accepts:
		"memory" (default)          -- memory tag with a type-appropriate default
		"opc:<server>:<itemPath>"   -- OPC tag against a configured server
		"expression:<expr>"         -- expression tag
		"<literal>"                 -- anything else is treated as an initial
		                               memory value, which is what an LLM tends
		                               to pass when it means "seed it with this"
	"""
	tagName = validateName(name, "Tag")
	relFolder = scopedFolder(folder)
	basePath = "[%s]%s" % (PROVIDER, relFolder)

	instance = udtInstanceAncestor(relFolder)
	if instance is not None:
		raise Exception(
			"%s is a UDT instance, not a folder, so '%s' cannot be created inside it. "
			"A machine-specific tag that is not part of the type belongs beside the "
			"instance in its parent folder -- name it after the machine, e.g. "
			"'%s_%s' -- or add it to the UDT definition as a member."
			% (instance, tagName, instance.split("/")[-1], tagName)
		)

	_ensureFolderPath(relFolder)

	fullPath = "%s/%s" % (basePath, tagName)
	if system.tag.exists(fullPath):
		raise Exception(
			"'%s' already exists at %s. Pick a different name." % (tagName, fullPath)
		)

	_unusedName, config = _atomicConfig(name, datatype, valueSource)

	quality = system.tag.configure(basePath, [config], "a")
	_checkQuality(quality, fullPath)

	logger.info("Created tag %s (%s, %s)" % (fullPath, config["dataType"], config["valueSource"]))
	return {
		"status": "created",
		"objectType": "tag",
		"name": tagName,
		"path": fullPath,
		"dataType": config["dataType"],
		"valueSource": config["valueSource"],
	}


# ---------------------------------------------------------------------------
# Batch create -- the whole accepted proposal in one call
#
# system.tag.configure takes a LIST of tag configs against one base path, so a
# folder's worth of tags is one gateway call, not one per tag. Building the
# structure tag by tag was 38 round trips through the model for this demo's
# proposal, every one of them a turn the model had to spend re-emitting data it
# had already written into the proposal.
#
# The proposal is read back out of Postgres rather than re-sent by the agent, so
# what gets built is exactly what the user reviewed on the page -- there is no
# second copy of the structure to drift.
# ---------------------------------------------------------------------------

def _quality_message(q):
	"""Readable text for one system.tag.configure quality result."""
	try:
		if q.good:
			return None
	except:
		return None
	return unicode(q)


def _configureBatch(basePath, configs):
	"""One system.tag.configure call. Returns a per-config list of (ok, message).

	Collision policy is 'a' (abort), which applies per tag rather than per call:
	an existing tag fails on its own row and its neighbours still get created.
	"""
	if not configs:
		return []
	qualities = list(system.tag.configure(basePath, configs, "a") or [])
	out = []
	for i in range(len(configs)):
		if i < len(qualities):
			msg = _quality_message(qualities[i])
			out.append((msg is None, msg or "created"))
		else:
			# Fewer qualities than configs should not happen; treat as unknown
			# rather than silently reporting success.
			out.append((False, "no quality returned for this tag"))
	return out


def createFromProposal(proposalId=None):
	"""Create the whole accepted proposal: definitions, instances, standalone tags.

	Order is forced -- definitions, then instances (which need their type to
	exist), then standalone tags. Within each stage the configs are grouped by
	target folder and written one folder per call.

	Returns a summary, never raises for a single bad item: one unmappable
	datatype or one name collision is reported in ``failures`` and everything
	else is still created, which is what you want halfway through a demo.
	"""
	pid, refusal = resolveAcceptedProposal(proposalId)
	if refusal is not None:
		return refusal

	p = getProposal(pid)
	proposal = p["proposal"] or {}
	created = {"udt_definitions": 0, "udt_instances": 0, "standalone_tags": 0}
	failures = []
	paths = {"udt_definitions": [], "udt_instances": [], "standalone_tags": []}

	def record(kind, name, path, ok, message):
		recordResult(pid, kind, name, path, ok, message)
		if ok:
			created[_RESULT_KEY[kind]] += 1
			paths[_RESULT_KEY[kind]].append(path)
		else:
			failures.append({"objectType": kind, "name": name, "path": path,
			                 "message": message})

	# --- 1. UDT definitions, grouped by their _types_ folder ----------------
	byFolder = {}
	for d in proposal.get("udt_definitions") or []:
		try:
			typeName = validateName(d.get("name"), "UDT")
			relFolder = scopedFolder(d.get("folder"))
			cfg = {"name": typeName, "tagType": "UdtType",
			       "tags": _memberConfigs(typeName, d.get("members"))}
		except:
			e = sys.exc_info()[1]
			record("udt_definition", unicode(d.get("name")), "", False, str(e))
			continue
		byFolder.setdefault(relFolder, []).append(cfg)

	for relFolder, configs in byFolder.items():
		typesRel = "_types_/" + relFolder
		basePath = "[%s]%s" % (PROVIDER, typesRel)
		_ensureFolderPath(typesRel)
		for cfg, (ok, message) in zip(configs, _configureBatch(basePath, configs)):
			record("udt_definition", cfg["name"],
			       "%s/%s" % (basePath, cfg["name"]), ok, message)

	# --- 2. UDT instances ---------------------------------------------------
	# typeId resolution happens here, after the definitions exist.
	byFolder = {}
	for inst in proposal.get("udt_instances") or []:
		try:
			name = validateName(inst.get("instance_name"), "UDT instance")
			relFolder = scopedFolder(inst.get("folder"))
			cfg = {"name": name, "tagType": "UdtInstance",
			       "typeId": resolveTypeId(inst.get("udt_name"))}
			overrides = _overrideTags(inst.get("overrides"))
			if overrides:
				cfg["tags"] = overrides
		except:
			e = sys.exc_info()[1]
			record("udt_instance", unicode(inst.get("instance_name")), "", False, str(e))
			continue
		byFolder.setdefault(relFolder, []).append(cfg)

	for relFolder, configs in byFolder.items():
		basePath = "[%s]%s" % (PROVIDER, relFolder)
		_ensureFolderPath(relFolder)
		for cfg, (ok, message) in zip(configs, _configureBatch(basePath, configs)):
			record("udt_instance", cfg["name"],
			       "%s/%s" % (basePath, cfg["name"]), ok, message)

	# --- 3. Standalone tags -------------------------------------------------
	byFolder = {}
	for t in proposal.get("standalone_tags") or []:
		try:
			relFolder = scopedFolder(t.get("folder"))
			instance = udtInstanceAncestor(relFolder)
			if instance is not None:
				raise Exception(
					"%s is a UDT instance, not a folder, so this tag cannot be "
					"created inside it. Put it beside the instance in the parent "
					"folder, named after the machine." % instance
				)
			name, cfg = _atomicConfig(
				t.get("name"), t.get("datatype") or t.get("dataType"),
				t.get("value_source") or t.get("valueSource"))
			if t.get("description"):
				cfg["documentation"] = unicode(t.get("description"))
		except:
			e = sys.exc_info()[1]
			record("tag", unicode(t.get("name")), "", False, str(e))
			continue
		byFolder.setdefault(relFolder, []).append(cfg)

	for relFolder, configs in byFolder.items():
		basePath = "[%s]%s" % (PROVIDER, relFolder)
		_ensureFolderPath(relFolder)
		for cfg, (ok, message) in zip(configs, _configureBatch(basePath, configs)):
			record("tag", cfg["name"], "%s/%s" % (basePath, cfg["name"]), ok, message)

	if not failures:
		setProposalStatus(pid, "executed")

	logger.info(
		"Proposal %d created in batch: %d types, %d instances, %d tags, %d failures"
		% (pid, created["udt_definitions"], created["udt_instances"],
		   created["standalone_tags"], len(failures))
	)
	return {
		"status": "created" if not failures else "partial",
		"proposalId": pid,
		"created": created,
		"failures": failures,
		"folders": sorted(set(
			[path.rsplit("/", 1)[0] for group in paths.values() for path in group]
		)),
		"tagRoot": ROOT_PATH,
		"typeRoot": TYPES_ROOT_PATH,
	}


_RESULT_KEY = {
	"udt_definition": "udt_definitions",
	"udt_instance": "udt_instances",
	"tag": "standalone_tags",
}


# ---------------------------------------------------------------------------
# Demo reset
# ---------------------------------------------------------------------------

def resetRoot(confirm=False):
	"""Delete everything under both root folders. Nothing outside them is touched.

	Behind the reset_demo_folder agent tool, and callable from the script console.
	Needed when re-running the demo, since every create uses collision policy
	'abort'. The containment lives here rather than in the tool: it only ever
	browses and deletes the children of ROOT_PATH and TYPES_ROOT_PATH, so no tool
	argument can widen what it reaches.
	"""
	if not confirm:
		return {"status": "no_action", "message": "Call resetRoot(confirm=True) to actually delete."}

	removed = []
	for root in (ROOT_PATH, TYPES_ROOT_PATH):
		if not system.tag.exists(root):
			continue
		children = [unicode(r.get("fullPath")) for r in system.tag.browse(root).getResults()]
		if children:
			system.tag.deleteTags(children)
			removed.extend(children)
	logger.warn("resetRoot removed %d objects under %s" % (len(removed), ROOT_FOLDER))
	return {"status": "reset", "removedCount": len(removed), "removed": removed}


# How long the agent's tags live before the purge timer removes them.
PURGE_AFTER_SECS = 600


def _rootsHaveChildren():
	"""True when either Tag Import Agent root holds anything."""
	for root in (ROOT_PATH, TYPES_ROOT_PATH):
		if system.tag.exists(root) and len(system.tag.browse(root).getResults()) > 0:
			return True
	return False


def purgeDemoFolder(force=False, maxAgeSecs=PURGE_AFTER_SECS):
	"""Empty both Tag Import Agent roots 10 minutes after the agent created them.

	Driven by the ``TagImportFolderPurge`` timer every minute, so the demo
	folder is back to empty a few minutes after each run and the next audience
	sees "go ahead" create 117 tags from scratch. The clock is the newest
	successful row in ``ex_icc_tag_import_result``, which ``createFromProposal``
	writes for every object it builds; its age is computed in SQL so the
	gateway's and database's clocks cannot disagree. Anything in the roots with
	no creation record at all (made by hand) is treated as old and removed.
	Uses the same :func:`resetRoot` as the agent's ``reset_demo_folder`` tool.

	Args:
		force (bool): Purge now, whatever the age.
		maxAgeSecs (int): Age of the newest creation at which to purge.

	Gated by ``[default]Exchange/Demo/Control/Timers/TagImportFolderPurgeEnabled`` -- the
	environment guard. It applies to a forced run too, and fails closed: an
	unreadable switch means no purge (see :mod:`exchange.demo.control`).

	Returns:
		dict: ``action`` -- ``disabled``, ``empty``, ``waiting`` (with
		``ageSecs``), ``purged`` (plus whatever :func:`resetRoot` returned) or
		``error``.
	"""
	if not exchange.demo.control.timerEnabled("TagImportFolderPurge"):
		return {"action": "disabled", "removedCount": 0,
				"switch": exchange.demo.control.switchPath("TagImportFolderPurge")}
	try:
		if not _rootsHaveChildren():
			return {"action": "empty", "removedCount": 0}
		ageSecs = None
		if not force:
			ds = system.db.runNamedQuery(PROJECT, "Exchange/TagImport/SelectLastCreatedAge", {})
			if ds.getRowCount() > 0 and ds.getValueAt(0, 0) is not None:
				ageSecs = int(float(ds.getValueAt(0, 0)))
			if ageSecs is not None and ageSecs < maxAgeSecs:
				return {"action": "waiting", "removedCount": 0, "ageSecs": ageSecs,
						"remainingSecs": maxAgeSecs - ageSecs}
		result = resetRoot(confirm=True)
	except:
		# Bare except: a tag-layer NPE is a Java exception and would escape
		# "except Exception"; on a 1-minute timer it must not throw every tick.
		e = sys.exc_info()[1]
		logger.error("Tag Import folder purge failed: %s" % str(e))
		return {"action": "error", "removedCount": 0, "error": str(e)}
	result["action"] = "purged"
	result["ageSecs"] = ageSecs
	logger.info("Purged the Tag Import Agent folder (%s objects, newest created %s s ago)"
				% (result.get("removedCount"), ageSecs))
	return result


# ---------------------------------------------------------------------------
# Staging tables -- the seam between Perspective and the agent
# ---------------------------------------------------------------------------

def saveUpload(filename, csvText, uploadedBy):
	"""Persist an uploaded CSV. Called from the Perspective File Upload handler."""
	if csvText is None or unicode(csvText).strip() == "":
		raise ValueError("Uploaded file is empty")
	text = unicode(csvText)
	rowCount = len([ln for ln in text.splitlines() if ln.strip()]) - 1
	ds = system.db.runNamedQuery(PROJECT, "Exchange/TagImport/InsertUpload", {
		"filename": unicode(filename or "upload.csv"),
		"csvText": text,
		"rowCount": max(rowCount, 0),
		"uploadedBy": unicode(uploadedBy or "unknown"),
	})
	uploadId = int(ds.getValueAt(0, 0))
	logger.info("Stored upload %d (%s, %d rows)" % (uploadId, filename, rowCount))
	return uploadId


def loadSampleUpload(filename=None):
	"""Seed an upload from the bind-mounted reference CSV instead of a browser upload.

	For a demo that always uses the same file, this reuses the exact same
	staging table saveUpload() writes to -- the agent's read_uploaded_export
	tool cannot tell the difference. filename defaults to the tag export named
	in _REFERENCE_BLURBS; pass a different reference filename to load a
	different sample.
	"""
	name = filename or PRIMARY_REFERENCE_FILE
	path = os.path.join(REFERENCE_DIR, name)
	if not os.path.isfile(path):
		raise ValueError("No reference file named '%s' in %s" % (name, REFERENCE_DIR))
	with open(path, "r") as f:
		text = f.read()
	return saveUpload(name, text, "sample-preload")


def getUpload(uploadId):
	"""Fetch an upload by id, or the most recent one when uploadId is None."""
	if uploadId is None:
		ds = system.db.runNamedQuery(PROJECT, "Exchange/TagImport/SelectLatestUpload", {})
	else:
		ds = system.db.runNamedQuery(PROJECT, "Exchange/TagImport/SelectUpload", {"uploadId": int(uploadId)})
	if ds.getRowCount() == 0:
		return None
	return {
		"uploadId": int(ds.getValueAt(0, "id")),
		"filename": unicode(ds.getValueAt(0, "filename")),
		"csvText": unicode(ds.getValueAt(0, "csv_text")),
		"rowCount": int(ds.getValueAt(0, "row_count") or 0),
		"uploadedAt": unicode(ds.getValueAt(0, "uploaded_at")),
	}


def saveProposal(uploadId, proposal, rationale):
	"""Persist the agent's structured proposal. Returns the new proposal_id."""
	if isinstance(proposal, basestring):
		# Validate it round-trips before storing -- a malformed blob would break
		# the Tree binding with no useful error.
		parsed = system.util.jsonDecode(proposal)
		text = system.util.jsonEncode(parsed)
	else:
		text = system.util.jsonEncode(proposal)

	if uploadId is None:
		latest = getUpload(None)
		if latest is None:
			raise Exception("No upload on file. Upload a tag export before proposing a structure.")
		uploadId = latest["uploadId"]

	ds = system.db.runNamedQuery(PROJECT, "Exchange/TagImport/InsertProposal", {
		"uploadId": int(uploadId),
		"proposalJson": text,
		"rationale": unicode(rationale or ""),
	})
	proposalId = int(ds.getValueAt(0, 0))
	logger.info("Stored proposal %d for upload %d" % (proposalId, uploadId))
	return proposalId


def getProposal(proposalId):
	"""Fetch a proposal by id, or the most recent one when proposalId is None."""
	if proposalId is None:
		ds = system.db.runNamedQuery(PROJECT, "Exchange/TagImport/SelectLatestProposal", {})
	else:
		ds = system.db.runNamedQuery(PROJECT, "Exchange/TagImport/SelectProposal", {"proposalId": int(proposalId)})
	if ds.getRowCount() == 0:
		return None
	createdAt = ds.getValueAt(0, "created_at")
	ageMinutes = 0
	try:
		ageMinutes = int(system.date.minutesBetween(createdAt, system.date.now()))
	except:
		pass
	return {
		"proposalId": int(ds.getValueAt(0, "id")),
		"uploadId": int(ds.getValueAt(0, "tag_import_upload_id")),
		"proposal": system.util.jsonDecode(unicode(ds.getValueAt(0, "proposal_json"))),
		"rationale": unicode(ds.getValueAt(0, "rationale") or ""),
		"status": unicode(ds.getValueAt(0, "status")),
		"createdAt": unicode(createdAt),
		"createdDate": createdAt,
		"ageMinutes": ageMinutes,
	}


def setProposalStatus(proposalId, status):
	"""Move a proposal through proposed -> accepted -> executed (or rejected)."""
	if status not in ("proposed", "accepted", "executed", "rejected", "archived"):
		raise ValueError("Unknown proposal status '%s'" % status)
	system.db.runNamedQuery(PROJECT, "Exchange/TagImport/UpdateProposalStatus", {
		"proposalId": int(proposalId),
		"status": status,
	})
	return {"proposalId": int(proposalId), "status": status}


def recordResult(proposalId, objectType, objectName, tagPath, succeeded, message):
	"""Append one row to the creation audit trail."""
	system.db.runNamedQuery(PROJECT, "Exchange/TagImport/InsertResult", {
		"proposalId": int(proposalId) if proposalId is not None else None,
		"objectType": unicode(objectType),
		"objectName": unicode(objectName),
		"tagPath": unicode(tagPath),
		# Passed as an int and cast in SQL -- Ignition named-query parameters have
		# no boolean sqlType.
		"succeeded": 1 if succeeded else 0,
		"message": unicode(message or ""),
	})


def isAccepted(proposalId):
	"""True once the user has approved this proposal in the chat."""
	p = getProposal(proposalId)
	if p is None:
		return False
	return p["status"] in ("accepted", "executed")


def acceptProposal(proposalId):
	"""Called by the accept_proposal agent tool once the user says go ahead."""
	if proposalId is None:
		latest = getProposal(None)
		if latest is None:
			raise Exception("There is no proposal to accept.")
		proposalId = latest["proposalId"]
	setProposalStatus(proposalId, "accepted")
	logger.info("Proposal %d accepted by the user" % int(proposalId))
	return int(proposalId)


def rejectProposal(proposalId):
	"""Called by the reject_proposal agent tool."""
	if proposalId is None:
		latest = getProposal(None)
		if latest is None:
			raise Exception("There is no proposal to reject.")
		proposalId = latest["proposalId"]
	setProposalStatus(proposalId, "rejected")
	return int(proposalId)


def archiveLatestProposal():
	"""Clear the page: hide the current proposal without deleting the history.

	Called by the view's onStartup, so the demo always opens on a blank panel. Only the most recent row is ever shown, so
	archiving that one is enough. Nothing is deleted -- the audit trail in
	ex_icc_tag_import_result still points at a real proposal row.
	"""
	latest = getProposal(None)
	if latest is None:
		return 0
	setProposalStatus(latest["proposalId"], "archived")
	logger.info("Proposal %d archived from the page" % latest["proposalId"])
	return int(latest["proposalId"])


def resolveAcceptedProposal(proposalId):
	"""Gate for create_proposed_structure (and the legacy per-item create_*
	tools). Returns (proposalId, refusal).

	``refusal`` is None when creation is allowed, otherwise a dict the tool
	returns verbatim. Acceptance is recorded by the accept_proposal tool, which
	the agent may only call once the user has said go ahead in the chat -- there
	is no Accept button on the page any more. The gate is still a state machine
	rather than a prompt instruction: a proposal must exist, must not be
	rejected, and must have been accepted in its own turn before anything can be
	created.
	"""
	pid = int(proposalId) if proposalId is not None else None
	p = getProposal(pid)

	if p is None:
		return None, {
			"status": "no_proposal",
			"message": "There is no saved proposal. Call save_proposal first, then "
			           "summarize it and wait for the user to tell you to go ahead.",
		}
	if p["status"] == "rejected":
		return p["proposalId"], {
			"status": "rejected",
			"proposalId": p["proposalId"],
			"message": "The user rejected proposal %d. Revise it and call save_proposal "
			           "again -- do not create anything from a rejected proposal."
			           % p["proposalId"],
		}
	if p["status"] not in ("accepted", "executed"):
		return p["proposalId"], {
			"status": "not_accepted",
			"proposalId": p["proposalId"],
			"message": "Proposal %d has not been accepted yet. The user reviews the tree "
			           "on the Tag Import page and then tells you in the chat to go ahead; "
			           "call accept_proposal at that point, never on your own initiative. "
			           "Summarize the proposal and wait."
			           % p["proposalId"],
		}
	return p["proposalId"], None


# ---------------------------------------------------------------------------
# Perspective support
#
# The page binds ONE view custom property to latestProposalSummary() and reads
# everything else off it with simple property bindings. One poll, one query, no
# script transforms in the view.
# ---------------------------------------------------------------------------

_STATUS_LABELS = {
	"proposed": "Awaiting your review",
	"accepted": "Accepted -- agent is creating",
	"executed": "Created",
	"rejected": "Rejected",
	"archived": "Cleared",
}


def _folderTail(folder):
	"""The part of a folder path below the root, as a list of segments."""
	segments = [s for s in scopedFolder(folder).split("/") if s]
	return segments[len(ROOT_SEGMENTS):]


class _Node(object):
	"""Mutable folder node used while assembling the tree."""

	def __init__(self, label):
		self.label = label
		self.folders = {}
		self.leaves = []

	def child(self, name):
		if name not in self.folders:
			self.folders[name] = _Node(name)
		return self.folders[name]

	def render(self, expanded):
		items = []
		for name in sorted(self.folders.keys()):
			items.append(self.folders[name].render(expanded))
		items.extend(self.leaves)
		return {
			"label": "%s  (%d)" % (self.label, _countLeaves(self)),
			"expanded": expanded,
			"data": {"kind": "folder"},
			"items": items,
		}


def _countLeaves(node):
	total = len(node.leaves)
	for child in node.folders.values():
		total += _countLeaves(child)
	return total


def _placeLeaf(root, folder, leaf):
	node = root
	for segment in _folderTail(folder):
		node = node.child(segment)
	node.leaves.append(leaf)


def buildTreeItems(proposal):
	"""Turn a proposal dict into ia.display.tree items.

	Three top-level branches: the tag tree that will be created, the UDT
	definitions that back it, and anything the agent could not resolve.
	"""
	if not proposal:
		return []

	definitions = proposal.get("udt_definitions") or []
	instances = proposal.get("udt_instances") or []
	standalone = proposal.get("standalone_tags") or []
	unresolved = proposal.get("unresolved") or []

	# Member list per UDT name, so an instance can be expanded to member level.
	membersByUdt = {}
	for d in definitions:
		membersByUdt[unicode(d.get("name"))] = d.get("members") or []

	tagRoot = _Node(ROOT_FOLDER)

	for inst in instances:
		udtName = unicode(inst.get("udt_name") or "").split("/")[-1]
		memberItems = []
		for m in membersByUdt.get(udtName, []):
			memberItems.append({
				"label": "%s : %s" % (m.get("name"), m.get("datatype") or m.get("dataType")),
				"expanded": False,
				"data": {"kind": "member"},
				"items": [],
			})
		_placeLeaf(tagRoot, inst.get("folder"), {
			"label": "%s  [%s]" % (inst.get("instance_name"), udtName),
			"expanded": False,
			"data": {"kind": "udt_instance", "udt": udtName},
			"items": memberItems,
		})

	for tag in standalone:
		_placeLeaf(tagRoot, tag.get("folder"), {
			"label": "%s : %s" % (tag.get("name"), tag.get("datatype") or tag.get("dataType")),
			"expanded": False,
			"data": {"kind": "tag", "rationale": tag.get("rationale") or ""},
			"items": [],
		})

	items = [tagRoot.render(True)]

	if definitions:
		defItems = []
		for d in definitions:
			memberItems = []
			for m in d.get("members") or []:
				memberItems.append({
					"label": "%s : %s" % (m.get("name"), m.get("datatype") or m.get("dataType")),
					"expanded": False,
					"data": {"kind": "member"},
					"items": [],
				})
			defItems.append({
				"label": "%s  (%d members)" % (d.get("name"), len(memberItems)),
				"expanded": False,
				"data": {"kind": "udt_definition", "rationale": d.get("rationale") or ""},
				"items": memberItems,
			})
		items.append({
			"label": "UDT Definitions  (%d)" % len(defItems),
			"expanded": True,
			"data": {"kind": "types_root", "path": TYPES_ROOT_PATH},
			"items": defItems,
		})

	if unresolved:
		items.append({
			"label": "Unresolved  (%d)" % len(unresolved),
			"expanded": True,
			"data": {"kind": "unresolved"},
			"items": [{
				"label": "%s -- %s" % (u.get("tag"), u.get("reason")),
				"expanded": False,
				"data": {"kind": "unresolved_tag"},
				"items": [],
			} for u in unresolved],
		})

	return items


def latestProposalSummary():
	"""Everything the Tag Import page needs, in one call.

	Bound to a single view custom property with a slow poll. Returns a dict that
	is always well-formed, even when there is nothing to show, so the view's
	simple property bindings never see a null.

	The page opening blank is not this function's job -- the view's onStartup
	archives whatever was on file, which is what makes a proposal from an earlier
	run invisible. See archiveLatestProposal().
	"""
	empty = {
		"proposalId": 0,
		"status": "none",
		"statusLabel": "Nothing proposed yet",
		"rationale": "",
		"treeItems": [],
		"counts": {"udt_definitions": 0, "udt_instances": 0, "standalone_tags": 0, "unresolved": 0},
		"totalTags": 0,
		"canAccept": False,
		"hasProposal": False,
		"isExecuted": False,
		"uploadFilename": "",
	}

	try:
		p = getProposal(None)
	except:
		e = sys.exc_info()[1]
		logger.warn("latestProposalSummary failed: %s" % str(e))
		empty["statusLabel"] = "Staging tables unavailable -- see gateway logs"
		return empty

	# "The latest proposal" on its own means the page opens pre-filled with
	# whatever the last demo produced, looking as though the agent had just
	# written it. `archived` is set by the view's onStartup and by the Start over
	# button; the TTL is a backstop for a gateway where neither ran.
	if p is not None and p["status"] == "archived":
		p = None
	elif p is not None and p["ageMinutes"] > PROPOSAL_TTL_MINUTES:
		p = None

	if p is None:
		return empty

	proposal = p["proposal"] or {}
	definitions = proposal.get("udt_definitions") or []
	instances = proposal.get("udt_instances") or []
	standalone = proposal.get("standalone_tags") or []

	memberCount = 0
	membersByUdt = {}
	for d in definitions:
		members = d.get("members") or []
		membersByUdt[unicode(d.get("name"))] = len(members)
	for inst in instances:
		udtName = unicode(inst.get("udt_name") or "").split("/")[-1]
		memberCount += membersByUdt.get(udtName, 0)

	upload = None
	try:
		upload = getUpload(p["uploadId"])
	except:
		pass

	return {
		"proposalId": p["proposalId"],
		"status": p["status"],
		"statusLabel": _STATUS_LABELS.get(p["status"], p["status"]),
		"rationale": p["rationale"],
		"treeItems": buildTreeItems(proposal),
		"counts": {
			"udt_definitions": len(definitions),
			"udt_instances": len(instances),
			"standalone_tags": len(standalone),
			"unresolved": len(proposal.get("unresolved") or []),
		},
		"totalTags": memberCount + len(standalone),
		"canAccept": p["status"] == "proposed",
		"hasProposal": True,
		"isExecuted": p["status"] == "executed",
		"uploadFilename": upload["filename"] if upload else "",
	}


def referenceFiles():
	"""List the documents served by the 'reference' WebDev mounted folder.

	The folder is bind-mounted into the gateway from the repo, so this reads the
	real directory rather than a hardcoded list -- drop a file in
	``reference/line1/`` on the host and it appears on the page.
	"""
	out = []
	if not os.path.isdir(REFERENCE_DIR):
		return out
	for name in sorted(os.listdir(REFERENCE_DIR)):
		path = os.path.join(REFERENCE_DIR, name)
		if not os.path.isfile(path):
			continue
		out.append({
			"name": name,
			"url": "%s/%s" % (REFERENCE_URL_BASE, name.replace(" ", "%20")),
			"sizeKb": int(round(os.path.getsize(path) / 1024.0)),
		})
	return out


_REFERENCE_BLURBS = {
	"Line1_ControllerTags_Export.CSV":
		"Studio 5000 controller tag export -- this is the one the agent turns "
		"into tags.",
	"Line1_MainProgram_Logic_Export.CSV":
		"The ladder itself, one row per rung in Logix neutral text. Shows which "
		"rungs repeat machine for machine, which is the evidence for a UDT.",
}


def referenceMarkdown():
	"""Markdown for the reference-documents panel on the Tag Import page."""
	files = referenceFiles()
	if not files:
		return (
			"_No reference documents found. Check that `./reference/line1` is "
			"bind-mounted into the gateway at `%s`._" % REFERENCE_DIR
		)
	# The tag export is the one the user actually uploads, so it leads regardless
	# of alphabetical order.
	primary = PRIMARY_REFERENCE_FILE
	files.sort(key=lambda f: (f["name"] != primary, f["name"].lower()))

	lines = []
	for f in files:
		blurb = _REFERENCE_BLURBS.get(f["name"], "")
		# A markdown []() link, NOT a raw <a>. The markdown component's HTML
		# support (escapeHtml=false) is non-nesting: it renders the <a> open tag
		# as its own node, so the label text lands *after* the anchor and the
		# anchor comes out empty -- clickable nowhere, and nothing to underline.
		# Colour/underline therefore come from the `exchange/tag-import/reference-links` style class
		# (see stylesheet.css .psc-exchange\/tag-import\/reference-links) which needs !important to
		# beat the theme's own link rule.
		# HTML entity for the separator -- a non-ASCII byte in a Jython 2.7 source
		# file comes back double-encoded in the rendered page.
		lines.append(
			'- [%s](%s) &nbsp;&middot;&nbsp; %d KB%s' % (
				f["name"], f["url"], f["sizeKb"],
				("  \n  %s" % blurb) if blurb else ""
			)
		)
	return "\n".join(lines)


def readReferenceDocument(name):
	"""Read one document out of the bind-mounted reference folder.

	The demo no longer uploads anything -- the files are already on the gateway,
	so the agent reads them directly. Only files that ``referenceFiles()`` lists
	can be read: the name is matched against that list rather than joined onto a
	path, so nothing outside the folder is reachable.
	"""
	wanted = unicode(name or "").strip()
	available = referenceFiles()
	match = None
	for f in available:
		if f["name"].lower() == wanted.lower():
			match = f
			break
	if match is None:
		return {
			"status": "not_found",
			"requested": wanted,
			"available": [f["name"] for f in available],
			"message": "No reference document by that name. Pick one from 'available'.",
		}

	path = os.path.join(REFERENCE_DIR, match["name"])
	with open(path, "r") as fh:
		text = fh.read()
	truncated = False
	if len(text) > MAX_REFERENCE_CHARS:
		text = text[:MAX_REFERENCE_CHARS]
		truncated = True

	lineCount = len([ln for ln in text.splitlines() if ln.strip()])
	return {
		"status": "ok",
		"filename": match["name"],
		"sizeKb": match["sizeKb"],
		"lineCount": lineCount,
		"truncated": truncated,
		"text": text,
	}


def ensureUploadFromReference(filename=None):
	"""Make sure there is an upload row for the hosted tag export.

	``save_proposal`` keys a proposal to an upload, and the page's own history
	does too. With the upload widget gone there is nothing to create that row, so
	reading the export seeds it. Returns the existing row when the same file has
	already been staged, so repeated reads do not pile up duplicates.
	"""
	name = filename or PRIMARY_REFERENCE_FILE
	latest = getUpload(None)
	if latest is not None and latest["filename"] == name:
		return latest
	uploadId = loadSampleUpload(name)
	return getUpload(uploadId)


def createdResults(proposalId):
	"""Rows for the results table: what the agent actually created.

	Polled from the view rather than bound as a query, because the rows appear
	while the agent is mid-execution and the proposal id -- the only query
	parameter -- does not change while that happens.
	"""
	if not proposalId:
		return []
	ds = system.db.runNamedQuery(PROJECT, "Exchange/TagImport/SelectResults", {"proposalId": int(proposalId)})
	rows = []
	for r in range(ds.getRowCount()):
		rows.append({
			"object_type": unicode(ds.getValueAt(r, "object_type")),
			"object_name": unicode(ds.getValueAt(r, "object_name")),
			"tag_path": unicode(ds.getValueAt(r, "tag_path")),
			"succeeded": bool(ds.getValueAt(r, "succeeded")),
			"message": unicode(ds.getValueAt(r, "message") or ""),
		})
	return rows


# --------------------------------------------------------------------------
# Proposal validation and reference metadata for the AI agent tools
# (exchange.aiTools.tagImportAgent). Added by the tool-refactor pass: these used to live
# inline in the save_proposal / list_reference_documents tool bundles, and
# list_reference_documents read _REFERENCE_BLURBS directly.

PROPOSAL_REQUIRED_FIELDS = {
	"udt_definitions": ["name", "folder", "members"],
	"udt_instances": ["udt_name", "instance_name", "folder"],
	"standalone_tags": ["name", "datatype", "folder"],
}
"""Fields every item in each proposal section must carry."""

PROPOSAL_SECTIONS = ("udt_definitions", "udt_instances", "standalone_tags")


def referenceBlurb(name):
	"""Return the one-line description of a reference document, or "".

	Args:
		name (str): File name in REFERENCE_DIR.

	Returns:
		str: The blurb shown beside the document, empty when there is none.
	"""
	return _REFERENCE_BLURBS.get(name, "")


def validateProposal(proposal):
	"""Check a proposal's shape before it reaches the review Tree binding.

	A malformed blob would render as an empty tree with no visible error, so
	the failure has to happen here where the agent can see and correct it.

	Args:
		proposal (dict): The decoded proposal JSON.

	Returns:
		list: Human-readable error strings. Empty when the proposal is valid.
	"""
	errors = []
	if not isinstance(proposal, dict):
		return ["Top level must be a JSON object, got %s" % type(proposal).__name__]

	for section, fields in PROPOSAL_REQUIRED_FIELDS.items():
		items = proposal.get(section)
		if items is None:
			continue
		if not isinstance(items, (list, tuple)):
			errors.append("'%s' must be a list" % section)
			continue
		for i, item in enumerate(items):
			if not isinstance(item, dict):
				errors.append("%s[%d] must be an object" % (section, i))
				continue
			for field in fields:
				value = item.get(field)
				if value is None or (isinstance(value, basestring) and value.strip() == ""):
					errors.append("%s[%d] is missing '%s'" % (section, i, field))
			if section == "udt_definitions":
				members = item.get("members")
				if isinstance(members, (list, tuple)):
					if len(members) == 0:
						errors.append("%s[%d] has no members" % (section, i))
					for j, member in enumerate(members):
						if not isinstance(member, dict) or not member.get("name") or not (member.get("datatype") or member.get("dataType")):
							errors.append(
								"%s[%d].members[%d] needs both 'name' and 'datatype'"
								% (section, i, j)
							)
				else:
					errors.append("%s[%d].members must be a list" % (section, i))

	if not (proposal.get("udt_definitions") or proposal.get("udt_instances")
			or proposal.get("standalone_tags")):
		errors.append(
			"Proposal is empty -- it needs at least one of udt_definitions, "
			"udt_instances or standalone_tags."
		)
	return errors


def scopeProposalFolders(proposal):
	"""Rewrite every item's folder through the containment rule, in place.

	Done before the proposal is saved, so the tree the user reviews shows the
	paths that will actually be created -- not the paths the agent asked for.

	Args:
		proposal (dict): A proposal that has passed validateProposal.

	Returns:
		list: {section, from, to} for every folder that changed.
	"""
	rewritten = []
	for section in PROPOSAL_SECTIONS:
		for item in proposal.get(section) or []:
			asked = unicode(item.get("folder"))
			scoped = scopedFolder(asked)
			if scoped != asked:
				rewritten.append({"section": section, "from": asked, "to": scoped})
			item["folder"] = scoped
	return rewritten


def instancesUsedAsFolders(proposal):
	"""Find standalone tags aimed inside a UDT instance.

	This is the one structural mistake the model reliably makes: a machine that
	has both a repeating member set and one or two extras, with the extras
	pointed at .../Machines/<Machine> -- which by then is an instance, not a
	folder. Every one of those tags fails at create time with a Bad_Unsupported
	about overrides. Run after scopeProposalFolders so both sides compare like
	for like.

	Args:
		proposal (dict): A validated, scoped proposal.

	Returns:
		list: Error strings, one per offending standalone tag.
	"""
	instancePaths = {}
	for inst in proposal.get("udt_instances") or []:
		folder = unicode(inst.get("folder") or "").strip("/")
		name = unicode(inst.get("instance_name") or "").strip("/")
		if name:
			instancePaths["%s/%s" % (folder, name) if folder else name] = name

	errors = []
	for i, item in enumerate(proposal.get("standalone_tags") or []):
		folder = unicode(item.get("folder") or "").strip("/")
		for path, name in instancePaths.items():
			if folder == path or folder.startswith(path + "/"):
				errors.append(
					"standalone_tags[%d] ('%s') targets '%s', which is the UDT instance "
					"'%s'. A UDT instance cannot contain child tags."
					% (i, unicode(item.get("name")), folder, name)
				)
				break
	return errors
