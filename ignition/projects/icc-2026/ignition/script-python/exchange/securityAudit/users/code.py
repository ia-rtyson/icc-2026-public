"""Users, roles and account hygiene.

Two sources are merged here. ``system.user.*`` is authoritative for who exists
and what roles they hold -- it reflects the live user source, including edits
made through the Gateway UI since the last file write. But the live API exposes
no password age and no creation date, and those are exactly what an
account-hygiene audit is made of. Those come from the user source's
``users.json`` on disk.

Where the two disagree the live API wins, and the disk record is used only for
its dates. A user present on disk but absent from the API is reported rather
than silently dropped -- it usually means the file was edited without a scan,
which is itself worth knowing.
"""

import os

import exchange.securityAudit.core as core

logger = system.util.getLogger("exchange.securityAudit.Users")

# A password older than this is called out. This threshold is ours, not
# something the gateway enforces, and the finding text says so.
STALE_PASSWORD_DAYS = 365

# Name fragments that suggest a shared or generic login rather than a person.
GENERIC_NAME_HINTS = [
	"shared", "temp", "tmp", "test", "demo", "guest", "generic", "common",
	"operator", "linelead", "shift", "crew", "kiosk", "service", "svc",
	"vendor", "contractor", "training", "backup", "default",
]

# Roles that confer broad authority, used to flag over-privileged accounts.
PRIVILEGED_ROLES = ["Administrator", "Admin", "Engineer", "Developer"]

# Roles that reach gateway configuration and the Designer. Holding one of these
# is a full compromise of the gateway, so they are graded separately from the
# merely privileged.
ADMIN_ROLES = ["Administrator", "Admin"]

# More administrators than this is worth a look. An absolute count beats a
# percentage here: four administrators is four full-gateway credentials whether
# the plant has ten accounts or two hundred, and a ratio test quietly stops
# firing as the user list grows.
ADMIN_SOFT_LIMIT = 3

# An account younger than this is expected to still be on its provisioning
# password, so U008 stays quiet. Without this every freshly created account is a
# finding, which buries the accounts that have genuinely been left for years.
NEW_ACCOUNT_GRACE_DAYS = 30


def userSourceNames():
	"""Names of every configured user source."""
	names = []
	for meta in system.user.getUserSources():
		try:
			names.append(str(meta.getName()))
		except Exception:
			continue
	if not names:
		# Fall back to the config tree if the API shape ever changes on us.
		names = core.listDirs(os.path.join(core.configRoot(), "ignition", "user-source"))
	return sorted(names)


def _diskRecords(sourceName):
	"""(usersByName, rolesByUuid, path) from a user source's users.json.

	Empty dicts if the file is absent -- an external user source (LDAP, AD)
	legitimately has no users.json, and that is not a finding.
	"""
	path = os.path.join(core.configRoot(), "ignition", "user-source",
	                    sourceName, "users.json")
	data = core.readJson(path)
	if not data:
		return {}, {}, path
	rolesByUuid = {}
	for r in data.get("roles") or []:
		rolesByUuid[unicode(r.get("uuid"))] = unicode(r.get("rolename"))
	byName = {}
	for u in data.get("users") or []:
		byName[unicode(u.get("username"))] = u
	return byName, rolesByUuid, path


