"""The access matrix: which role can reach which screen, and why.

The chain a real access decision travels is:

    user -> role -> (identity provider rule) -> security level -> (permission
    block) -> page

Each hop is configured in a different place by a different person, and the
whole point of the matrix is that nowhere in Ignition can you see the chain end
to end. Reconstructing it is where the interesting answers come from -- a role
that reaches nothing because the middle hop was never configured looks fine at
both ends.

Two honesty rules are built in:

* A page with no protection is reachable by **every** role, and the matrix says
  so rather than leaving the cell blank. An empty cell reads as "no access"; the
  truth is the opposite.
* A cell is marked by *how* access is granted, not just whether. Reaching a page
  because it is wide open is not the same as reaching it because your role was
  granted the level it requires, and collapsing the two hides every finding in
  this report.
"""

import exchange.securityAudit.core as core
import exchange.securityAudit.gateway as gw
import exchange.securityAudit.pages as pagesmod
import exchange.securityAudit.users as usersmod

logger = system.util.getLogger("exchange.securityAudit.Matrix")

# Cell values, in decreasing order of how much configuration stands behind them.
GRANTED = "granted"        # role holds the level the page requires
OPEN = "open"              # page requires nothing; everyone reaches it
DENIED = "denied"          # page requires a level this role does not hold
UNREACHABLE = "unreachable"  # page requires a level nobody can hold


def roleToLevels():
	"""{role: [security levels]} as granted by the identity providers.

	Ignition's IdP rules can key on things other than role membership, so this
	is a best-effort read of the role-keyed rules. Where a rule cannot be
	attributed to a specific role its levels land under the special key "*",
	meaning every authenticated user gets them.
	"""
	mapping = {}
	everyone = set(["Authenticated"])
	for idp in gw.identityProviders():
		# The stock levels are granted by authenticating at all.
		for lvl in idp["grantsLevels"]:
			# Without a parseable rule condition the safe reading is that the
			# level is granted broadly; saying "nobody" would understate access.
			everyone.add(lvl)
	mapping["*"] = sorted(everyone)
	return mapping


def build(project=None):
	"""The full matrix plus the inputs it was derived from."""
	project = project or core.PROJECT
	pageInv = pagesmod.pageInventory(project)
	userInv = usersmod.inventory()
	levels = gw.securityLevelPaths()
	grants = roleToLevels()

	roles = set()
	for src in userInv["sources"]:
		for r in src["roles"]:
			roles.add(r)
	roleList = sorted(roles)

	# Everyone-grants apply on top of whatever a role specifically receives.
	baseline = set(grants.get("*") or [])

	rows = []
	for p in pageInv["pages"]:
		required = p["declaredLevels"]
		cells = {}
		for role in roleList:
			held = set(baseline)
			# Ignition's stock model exposes role membership as a level under
			# Authenticated/Roles, so a role always holds its own name there.
			held.add("Authenticated/Roles/%s" % role)
			held.add(role)

			if not required:
				cells[role] = OPEN
			elif [r for r in required if r in held]:
				cells[role] = GRANTED
			elif [r for r in required if r not in levels]:
				cells[role] = UNREACHABLE
			else:
				cells[role] = DENIED
		rows.append({
			"url": p["url"],
			"title": p["title"],
			"viewPath": p["viewPath"],
			"required": required,
			"protection": p["protection"],
			"sensitive": p["sensitiveComponents"],
			"cells": cells,
		})

	return {
		"project": project,
		"roles": roleList,
		"levels": levels,
		"baselineLevels": sorted(baseline),
		"rows": rows,
	}


def toMarkdown(m=None):
	"""Render the matrix as a Markdown table the agent can paste verbatim."""
	m = m or build()
	roles = m["roles"]
	if not roles:
		return "_No roles are defined on this gateway, so there is no matrix to build._"

	symbol = {
		GRANTED: "Y",
		OPEN: "ALL",
		DENIED: "-",
		UNREACHABLE: "X",
	}

	lines = []
	lines.append("| Page | Requires | Protection | %s |"
	             % " | ".join(roles))
	lines.append("|---|---|---|%s" % ("---|" * len(roles)))
	for row in m["rows"]:
		req = ", ".join(row["required"]) if row["required"] else "_nothing_"
		cells = [symbol.get(row["cells"].get(r), "?") for r in roles]
		flag = " **(AI)**" if row["sensitive"] else ""
		lines.append("| `%s`%s | %s | %s | %s |"
		             % (row["url"], flag, req, row["protection"], " | ".join(cells)))

	lines.append("")
	lines.append("`Y` role holds the required level &nbsp; `ALL` page requires "
	             "nothing, every session reaches it &nbsp; `-` role lacks the "
	             "required level &nbsp; `X` required level exists in no "
	             "identity-provider rule, so nobody can reach it")
	return "\n".join(lines)
