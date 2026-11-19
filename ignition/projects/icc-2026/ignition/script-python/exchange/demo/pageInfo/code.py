"""exchange.demo.pageInfo -- the copy behind the "i" info dock.

One entry per Perspective page. The info dock (Exchange/Demo/Page Info) binds to
``page.props.path`` and calls ``markdown(path)``, so adding a page's help text is
a single edit here rather than a new view.

The audience is a presenter, not an engineer. Each entry has these parts:
	hook    -- the one-sentence pitch: what this page proves to a customer
	run     -- what to click, and what to say while clicking it
	prompts -- optional; the prompts a page offers, for the agent-driven pages
	say     -- the two or three points to land before moving on

Keep it short. This is a cue card, not documentation.

Jython 2.7. No f-strings, no type hints.
"""

logger = system.util.getLogger("exchange.demo.PageInfo")


_PAGES = {

	"/what-is-an-agent": {
		"title": "What is an Agent?",
		"hook": [
			"One screen, no jargon: an agent is a model connection, a system prompt and "
			"a set of tools -- and you own two of the three.",
			"",
			"Run this first in a room that has not seen an agent before. Everything "
			"after it lands better.",
		],
		"run": [
			"**The page opens with all three parts on screen** -- there is nothing to "
			"click. \"That's genuinely it. Everything else is detail.\"",
			"**Walk the three cards** in whatever order the room wants: the **model "
			"connection** (OpenRouter, OpenAI, a locally hosted Ollama or Anthropic, "
			"with your own model behind it), the **system prompt** (plain English, "
			"written once -- Step 1 browse, Step 2 query history, then a worked "
			"example of the email it writes), and the **tools** -- two named "
			"functions, browse_tags and query_tag_history.",
		],
		"say": [
			"\"The prompt and the tools are yours. You write them, you can read them, "
			"they're in version control. Only the model is the vendor's.\"",
			"",
			"\"Look at the tools list -- two functions, both read-only. That's the "
			"whole surface. The agent cannot do anything that isn't on that card, and "
			"that's the answer to 'what if it does something crazy.'\"",
			"",
			"\"And this is not a mock-up -- that is the real prompt and the real two "
			"tools behind the Alarm Notification Agent, the one that sent the email in "
			"the alarm flood demo.\"",
			"",
			"\"Swap the model for a better one and the same agent gets better. The "
			"prompt and the tools don't change.\"",
		],
	},

	"/translation-manager": {
		"title": "Translation Manager Agent",
		"hook": [
			"A finished English screen, and one click later it is in Spanish -- including "
			"the strings nobody remembered to make translatable.",
			"",
			"The page carries no translate controls of its own -- the **top bar** is the "
			"only control, and it works here exactly the same way it works on any other "
			"page.",
		],
		"run": [
			"**Point at the dashboard** -- \"a normal Perspective screen. Every label on "
			"it is hardcoded English, which is how most projects actually look.\"",
			"**Pick a language** in the top bar, then press **Translate** -- it walks "
			"the view's own JSON, finds every literal label, and registers a translation "
			"for each.",
			"**Read the status** beside the buttons: added / already / failed.",
			"**Switch the session locale** (the language buttons in the top bar) to see "
			"the screen come back translated.",
		],
		"say": [
			"\"Ignition can only translate text it knows about as a term. The tedious part "
			"of localizing an existing project is finding the hundreds of strings nobody "
			"registered -- that's the part being automated here.\"",
			"",
			"\"The control lives in the shared top bar, not on this page -- it reads "
			"whatever URL you're standing on, so nothing here is wired up specially.\"",
			"",
			"\"It also decides what NOT to translate -- equipment names, tag paths, units.\"",
		],
	},

	"/designer-embeds-example": {
		"title": "Designer Embeds Example",
		"hook": [
			"A working filtered event log -- filters, query, paged table -- built by the "
			"AI in the Designer rather than by hand.",
		],
		"run": [
			"**Set a filter or two** (Area, Last Hours, Min Severity) and press "
			"**Run Query**.",
			"**Point at the status line** -- row count and the time it ran.",
			"**Page through the table**, sort a column.",
		],
		"say": [
			"\"This is not a mockup. The filters are wired to a real named query against "
			"Postgres, and the table is paging real rows.\"",
			"",
			"\"The point is the *finished* state: layout, filter panel, query parameters "
			"and result binding all agree with each other. That agreement is what usually "
			"takes the afternoon.\"",
			"",
			"_The data keeps itself fresh_ -- a gateway timer adds an event every 20 "
			"minutes and ages the old ones out, so the default *last 24 hours* filter is "
			"never empty.",
		],
	},

	"/db-wrecker": {
		"title": "DB Wrecker",
		"hook": [
			"Deliberately break the database's day, so there is something real for the "
			"gateway's diagnostics -- and the AI Diagnostic Digest -- to find.",
			"",
			"A gateway timer now runs this same slow query on its own every ~15 "
			"seconds, so the Diagnostics -> Database view already has something "
			"slow in it even if nobody presses a button first.",
		],
		"run": [
			"**Run One Slow Query** -- takes about 11 seconds and comes back with 25 rows. "
			"Layers on top of the background timer for a bigger spike if you want one.",
			"**Run 3 Sequential** for a sustained load, or set a count and "
			"**Launch Concurrent Slow Calls** to fire up to 20 at once.",
			"**Switch to the gateway's Diagnostics -> Database** while they run: the "
			"connection's active queries and durations are visibly bad.",
			"**Then ask the Diagnostic Digest** what is wrong with the gateway.",
		],
		"say": [
			"\"Every demo of a diagnostic tool needs something actually wrong. This is a "
			"query engineered to be slow -- a 10 second sleep and a self-join that does "
			"about a million and a half hash comparisons.\"",
			"",
			"\"It reads its own table, not the historian, so hammering it does not "
			"disturb the alarm-flood data being recorded next door.\"",
			"",
			"\"You don't even need this page. The LongRunningQuery gateway timer fires "
			"the same query on its own the whole time this stack is up -- ask the "
			"Digest cold and it still has something to find.\"",
		],
	},

	"/tag-import": {
		"title": "Tag Import Agent",
		"hook": [
			"Tag mapping is the part of every project that eats weeks. Hand the AI a "
			"Studio 5000 export and it builds the tag model for you -- and gets the "
			"judgement calls right.",
		],
		"run": [
			"**Point at the source files** (top left) -- \"a Studio 5000 controller tag "
			"export, 117 tags, exactly what a customer sends us, plus the ladder itself "
			"rung by rung. They are sitting on the gateway; nobody uploads anything.\"",
			"**Click the first suggested prompt** in the chat -- \"read the export and "
			"show me the proposal.\" One click sends it. \"It reads the export itself "
			"and looks for what repeats across machines.\"",
			"**Read the review panel** on the right: the counts, then walk the proposed "
			"tree -- \"five identical machines, one reusable template instead of copying "
			"tags five times.\" The reasoning is in the chat beside it.",
			"**Ask it what *Unresolved* means** -- type it, there is no chip for this "
			"one. It is the best question in the demo: it explains what it deliberately "
			"refused to guess at.",
			"**Second prompt, \"go ahead and create it\"** -- there are no buttons on the "
			"panel, approval is just something you say -- and 117 tags appear in the "
			"gateway.",
			"**To reset between runs**, the third prompt deletes the old demo tags; it "
			"empties the Exchange/Tag Import Agent folder and nothing else.",
		],
		"say": [
			"\"Weeks of tag mapping, done in a conversation.\"",
			"",
			"\"The smart part is what it *left out*. Ambient temperature and shift number "
			"belong to the whole line, not to one machine -- it kept those separate. "
			"That's the judgement call a junior engineer usually gets wrong.\"",
			"",
			"\"It read the ladder too, not just the tag list. Its own reason for the "
			"template is 'identical rung patterns per machine' -- that's the argument an "
			"engineer would make.\"",
			"",
			"\"Nothing was created until I said so in the chat. The AI proposes, a human "
			"accepts -- and that gate is in the tool, not just the prompt.\"",
			"",
			"\"And it can only write inside one folder. That is enforced in the tool, not "
			"asked for in the prompt.\"",
		],
	},

	"/alarm-flood-event": {
		"title": "Alarm Flood Event",
		"hook": [
			"Break one motor and watch twenty-seven alarms happen on their own -- then ask "
			"the AI which one actually mattered. Both on this page.",
		],
		"run": [
			"**Press 1. Simulate Alarm Flood.** The line degrades, the belt parts, and "
			"the backup walks upstream -- \"I broke a motor, I did not write these "
			"alarms.\" The button disables itself while a flood is running, so it "
			"can't be double-pressed.",
			"**Watch the mimic**: each station freezes in turn, Packaging first, and the "
			"buffers fill behind it. The line is fully stopped 30 seconds in.",
			"**Press 2. Alarm Notification Agent** to open the mailbox in a new tab -- "
			"the flood went out as an email, written by a second agent. React to it "
			"as an operator would, then come back.",
			"**Once the line is back up, press 3. Alarm Flood Agent** to slide out the "
			"chat, then **click the first suggested prompt** -- \"Analyze the most "
			"recent flood.\" One click sends it.",
			"**Read the report** and point at the bolded root cause, then click the "
			"second prompt, \"What should the operator do?\" -- it answers with a "
			"rendered trend chart, not a table.",
		],
		"say": [
			"\"Nothing here is scripted. Five production lines are running a live process "
			"simulation -- I broke one motor, and the alarms happened on their own.\"",
			"",
			"\"That matters, because the agent isn't reading a script either. It has four "
			"tools -- the stored flood event, the historian, live tag reads, and a chart "
			"renderer -- and it has to reconstruct the chain itself.\"",
			"",
			"\"The loudest alarm was not the cause. A conveyor motor started binding and "
			"everything downstream followed. That's the diagnosis that normally takes an "
			"experienced engineer an hour.\"",
			"",
			"\"It answers with a chart, not a spreadsheet -- and marks where the problem "
			"actually started.\"",
			"",
			"_Timing:_ the run recovers itself in under 90 seconds -- keep talking over it.",
			"",
			"_There is no abort button on this page._ If you genuinely need to cut one "
			"short, that is a script-console call (`exchange.alarmFlood.sim.abortFlood()` / "
			"`resetAll()`), not something to reach for on stage.",
		],
	},

	"/report-issue": {
		"title": "Report Issue Agent -- Line Overview",
		"hook": [
			"An operator says \"this screen looks wrong.\" The AI turns that sentence into "
			"a proper engineering ticket -- then three agents hand it off: write it, check "
			"it, fix it.",
		],
		"run": [
			"**Use the screen as an operator would** for a moment, then point at the "
			"**Drive Torque** tile -- red box, reading null. \"Something is wrong and I "
			"don't know why.\"",
			"**Press Report an Issue.** The chat slides out from the right, with the "
			"captured context above it: the component, the view, the binding.",
			"**Click the first suggested prompt** (\"There's an issue with the drive "
			"torque\") -- \"that's all the operator has to do.\" Let it investigate, then "
			"click the **second** to file the ticket.",
			"**Press YouTrack** in the header to open the real board in a new tab and "
			"read the ticket it just wrote. Sign in as **admin** / **admin** if it asks.",
			"**Move the card to the next column yourself.** That is the human gate, and "
			"it is what starts Validate, and then Implement.",
			"**Press Pipeline Status** in the header -- it slides out over this page, so "
			"you never leave the line you just reported on. Read what each agent wrote.",
		],
		"say": [
			"\"Operators see problems and don't report them, because filing a good ticket "
			"is work. This removes that.\"",
			"",
			"\"Behind the scenes the AI looked at the actual screen and the data behind "
			"it, so the ticket names the real component -- not just 'the screen looks "
			"wrong.'\"",
			"",
			"\"Report, validate, implement. Each agent checks the one before it -- the "
			"second agent's whole job is to push back on the first.\"",
			"",
			"\"And nothing moves between them on its own. *I* moved the card. The agents "
			"do the work; a person decides it goes to the next stage.\"",
			"",
			"\"The agent that makes changes can only do a very short list of things. It's "
			"deliberately kept on a leash -- that's the answer to 'what if the AI does "
			"something crazy.'\"",
			"",
			"\"And it landed in their real issue tracker. This drops into the workflow "
			"they already have -- not another tool to buy.\"",
			"",
			"_Re-running it:_ there is no inject-fault button any more. Once Implement "
			"fixes the typo, a gateway timer puts it back about 8 minutes later and "
			"clears the activity board with it. If the Drive Torque tile is showing a "
			"real number, the demo is not armed yet.",
		],
	},

	"/drawing": {
		"title": "Drawing Agent",
		"hook": [
			"Ask for a graphic, get a real, editable Ignition graphic -- not a picture.",
		],
		"run": [
			"**Click one of the suggested prompts** to open with -- they are all plant "
			"equipment, so the drawing lands in their world. Or **describe what you "
			"want drawn**: one concrete subject, \"a red recliner chair\", not \"a "
			"detailed factory\".",
			"**Watch it appear** on the canvas beside it. Budget **90-120 seconds** and "
			"keep talking over it.",
			"**Ask for a change** -- colour, position, another element -- \"and it edits "
			"what's already there.\"",
		],
		"say": [
			"\"That's not an image. It's a live Ignition graphic -- you could hook it to a "
			"tag and make it move.\"",
			"",
			"\"Strongest on process shapes and schematics. Keep the request concrete.\"",
			"",
			"**Do not press Cancel.** It does not rescue a slow run -- the agent stays "
			"locked until the original call finishes -- and a half-written drawing puts "
			"the canvas into Component Error that a page reload will not clear. Let a "
			"slow one finish. Asking for something \"detailed\" is what makes them slow.",
		],
	},

	"/security-audit": {
		"title": "Security Audit Agent",
		"hook": [
			"Point an agent at the gateway and ask it who can do what -- users, roles, "
			"page access, and the permissions on the AI agents themselves.",
		],
		"run": [
			"**Click the first suggested prompt** -- \"Run a full gateway security "
			"audit.\" One click sends it.",
			"**Point at a finding's citation.** Every one names the config file it was "
			"read from, so the evidence and the place you'd fix it are the same file.",
			"**Then \"Show me the role to page access matrix\"** -- the answer nobody "
			"can produce by hand.",
			"**Ask \"Are my AI agents secured?\"** -- it audits the AI module itself, "
			"including the MCP server's wildcard permissions.",
			"**Ask it how to fix one.** It answers with the exact change and where to "
			"make it -- and says plainly that it cannot make it for you.",
		],
		"say": [
			"\"The findings are not the model's opinion. They're computed by code -- "
			"deterministic, diffable, the same answer every time. The model picks what "
			"matters, orders it and explains it. That split is the whole design.\"",
			"",
			"\"It separates *declared* from *enforced*. A page can claim a permission in "
			"config and still be open to anyone with the URL -- that's the dangerous "
			"case, and collapsing the two into a tick-box is how you end up with a false "
			"sense of security.\"",
			"",
			"\"It's report-only. Every tool it has is a read. It will tell you exactly what "
			"to change and in which file, but it cannot change anything itself -- an "
			"auditor that can edit what it audits is not an auditor.\"",
			"",
			"_This gateway is deliberately wide open_ -- 9 critical, 45 high, every "
			"Perspective page unprotected. That's staged so there is something to find. "
			"The chat answer is the deliverable; nothing is saved.",
		],
	},

	"/dashboard-agent": {
		"title": "Dashboard Agent",
		"hook": [
			"Describe the dashboard you want. It builds it, pointed at your real tags.",
			"",
			"It draws on the same five-station line as the Alarm Flood demo "
			"(Kitting -> Mixing -> Forming -> Cooking -> Packaging), so a dashboard "
			"built here and a flood triggered there are the same process.",
		],
		"run": [
			"**Press \"Ask the Agent\"** in the header. The chat slides over the page "
			"as a dock rather than sitting beside it, so the widget grid keeps the full "
			"width -- close it and the dashboard is still there, conversation intact.",
			"**Click one of the suggested prompts** in the dock. It calls "
			"`describe_production_line` first, so the tag paths and the live state are "
			"real before it places anything.",
			"**Close the dock and watch** -- a full dashboard takes 2-4 minutes, so start "
			"it talking and keep talking.",
			"**Ask for a change** -- \"add gearbox temperature\", \"make the buffer chart "
			"bigger\". It edits the layout rather than rebuilding it.",
			"**Save it** -- the Save button names the layout and writes it to Postgres. "
			"**Saved** lists everything stored: open one, flag it as a demo, or delete "
			"it. Saving under a new name keeps the original too.",
			"**Better together:** trigger a flood on the Alarm Flood Event page first, "
			"then come back and ask for a dashboard. It sees the fault and builds a "
			"different screen.",
		],
		"prompts": [
			"**Full operations dashboard** -- the reliable crowd-pleaser, 8 widgets:",
			"> Build me a full operations dashboard for the line: how it's running, "
			"where product is piling up, and what alarms fired recently.",
			"",
			"**Shift handover screen** -- the other prompt in the dock:",
			"> Build a shift-handover screen: alarm density over the last 12 hours, "
			"current buffer levels, and a station health comparison so the next "
			"crew knows what they're walking into.",
		],
		"say": [
			"\"It called a tool to read the real line first -- the stations, the units, "
			"the engineering ranges, and how it's running right now. These are live "
			"values, not placeholders.\"",
			"",
			"\"Note what it *chose*. A rate bar next to a buffer bar, because that pair "
			"tells you a backup from a slowdown. Nobody prompted that -- it's in the "
			"widget descriptions the agent reads.\"",
			"",
			"\"And note what it won't do -- it won't reach for a pie chart. You can't "
			"compare angles, and 'where is product piling up' is a comparison question "
			"every time. Six widgets is a good dashboard; eight is the ceiling.\"",
			"",
			"\"Fifteen chart types, all native Perspective components. No image, no "
			"iframe, no third-party charting library.\"",
			"",
			"\"The screen a plant manager asks for on Monday, built while they're "
			"describing it.\"",
			"",
			"*Caveat worth saying:* an unsaved layout lives in the session and is gone "
			"on reload. Press Save and it survives -- and anything not flagged as a "
			"demo dashboard is cleared automatically at the end of the day, which is "
			"what keeps this environment clean between shows.",
		],
	},

	"/": {
		"title": "ICC 2026 Demo Gateway",
		"hook": [
			"One Ignition gateway, several AI demos. Everything you're about to see runs "
			"*inside* Ignition -- no other software, no separate subscription.",
		],
		"run": [
			"**What is an Agent?** -- four clicks of grounding before any of the rest.",
			"**Alarm Flood Agent** -- twenty-seven alarms, one root cause.",
			"**Tag Import Agent** -- weeks of tag mapping, done in a conversation.",
			"**Report Issue Agent** -- an operator's sentence becomes a worked ticket.",
			"**Security Audit** -- who can do what on this gateway, with citations.",
			"**Drawing / Dashboard Agents** -- AI building Ignition screens.",
			"**Translation Manager** -- a finished English screen in Spanish, one click.",
		],
		"say": [
			"\"Pick one or two -- don't run all of them. Alarm Flood and Tag Import land "
			"hardest in a first meeting.\"",
			"",
			"\"The AI is part of the platform they already own. It's not a bolt-on, and "
			"the data never leaves their gateway.\"",
			"",
			"\"Every page has this **i** button with its own two-minute script.\"",
			"",
			"_True on every agent page:_ the chat offers **suggested prompts** on an "
			"empty conversation, and clicking one sends it. They disappear once the "
			"conversation starts -- clear it to get them back.",
		],
	},
}