def inventory():
	"""Full user/role inventory across every user source."""
	sources = []
	totalUsers = 0
	for name in userSourceNames():
		diskUsers, rolesByUuid, diskPath = _diskRecords(name)

		try:
			liveRoles = sorted([unicode(r) for r in system.user.getRoles(name)])
		except Exception, e:
			logger.warn("getRoles(%s) failed: %s" % (name, e))
			liveRoles = sorted(rolesByUuid.values())

		try:
			liveUsers = system.user.getUsers(name)
		except Exception, e:
			logger.warn("getUsers(%s) failed: %s" % (name, e))
			liveUsers = []

		users = []
		seen = set()
		for u in liveUsers:
			username = unicode(u.get("username") or "")
			seen.add(username)
			rec = diskUsers.get(username) or {}
			try:
				contacts = len(u.getContactInfo())
			except Exception:
				contacts = len(rec.get("contactInfos") or [])
			pwRaw = rec.get("passwordDate")
			createdRaw = rec.get("createdDate")
			users.append({
				"username": username,
				"firstName": unicode(u.get("firstname") or ""),
				"lastName": unicode(u.get("lastname") or ""),
				"roles": sorted([unicode(r) for r in u.getRoles()]),
				"schedule": unicode(u.get("schedule") or ""),
				"badge": unicode(u.get("badge") or ""),
				"notes": unicode(u.get("notes") or ""),
				"contactCount": contacts,
				"passwordAgeDays": core.daysSince(pwRaw),
				"accountAgeDays": core.daysSince(createdRaw),
				# A password date still equal to the creation date means the
				# account is very likely on its provisioning password.
				"passwordNeverChanged": bool(
					pwRaw and createdRaw
					and unicode(pwRaw).split(".")[0] == unicode(createdRaw).split(".")[0]),
			})

		orphanedOnDisk = sorted([n for n in diskUsers.keys() if n not in seen])

		totalUsers += len(users)
		sources.append({
			"name": name,
			"file": core.rel(diskPath),
			"users": sorted(users, key=lambda x: x["username"]),
			"roles": liveRoles,
			"orphanedOnDisk": orphanedOnDisk,
		})

	allRoles = set()
	for s in sources:
		for r in s["roles"]:
			allRoles.add(r)

	return {
		"sources": sources,
		"totals": {
			"sourceCount": len(sources),
			"userCount": totalUsers,
			"roleCount": len(allRoles),
		},
	}


def _looksGeneric(username):
	"""The matched hint if the username reads like a shared login, else None."""
	low = username.lower()
	for hint in GENERIC_NAME_HINTS:
		if hint in low:
			return hint
	return None


