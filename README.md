# AI ICC 2026

A demo environment for **ICC 2026** (Ignition Community Conference, September
2026), showcasing the new **Catalyst** (AI) modules in Ignition 2027 — a
gateway-hosted LLM chat agent framework with a tool-calling surface, and MCP
client connections that let those agents call external tools (here, YouTrack).

Everything here is deliberately **self-contained**: clone the repo, run one
command, and the whole stack — gateway, database, issue tracker, mail sink —
comes up already seeded with a working demo. No manual setup, no wizards, no
"first run this script by hand." See [Quick start](#quick-start) below.

> ⚠️ **Ignition version note.** The stack runs the public
> `inductiveautomation/ignition:2027.2.0-beta2` image, pinned in
> `docker-compose.yml`. It ships the Catalyst Core and Catalyst Agent modules
> the demos need, so there is nothing to build.

## What's in the demo

One Ignition project (`icc-2026`), reached through a card-grid landing page at
`/`. Each card is a self-contained AI demo built around the same simulated
five-station coffee-roasting line:

| Page | What it shows |
|---|---|
| **Alarm Flood Event** (`/alarm-flood-event`) | Trigger a cascading alarm flood on a live process simulator; an AI agent (with trend-chart and tag-history tools) investigates the alarm journal and writes a root-cause report |
| **Security Audit** (`/security-audit`) | An agent audits the gateway's own users, roles, security levels, page permissions and AI/MCP surface, then reports findings with recommended fixes (report-only; it changes nothing) |
| **Tag Import Agent** (`/tag-import`) | An agent reads a real-looking Rockwell/Studio 5000 controller export and proposes a UDT/tag structure, reviewed as a tree and created on approval |
| **Report Issue Agent** (`/report-issue`) | An operator describes a problem in chat; the agent files a YouTrack ticket, and a webhook-driven pipeline (Validate → Implement) fixes the underlying config and comments back |
| **Dashboard Agent** (`/dashboard-agent`) | An agent builds a live operations dashboard out of 18 chart widgets from a natural-language request |
| **Drawing Tool with Agent** (`/drawing`) | An agent draws requested equipment as an SVG on a live canvas |
| **Translation Manager** (`/translation-manager`) | Scans a page's text and translates it in place via the AI module, shallow (literal) or deep (binding-aware) |
| **What is an Agent?** (`/what-is-an-agent`) | A one-screen explainer showing "an agent" as its three real parts — model, system prompt, tools — using this stack's own Alarm Notification Agent as the worked example |
| **Designer Assist formatting demo** (Designer: `Exchange/Designer Assist/Formatting Demo`) | A deliberately badly laid-out Line Status Board (25 live station cards in a flex-repeater) that Component Assist is asked to fix in the Designer. Target layout: `Exchange/Designer Assist/Formatting Demo Fixed` |
| **Designer Embeds Example** (`/designer-embeds-example`) | A conventional (non-AI) Perspective view + named query, for contrast |
| **DB Wrecker** (`/db-wrecker`) | Deliberately expensive queries, for exercising Gateway diagnostics |

## Quick start

```bash
git clone <this-repo>
cd icc-2026-public
docker compose up -d
```

That's it. This single command:

- starts the **Ignition gateway** with the Catalyst modules, pre-configured
  with an LLM provider (no API key, see below), the YouTrack MCP connection,
  and every project resource for the demos above
- starts **Postgres** and applies every migration in `sql/` (safe to replay,
  every migration checks before it seeds)
- restores a fully-provisioned **YouTrack** instance (project, board, API
  token already wired into the gateway) from a baked snapshot
- starts **Mailpit** as an SMTP sink for the gateway's alarm-notification
  emails, fronted by a Gmail-look-alike inbox so "sent" mail is visible
- starts **pgAdmin** for poking at the database

No file needs to be edited and no script needs to be run by hand for any of
this — see [Zero-config bring-up](#zero-config-bring-up-what-makes-this-work)
below for what specifically makes that true.

The gateway comes up on a **2-hour trial license**, which is enough to see
everything working. For a longer-lived license:

```bash
cp .env.example .env
# fill in IGNITION_LICENSE_KEY and IGNITION_ACTIVATION_TOKEN
docker compose up -d ignition   # a license env var needs the container recreated
```

### Add your model API key

**The AI demos will not work until you add an API key.** The gateway ships with
one model provider already configured, named **Anthropic**, but its API key is
deliberately blank. Until a key is in place, every agent fails with an
authentication error (the gateway log says `No API key configured`). Everything
that is not AI (the process simulator, the line mimic, the
non-AI pages, YouTrack, the inbox) works without one.

To add it: in the gateway's web configuration, open the AI model providers,
edit **Anthropic**, paste your Anthropic API key and save.

**Using a different provider (OpenAI, OpenRouter, a local model, …) is more
than swapping the key.** Every agent names its provider *and* a model ID, and
those IDs are Anthropic's (`claude-opus-5-5`, `claude-sonnet-5-5`,
`claude-haiku-5-5`). Add your provider alongside Anthropic, then change the
provider and model on each of these:

| Where | What points at Anthropic |
|---|---|
| Each AI agent (10): Alarm Flood, Alarm Notification, Dashboard, Drawing, Implement, Report Issue, Security Audit, Tag Import, Translation Manager, Validate | the agent's model (`claude-opus-5-5`) |
| Gateway AI settings | the default model (`claude-sonnet-5-5`) and both Diagnostic Digest models (`claude-haiku-5-5`) |

In the repo these are `ignition/config/resources/core/com.inductiveautomation.catalyst.agent/agent/<name>/config.json`
(`model.providerName` / `model.modelId`) and
`ignition/config/resources/core/com.inductiveautomation.catalyst.core/ai-settings/config.json`.
Edit them in the gateway UI, or edit the files and run a config scan. The demos
were built and tuned against Claude, so expect another model to behave
differently, especially on the long multi-tool demos (Alarm Flood, Tag Import,
Dashboard).


### The Validate and Implement agents (YouTrack webhook)

The Report Issue demo's second half runs when someone moves a ticket on the
YouTrack board. A YouTrack workflow, `ignition-stage-hook`, posts the move to
the gateway, and the gateway runs the Validate or Implement agent. The workflow
sends it to:

```
http://ignition:8088/system/webdev/icc-2026/exchange/issue-report/issue-stage
```

`ignition` is the gateway's service name in `docker-compose.yml`, which
resolves inside the stack's Docker network under any project name, so this
works as shipped. **Update it if YouTrack cannot reach the gateway at that
address**: if you rename the `ignition` service, run YouTrack outside this
compose stack, or put the gateway on another host. Do not use a host IP or
`localhost`. A host IP times out from inside the YouTrack container, and
`localhost` is the YouTrack container itself.

To change it:

1. Edit `ENDPOINT` in `scripts/youtrack-workflow/ignition-stage-hook.js`.
2. Rebuild `scripts/youtrack-workflow/ignition-stage-hook.zip` with the edited
   file (the zip holds `package.json` and `ignition-stage-hook.js`).
3. In YouTrack, go to **Administration -> Workflows** and import the zip over
   the existing `ignition-stage-hook` workflow.

If the address is wrong, moving a card to Validate or Implement does nothing
and nothing is logged in the gateway. Two related points:

* The baked YouTrack seed is only restored into **empty** volumes. A YouTrack
  that already has data keeps whatever workflow it has, so import the zip there
  too.
* Both agents also need the model API key (see above). Without it the gateway
  logs `No API key configured` when a card moves.

### Where things are

| Service | URL | Login |
|---|---|---|
| Ignition Gateway | http://localhost:8088 | `admin` / `password` |
| pgAdmin | http://localhost:5051/browser/ | `pgadmin4@pgadmin.org` / `admin` |
| YouTrack | http://localhost:8089 | admin account baked into the seed |
| Gmail-look-alike inbox | http://localhost:8090 | — (renders the Mailpit sink) |
| Mailpit's own UI | http://localhost:8025 | — |
| Postgres | `localhost:5433` | `admin` / `password`, db `postgres` |

Start in the gateway at `/` — the card grid is the front door to every demo.

### Troubleshooting

- **`git status` shows changes under `ignition/config` right after the first
  `up`** — on a brand-new gateway volume, Ignition's first-boot commissioning
  writes a `temp` identity provider and user source and rewrites
  `security-properties` (Administrator-only gateway API, classic Designer
  login). The demo pages still work. To put the shipped security settings back,
  run `git checkout -- ignition/config/resources/core/ignition/security-properties`,
  delete the two `temp` folders, then run **Config → Scan** in the gateway as
  `admin`.
- **Moving a YouTrack card to Validate or Implement does nothing** — the
  workflow cannot reach the gateway; see *The Validate and Implement agents*.
- **Every agent answers with an authentication error** — the Anthropic model
  provider has no API key yet; see *Add your model API key*.
- **A demo page looks stale after a while** — several demos (Alarm Flood's
  binding-fault, the ticket pipeline's activity log, YouTrack's ticket board)
  re-arm or purge themselves on a timer so the stack stays demo-ready without
  a human resetting anything; give it a few minutes.
- **Something looks broken after changing a `.env` value** — most env vars
  are read once at container start; recreate the affected service with
  `docker compose up -d <service>` rather than just reloading a page.

## Zero-config bring-up: what makes this work

A from-scratch `git clone && docker compose up -d` produces a working demo
because every piece of state a human would otherwise have to create by hand
travels with the repo instead:

| Would normally need a human | Instead |
|---|---|
| Postgres schema + demo data | `postgres-init` (a one-shot service) replays every file in `sql/` on every `docker compose up`, not just on first volume creation — every migration is idempotent and every seed is guarded so it never clobbers live demo data |
| A YouTrack instance, project, custom field, board, API token | `youtrack-init` restores a baked snapshot (`services/youtrack/seed/`) into empty volumes before YouTrack ever starts, so it comes up already provisioned |
| The gateway's YouTrack credential | The same seed ships `token.env`, loaded into the gateway container automatically |
| MCP auth to YouTrack | Committed inside `ignition/config`; it is the disposable seed's token |
| Scenery in the demo inbox | `services/mailpit/seed_demo_mail.py` (currently disabled by default in `docker-compose.yml` — flip it back on if you want a populated inbox out of the box) |

The one thing that does not travel is the LLM API key; see
*Add your model API key*.

## Repo layout

```
docker-compose.yml       # ignition + postgres + pgadmin + youtrack + mailpit/gmail
ignition/
  config/                 # gateway config: AI provider, MCP connection, security, themes, tags
  projects/icc-2026/      # the one Ignition project — Perspective views, scripts, named queries, AI agent tools
reference/line1/          # generated Rockwell/Studio 5000 export the Tag Import demo reads
scripts/                  # generators for views/stylesheets (idempotent, most support --check) + demo-data tooling
services/
  youtrack/                # baked YouTrack snapshot + restore script
  mailpit/                 # Gmail-look-alike inbox + demo mail seeder
sql/                       # Postgres migrations, replayed on every `docker compose up`
```

## Credentials in this repo

Every credential committed here is a local demo credential: the gateway,
Postgres, pgAdmin and OPC UA logins listed above, the fictional Security Audit
accounts, and the baked YouTrack admin account and API token. They only work
against the containers this stack starts. Change them before exposing the
stack on a network.

## Third-party content

See [`THIRD-PARTY-NOTICES.md`](./THIRD-PARTY-NOTICES.md).

---

_Inductive Automation — ICC 2026 AI demos._
