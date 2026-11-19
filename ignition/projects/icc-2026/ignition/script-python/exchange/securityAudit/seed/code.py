"""Seed a realistic security model for the Security Audit Agent demo.

Out of the box this gateway has one account (admin) holding one role
(Administrator), and every permission block on it is empty. An audit of that is
accurate and useless as a demo: the entire report is "there is nothing
configured".

So this builds a plant that looks like a real one -- eleven people across six
roles, on schedules -- and then plants a specific set of defects for the audit
to find. The defects are listed in PLANTED below, each keyed to the finding id
it should trigger, which makes this file double as the expected-results fixture:
if the audit stops reporting one of them, that is a regression in the audit, not
a change in the plant.

Everything here is idempotent. Running it twice produces the same gateway.

    exchange.securityAudit.seed.seedAll()      # roles, users, schedules
    exchange.securityAudit.seed.verify()       # confirm the planted defects are present
    exchange.securityAudit.seed.resetAll()     # remove everything this created

What this module does *not* do is edit gateway config files -- the security
level tree, the identity provider rules and the per-resource permission blocks
all live in git and reach the gateway through a scan. Those parts of the seed
ship as committed config, not as script writes, because those files are the
deployment artifact and a script write would be reverted by the next deploy.
"""

import sys

from com.inductiveautomation.ignition.common.user import ContactInfo, User
from java.util import ArrayList

import exchange.securityAudit.core as core

logger = system.util.getLogger("exchange.securityAudit.Seed")

USER_SOURCE = "default"

# Roles the seeded plant uses. Administrator already exists on a stock gateway.
ROLES = [
	"Administrator",
	"Engineer",
	"Supervisor",
	"Operator",
	"Maintenance",
	"Contractor",
]

# Schedules referenced by the seeded users. "Always" ships with Ignition.
SCHEDULES = [
	("Day Shift", "6:00am-6:00pm", "Mon,Tue,Wed,Thu,Fri"),
	("Night Shift", "6:00pm-6:00am", "Mon,Tue,Wed,Thu,Fri"),
]

# The seeded workforce.
#
# password: every seeded account gets the same throwaway password. This is a
# demo gateway on an internal network and these accounts exist to be audited,
# not used. It is stated here rather than hidden so nobody mistakes one of these
# for a real credential.
SEED_PASSWORD = "Icc2026!demo"

USERS = [
	# (username, first, last, roles, schedule, email)
	("dmorales",   "Diana",  "Morales",  ["Administrator", "Engineer"], "Always",      "dmorales@example.com"),
	("rchen",      "Ray",    "Chen",     ["Engineer"],                  "Day Shift",   "rchen@example.com"),
	("pnovak",     "Petra",  "Novak",    ["Engineer"],                  "Day Shift",   "pnovak@example.com"),
	("jokafor",    "Joy",    "Okafor",   ["Supervisor"],                "Day Shift",   "jokafor@example.com"),
	("mhaddad",    "Malik",  "Haddad",   ["Supervisor"],                "Night Shift", "mhaddad@example.com"),
	("sberg",      "Sam",    "Berg",     ["Operator"],                  "Day Shift",   "sberg@example.com"),
	("tvasquez",   "Tomas",  "Vasquez",  ["Operator"],                  "Night Shift", "tvasquez@example.com"),
	("adubois",    "Amara",  "Dubois",   ["Operator"],                  "Day Shift",   "adubois@example.com"),
	("korlov",     "Kira",   "Orlov",    ["Maintenance"],               "Day Shift",   "korlov@example.com"),
	("bfitzgerald", "Brian", "Fitzgerald", ["Maintenance"],             "Night Shift", "iggy@example.com"),
]

