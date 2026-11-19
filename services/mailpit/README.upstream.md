# Mailpit
A local SMTP server with a UI for viewing sent emails

URL: http://localhost:8025
Gmail look-alike UI: http://localhost:8090

Source: [Github](https://github.com/axllent/mailpit)

## Configuration

Connect to the smtp server using the hostname `mailpit` and port 1025

## Gmail look-alike UI (for demos)

The `gmail` service is a static front end over the **same mailbox**, styled to look
like Gmail — for demoing "an email arrives" to an audience that expects Gmail.
Mailpit's own UI is not themeable, so this is a separate page that reads Mailpit's
REST API; nginx proxies `/api/` and `/view/` to the mailpit container so
everything is one origin.

Mail sent to port 1025 shows up in both UIs. New mail lands in the list live over
Mailpit's websocket event feed, highlighted for a second the way Gmail does it.

### What is real vs. faked

| Real Mailpit operations | Local-only (localStorage) | Cosmetic only |
| --- | --- | --- |
| receiving mail, live arrival | star | Snoozed, Drafts, Spam |
| read / unread | archive | Primary/Promotions/Social tabs |
| search (`/api/v1/search`, so `tag:`, `from:` etc. work) | Delete → local Trash | help/settings/apps buttons |
| Compose → Send (`/api/v1/send`) | | storage + "last account activity" footer (real numbers from `/api/v1/info`) |
| Trash → "Empty Trash now" (really deletes) | | |

Delete is deliberately non-destructive: it moves the message to a local Trash so a
demo cannot lose the mailbox. "Empty Trash now" is what actually deletes from
Mailpit. Stars/archive/trash live in the browser, so they are per-browser and are
cleared with the site's local storage.

Mailpit tags appear as Gmail labels in the left rail; clicking one searches
`tag:"<name>"`.

### Account identity

The account the UI presents as (avatar, "to me", the Sent folder) comes from env
vars on the `gmail` service, defaulting to `iggy@example.com`:

```sh
GMAIL_ACCOUNT=operator@plant.example GMAIL_NAME="Plant Operator" docker compose up -d
```

Mail *from* that address is filed under Sent instead of Inbox, so send demo mail
from some other address.

### Seeding a demo mailbox

```sh
bash gmail/seed-demo-mail.sh                       # four plant-floor emails, all unread
bash gmail/seed-demo-mail.sh someone@example.com   # to a different account
```

Mailpit keeps its database in the container's `/tmp` (no volume), so recreating
the container gives you an empty mailbox.

### Phone / tablet layout

The same URL is responsive - there is no separate mobile site to open:

| Width | Layout |
| --- | --- |
| > 1000px | full Gmail desktop: 256px nav, list card, side panel rail |
| 701-1000px | nav auto-collapses to Gmail's icon rail |
| <= 700px | Gmail **app** look |

On a phone it becomes the Gmail app UI: floating rounded search bar with the
hamburger and avatar in it, three-line rows with a coloured sender avatar (date
top-right, star bottom-right), the nav as an off-canvas drawer behind a scrim, a
light-blue extended **Compose** FAB bottom-right, full-screen compose, and a
reading view with a pinned Reply / Reply all / Forward bar. HTML mail that is
wider than the screen is scaled to fit, the way Gmail does it.

For a demo on a laptop, Chrome/Edge DevTools device toolbar (Ctrl+Shift+M) at any
phone preset shows the mobile layout; the breakpoint is plain CSS width, so
resizing the window works too.

### Shortcuts and URLs

`c` compose · `/` search · `u`/`Esc` back to the list · `e` archive · `r` reply ·
`Ctrl+Enter` send (desktop; the phone layout is touch-only). URLs mirror Gmail's: `#inbox`, `#inbox/<message-id>`,
`#starred`, `#sent`, `#trash`.

### Files

```
gmail/templates/default.conf.template   nginx: static assets + proxy to mailpit
gmail/html/{index.html,styles.css,app.js}
gmail/seed-demo-mail.sh
```

The html directory is bind-mounted, so edits show up on reload — no rebuild.