_FALLBACK = {
	"title": "ICC 2026",
	"hook": ["No presenter notes have been written for this page yet."],
	"run": [],
	"say": [],
}


def _entry(pagePath):
	path = unicode(pagePath or "/").strip()
	if path != "/" and path.endswith("/"):
		path = path.rstrip("/")
	return _PAGES.get(path, _FALLBACK)


def title(pagePath):
	"""Heading for the info dock."""
	return _entry(pagePath)["title"]


def markdown(pagePath):
	"""Full Markdown body for the info dock."""
	e = _entry(pagePath)
	out = ["## %s" % e["title"], ""]

	if e.get("hook"):
		out.extend(e["hook"])
		out.append("")

	if e.get("run"):
		out.append("### Demo it")
		out.append("")
		for i, step in enumerate(e["run"]):
			out.append("%d. %s" % (i + 1, step))
		out.append("")

	# Optional: ready-to-paste prompts, for pages driven by a chat rather than by
	# buttons. Rendered before "What to say" so the presenter can copy one and
	# get it running while they deliver the talking points -- a full dashboard
	# takes a couple of minutes to build.
	if e.get("prompts"):
		out.append("### Prompts to try")
		out.append("")
		out.extend(e["prompts"])
		out.append("")

	if e.get("say"):
		out.append("### What to say")
		out.append("")
		out.extend(e["say"])

	return "\n".join(out)


def knownPages():
	"""Page paths that have notes. Used when checking coverage after adding a page."""
	return sorted(_PAGES.keys())