# Deliberately defective accounts, each paired with the finding it should
# produce. Kept separate from USERS so the healthy baseline stays readable.
PLANTED_USERS = [
	# U005 shared login: the name says it is used by a whole shift, and it holds
	# an operating role, so nothing done through it can be attributed.
	("linelead", "Line", "Lead", ["Operator", "Supervisor"], "Always", None,
	 "U005", "Shared shift login with no owner"),

	# U005 + U004: a contractor account left active after the engagement, with
	# a name that reads as generic and roles far beyond what a contractor needs.
	("contractor1", "Contract", "Integrator", ["Engineer", "Administrator"],
	 "Always", None,
	 "U005", "Contractor account still active, holding Administrator"),

	# U002: provisioned and never finished -- authenticates, holds nothing.
	("jhalvorsen", "Jonas", "Halvorsen", [], "Always", "jhalvorsen@example.com",
	 "U002", "Account provisioned but never assigned a role"),

	# U006: privileged, no contact information, so nobody can be reached to
	# verify a change made through it.
	("svc_historian", "Service", "Historian", ["Administrator"], "Always", None,
	 "U006", "Service account holding Administrator with no owner contact"),
]

# What the audit is expected to report once this has run. Used by verify().
PLANTED = [
	("U005", "linelead reads as a shared login"),
	("U005", "contractor1 reads as a generic/contractor login"),
	("U005", "svc_historian reads as a service login"),
	("U009", "contractor1 and svc_historian are shared logins holding Administrator"),
	("U002", "jhalvorsen holds no roles"),
	("U004", "More than three accounts hold an administrator role"),
	("U006", "svc_historian is privileged with no contact information"),
	("U003", "Contractor role is defined but held by nobody"),
]


def _ensureSchedules():
	"""Create the shift schedules the seeded users reference."""
	existing = set([unicode(s) for s in system.user.getScheduleNames()])
	made = []
	for name, timeRange, days in SCHEDULES:
		if name in existing:
			continue
		try:
			from com.inductiveautomation.ignition.common.user.schedule import BasicScheduleModel
			model = BasicScheduleModel(name)
			model.setAllDay(False)
			model.setTimeRange(timeRange)
			model.setDaysOfWeek(days)
			system.user.addSchedule(model)
			made.append(name)
		except:
			e = sys.exc_info()[1]
			# A missing schedule is cosmetic here -- the account still exists and
			# is still auditable, so fall back to Always rather than aborting.
			logger.warn("Could not create schedule '%s' (%s); seeded users will "
			            "fall back to Always." % (name, e))
	return made


def _scheduleOrAlways(name):
	try:
		if name in [unicode(s) for s in system.user.getScheduleNames()]:
			return name
	except:
		pass
	return "Always"


def _ensureRoles():
	"""Create every seeded role that does not already exist."""
	existing = set([unicode(r) for r in system.user.getRoles(USER_SOURCE)])
	made = []
	for role in ROLES:
		if role in existing:
			continue
		system.user.addRole(USER_SOURCE, role)
		made.append(role)
	return made


def _responseErrors(response):
	"""Error strings out of a UIResponse, or [] if there were none.

	system.user.addUser and editUser do not raise on a validation failure --
	they return a UIResponse carrying the errors. An earlier version of this
	module ignored the return value and reported fourteen accounts as created
	when the user source had accepted none of them, so the return value is now
	always inspected.
	"""
	if response is None:
		return []
	errs = []
	try:
		for e in response.getErrors() or []:
			errs.append(unicode(e))
	except:
		e = sys.exc_info()[1]
		logger.warn("Could not read UIResponse: %s" % e)
	return errs


def _upsertUser(username, first, last, roles, schedule, email, notes=None):
	"""Create or update one account. Returns "created" | "updated".

	Raises on a validation failure so seedAll records it, rather than letting a
	rejected account be reported as seeded.
	"""
	existing = system.user.getUser(USER_SOURCE, username)
	# getNewUser takes (userSource, username) -- it seeds the record with the
	# name rather than handing back a blank one.
	user = existing if existing is not None \
		else system.user.getNewUser(USER_SOURCE, username)

	user.set(User.Username, username)
	user.set(User.FirstName, first)
	user.set(User.LastName, last)
	user.set(User.Schedule, _scheduleOrAlways(schedule))
	if notes:
		user.set(User.Notes, notes)
	user.setRoles(roles)

	if email:
		# setContactInfo with a fresh list, not getContactInfo().add(...).
		# Mutating the list the getter hands back is accepted without error and
		# then silently discarded on save, which had every seeded account
		# reporting as having no contact information.
		try:
			contacts = ArrayList()
			contacts.add(ContactInfo("email", email))
			user.setContactInfo(contacts)
		except:
			e = sys.exc_info()[1]
			logger.warn("Could not set contact info for %s: %s" % (username, e))

	if existing is None:
		# The password has to be on the object before it is added -- an internal
		# user source rejects an account with no credential.
		user.set(User.Password, SEED_PASSWORD)
		errs = _responseErrors(system.user.addUser(USER_SOURCE, user))
		if errs:
			raise Exception("addUser rejected '%s': %s" % (username, "; ".join(errs)))
		return "created"

	errs = _responseErrors(system.user.editUser(USER_SOURCE, user))
	if errs:
		raise Exception("editUser rejected '%s': %s" % (username, "; ".join(errs)))
	return "updated"


