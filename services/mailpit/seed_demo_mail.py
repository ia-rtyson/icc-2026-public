#!/usr/bin/env python3
"""Keep a handful of plausible plant-floor emails in the Mailpit sink, so the
Gmail look-alike has something to show before a demo.

Runs as the `mailpit-seed` compose service. Two behaviours worth knowing:

* **It re-seeds, because Mailpit expires mail.** ``MP_MAX_AGE`` is 1h on
  purpose -- it is what stops a day of demo runs piling up fifty alarm
  notifications in the inbox -- but that also takes the scenery with it, so a
  one-shot seeder leaves the inbox empty an hour into the day. This loops.

* **It only re-seeds when the scenery is entirely gone**, never to top it up.
  Injecting four emails while someone is presenting would shove the agent's
  notification down the list mid-sentence. If even one seeded subject is still
  present, this does nothing.

Pure stdlib, so the service can run on a bare ``python:*-alpine`` with no
package install at start -- a conference network is not something to depend on.

    python3 seed_demo_mail.py --url http://mailpit --to iggy@example.com
    python3 seed_demo_mail.py ... --once       # seed and exit, no loop
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

# Subjects double as the "is the scenery still there" probe, so they have to
# stay in step with the messages below.
MESSAGES = [
    {
        "From": {"Email": "noreply@ignition.example.com", "Name": "Ignition Gateway"},
        "Subject": "Alarm: Tank 4 High Temperature",
        "Text": (
            "Tank 4 temperature exceeded 180 F at 09:14:22.\n\n"
            "Priority: High\nState: Active, Unacknowledged\n\n"
            "Acknowledge in the HMI to clear this notification."
        ),
        "HTML": (
            '<div style="font-family:Arial,sans-serif">'
            '<h2 style="color:#c5221f;margin:0 0 8px">High Temperature Alarm</h2>'
            "<p><b>Tank 4</b> temperature exceeded <b>180 F</b> at 09:14:22.</p>"
            '<table cellpadding="6" style="border-collapse:collapse;font-size:14px">'
            '<tr><td style="border:1px solid #ddd">Priority</td>'
            '<td style="border:1px solid #ddd">High</td></tr>'
            '<tr><td style="border:1px solid #ddd">State</td>'
            '<td style="border:1px solid #ddd">Active, Unacknowledged</td></tr></table>'
            "<p>Acknowledge in the HMI to clear this notification.</p></div>"
        ),
    },
    {
        "From": {"Email": "reports@ignition.example.com", "Name": "Production Reporting"},
        "Subject": "Daily production summary - Line 2",
        "Text": (
            "Line 2 produced 14,208 units over 3 shifts with 97.4% OEE. "
            "Downtime: 22 minutes (changeover)."
        ),
        "Tags": ["Reports"],
    },
    {
        "From": {"Email": "maintenance@plantfloor.example", "Name": "Dana Whitfield"},
        "Subject": "Re: PLC firmware window this weekend",
        "Text": (
            "Works for me. I will stage the firmware Friday afternoon so we can "
            "start at 6am Saturday.\n\n- Dana"
        ),
    },
    {
        "From": {"Email": "noreply@ignition.example.com", "Name": "Ignition Gateway"},
        "Subject": "Historian backup completed",
        "Text": "QuestDB backup completed in 4m12s. 8.2 GB written to /backups/questdb/2026-09-09.",
    },
]

SEED_SUBJECTS = {m["Subject"] for m in MESSAGES}


def _call(url, method="GET", payload=None, timeout=10):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    if not body:
        return None
    try:
        return json.loads(body)
    except ValueError:
        # Mailpit answers the mark-read PUT with a bare `ok`, not JSON. Treating
        # that as a failure made a successful seed log an error and skip the
        # mark-unread step, so the scenery arrived already-read.
        return None


def scenery_present(base):
    """True if any seeded subject is still in the mailbox."""
    got = _call("%s/api/v1/messages?limit=200" % base) or {}
    return any(m.get("Subject") in SEED_SUBJECTS for m in got.get("messages", []))


def seed(base, to):
    for msg in MESSAGES:
        body = dict(msg)
        body["To"] = [{"Email": to}]
        _call("%s/api/v1/send" % base, method="POST", payload=body)
        print("  sent: %s" % msg["Subject"], flush=True)

    # Everything starts unread so the inbox looks fresh. Marking only the seeded
    # IDs, not every message -- re-marking an alarm notification the presenter
    # has already opened would be a visible glitch.
    got = _call("%s/api/v1/messages?limit=200" % base) or {}
    ids = [m["ID"] for m in got.get("messages", []) if m.get("Subject") in SEED_SUBJECTS]
    if ids:
        _call("%s/api/v1/messages" % base, method="PUT",
              payload={"IDs": ids, "Read": False})
    print("  %d message(s) marked unread" % len(ids), flush=True)


def wait_for(base, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            _call("%s/api/v1/info" % base, timeout=5)
            return True
        except Exception:
            time.sleep(2)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("MAILPIT_URL", "http://mailpit"))
    ap.add_argument("--to", default=os.environ.get("GMAIL_ACCOUNT", "iggy@example.com"))
    ap.add_argument("--interval", type=int,
                    default=int(os.environ.get("SEED_INTERVAL_SECS", "600")))
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    base = args.url.rstrip("/")
    if not wait_for(base):
        sys.exit("mailpit-seed: %s never answered" % base)

    while True:
        try:
            if scenery_present(base):
                print("mailpit-seed: scenery still present, nothing to do", flush=True)
            else:
                print("mailpit-seed: seeding demo mail for %s" % args.to, flush=True)
                seed(base, args.to)
        except Exception as exc:                      # noqa: BLE001 - keep looping
            print("mailpit-seed: %s" % exc, flush=True)
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