def audit(inv=None):
	"""Findings for the users/roles domain."""
	inv = inv or inventory()
	out = []

	for src in inv["sources"]:
		name = src["name"]
		cite = src["file"]

		# A role nobody holds is dead config that still appears in every role
		# picker and permission dialog, where it gets selected by mistake.
		held = set()
		for u in src["users"]:
			for r in u["roles"]:
				held.add(r)
		for role in src["roles"]:
			if role not in held:
				out.append(core.finding(
					"U003", "LOW", "users",
					"Role %s is defined but assigned to no user" % role,
					"User source %s defines the role %s, but no account in that "
					"source holds it." % (name, role),
					cite,
					"Delete the role, or assign it to the accounts it was "
					"created for.",
					{"userSource": name, "role": role}))

		for u in src["users"]:
			un = u["username"]
			liveCite = "system.user.getUsers(%s) + %s" % (name, cite)

			if not u["roles"]:
				out.append(core.finding(
					"U002", "MEDIUM", "users",
					"Account %s holds no roles" % un,
					"%s can authenticate against user source %s but holds no "
					"roles, so it satisfies the Authenticated security level "
					"while matching no role-based rule. What it can actually "
					"reach then depends on each individual permission check, "
					"which makes its real access unpredictable." % (un, name),
					liveCite,
					"Assign the roles this account is meant to have, or disable "
					"the account.",
					{"userSource": name, "username": un}))

			hint = _looksGeneric(un)
			if hint:
				out.append(core.finding(
					"U005", "HIGH", "users",
					"Account %s looks like a shared login" % un,
					"The name contains %s, which suggests more than one person "
					"uses it. A shared account destroys attribution: the audit "
					"log and the alarm journal record the account, not the "
					"operator, so nothing done through it traces back to a "
					"human. It also cannot be revoked when one of its users "
					"leaves." % hint,
					liveCite,
					"Replace it with named per-person accounts and disable the "
					"shared login.",
					{"userSource": name, "username": un, "matched": hint,
					 "roles": u["roles"]}))

			days = u["passwordAgeDays"]
			if days is not None and days > STALE_PASSWORD_DAYS:
				out.append(core.finding(
					"U001", "HIGH", "users",
					"Password for %s is %d days old" % (un, days),
					"The stored password date is %d days ago, past the %d-day "
					"threshold this audit applies. That threshold is this "
					"audit's, not the gateway's -- no password expiry policy is "
					"configured on this user source at all."
					% (days, STALE_PASSWORD_DAYS),
					cite,
					"Rotate the password, and consider moving this user source "
					"behind an external IdP that can enforce expiry centrally.",
					{"userSource": name, "username": un, "ageDays": days}))

			acctAge = u["accountAgeDays"]
			if u["passwordNeverChanged"] and (acctAge is None
			                                  or acctAge > NEW_ACCOUNT_GRACE_DAYS):
				out.append(core.finding(
					"U008", "LOW", "users",
					"Password for %s has never been changed" % un,
					"The password date still matches the account creation date "
					"and the account is %s days old, so it is very likely still "
					"using the password it was provisioned with."
					% (acctAge if acctAge is not None else "an unknown number of"),
					cite,
					"Force a password change at next login.",
					{"userSource": name, "username": un}))

			privileged = [r for r in u["roles"] if r in PRIVILEGED_ROLES]
			if privileged and u["contactCount"] == 0:
				out.append(core.finding(
					"U006", "LOW", "users",
					"Privileged account %s has no contact information" % un,
					"%s holds %s but has no email or phone on file, so there is "
					"no way to reach the holder to verify a change or warn them "
					"of a compromise." % (un, ", ".join(privileged)),
					cite,
					"Add contact information, or drop the privileged role if "
					"the account is not attached to a person.",
					{"userSource": name, "username": un, "roles": privileged}))

		if src["orphanedOnDisk"]:
			out.append(core.finding(
				"U007", "MEDIUM", "users",
				"User source %s has %d account(s) on disk the gateway is not "
				"serving" % (name, len(src["orphanedOnDisk"])),
				"These accounts exist in users.json but were not returned by "
				"the live API: %s. That usually means the file was edited "
				"without a config scan, so the running gateway and the "
				"committed configuration disagree about who can log in."
				% ", ".join(src["orphanedOnDisk"]),
				src["file"],
				"Run a config scan, then confirm the live account list matches "
				"the committed file.",
				{"userSource": name, "accounts": src["orphanedOnDisk"]}))

	# Cross-source: who holds the keys to the gateway?
	admins = []
	privilegedGenerics = []
	for src in inv["sources"]:
		for u in src["users"]:
			isAdmin = [r for r in u["roles"] if r in ADMIN_ROLES]
			if isAdmin:
				admins.append("%s/%s" % (src["name"], u["username"]))
			hint = _looksGeneric(u["username"])
			privileged = [r for r in u["roles"] if r in PRIVILEGED_ROLES]
			if hint and privileged:
				privilegedGenerics.append({
					"account": "%s/%s" % (src["name"], u["username"]),
					"roles": privileged,
					"matched": hint,
					"isAdmin": bool(isAdmin),
				})

	# The sharpest finding an account audit can make: a login that no single
	# person owns, holding a role that can change the plant.
	for g in privilegedGenerics:
		sev = "CRITICAL" if g["isAdmin"] else "HIGH"
		out.append(core.finding(
			"U009", sev, "users",
			"Shared account %s holds %s" % (g["account"], ", ".join(g["roles"])),
			"%s reads as a shared or service login (its name contains %s) and "
			"holds %s. Those two facts together are worse than either alone: the "
			"role can change the system, and the account cannot tell you who "
			"used it. Nothing done through it is attributable, and it cannot be "
			"revoked when one of the people holding the password leaves."
			% (g["account"], g["matched"], ", ".join(g["roles"])),
			"system.user.getUsers()",
			"Replace it with named accounts holding the same role, then disable "
			"this login. If it is a service account, give it only the "
			"permissions the service actually calls.",
			g))

	if len(admins) > ADMIN_SOFT_LIMIT:
		out.append(core.finding(
			"U004", "HIGH", "users",
			"%d accounts hold an administrator role" % len(admins),
			"Administrator is held by %s. Each one is a full compromise of the "
			"gateway: it reaches the Gateway configuration pages, the Designer "
			"and every project. More than %d is worth questioning -- "
			"administering the gateway is a smaller job than running the plant, "
			"and the two rarely need the same credential."
			% (", ".join(admins), ADMIN_SOFT_LIMIT),
			"system.user.getUsers()",
			"Move day-to-day work onto least-privilege roles and reduce "
			"administrator to the people who administer the gateway itself.",
			{"admins": admins, "limit": ADMIN_SOFT_LIMIT}))

	return core.sortFindings(out)