def seedAll():
	"""Create the roles, schedules and accounts. Idempotent."""
	made = {"schedules": _ensureSchedules(), "roles": _ensureRoles(),
	        "created": [], "updated": [], "failed": []}

	everyone = []
	for username, first, last, roles, schedule, email in USERS:
		everyone.append((username, first, last, roles, schedule, email, None))
	for username, first, last, roles, schedule, email, fid, why in PLANTED_USERS:
		everyone.append((username, first, last, roles, schedule, email,
		                 "SEEDED DEFECT (%s): %s" % (fid, why)))

	for username, first, last, roles, schedule, email, notes in everyone:
		try:
			action = _upsertUser(username, first, last, roles, schedule, email, notes)
			made[action].append(username)
		except:
			e = sys.exc_info()[1]
			logger.error("Seeding %s failed: %s" % (username, e))
			made["failed"].append({"username": username, "error": unicode(e)})

	logger.info("Seed complete: %d created, %d updated, %d failed"
	            % (len(made["created"]), len(made["updated"]), len(made["failed"])))
	made["note"] = ("Roles, schedules and accounts are seeded. The security "
	                "level tree, identity-provider rules and per-resource "
	                "permission blocks ship as committed config -- run a config "
	                "scan to pick those up.")
	return made


def verify():
	"""Run the audit and confirm every planted defect was actually found.

	Reports what is missing rather than raising, so a partial seed is diagnosable
	instead of just broken.
	"""
	audit = exchange.securityAudit.report.runAudit()
	foundIds = set([f["id"] for f in audit["findings"]])

	results = []
	for fid, description in PLANTED:
		results.append({
			"findingId": fid,
			"planted": description,
			"detected": fid in foundIds,
		})

	missing = [r for r in results if not r["detected"]]
	return {
		"seededUsers": len(USERS) + len(PLANTED_USERS),
		"totalFindings": audit["findingCount"],
		"postureScore": audit["score"],
		"counts": audit["counts"],
		"planted": results,
		"missing": missing,
		"ok": not missing,
		"note": ("Every planted defect was detected." if not missing else
		         "%d planted defect(s) were not detected -- the audit rule for "
		         "each is either missing or no longer matching." % len(missing)),
	}


def resetAll():
	"""Remove every account and role this module created.

	Leaves 'admin' and 'Administrator' alone -- they predate the seed, and
	deleting the only administrator would lock the gateway.
	"""
	removedUsers = []
	seededNames = [u[0] for u in USERS] + [u[0] for u in PLANTED_USERS]
	for username in seededNames:
		try:
			if system.user.getUser(USER_SOURCE, username) is not None:
				system.user.removeUser(USER_SOURCE, username)
				removedUsers.append(username)
		except:
			e = sys.exc_info()[1]
			logger.warn("Could not remove %s: %s" % (username, e))

	removedRoles = []
	for role in ROLES:
		if role == "Administrator":
			continue
		try:
			system.user.removeRole(USER_SOURCE, role)
			removedRoles.append(role)
		except:
			e = sys.exc_info()[1]
			logger.warn("Could not remove role %s: %s" % (role, e))

	logger.info("Reset: removed %d user(s), %d role(s)"
	            % (len(removedUsers), len(removedRoles)))
	return {"removedUsers": removedUsers, "removedRoles": removedRoles}
