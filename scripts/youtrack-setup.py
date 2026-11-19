#!/usr/bin/env python3
"""Provision the YouTrack side of the Submitted -> Validate -> Implement -> Completed pipeline.

Idempotent: safe to re-run. Creates, if missing:

* project **Ignition Issues** (key ``UI``)
* enum custom field **Stage** with values ``Submitted``, ``Validate``, ``Implement``, ``Completed`` --
  this is the field the board columns are built from, so moving a card between
  columns is just a ``Stage`` change, which is what the webhook fires on
* string custom fields **View Path** and **Component Path** -- the Ignition
  coordinates the Validate and Implement agents need to find the resource
* agile board **Ignition Issues** with one column per ``Stage`` value

Usage:
    python scripts/youtrack-setup.py                 # uses .env
    python scripts/youtrack-setup.py --token perm-…  # explicit

Reads YOUTRACK_TOKEN / YOUTRACK_PORT from .env next to docker-compose.yml.
The token needs both the Hub ("YouTrack Administration") and YouTrack scopes;
mint one with --mint-token if you don't have one yet.
"""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request

PROJECT_NAME = "Ignition Issues"
PROJECT_KEY = "UI"
BOARD_NAME = "Ignition Issues"
STAGE_FIELD = "Stage"
STAGES = ["Submitted", "Validate", "Implement", "Completed"]
TEXT_FIELDS = ["View Path", "Component Path"]

HUB_SERVICE_ID = "0-0-0-0-0"


def env_from_dotenv(path):
    out = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


class YouTrack:
    def __init__(self, base, token=None, basic=None):
        self.base = base.rstrip("/")
        self.token = token
        self.basic = basic

    def _call(self, method, path, body=None):
        url = self.base + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        elif self.basic:
            req.add_header("Authorization", "Basic " + base64.b64encode(
                self.basic.encode()).decode())
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw.strip() else None
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()[:600]
            raise SystemExit("%s %s -> HTTP %s\n%s" % (method, path, exc.code, detail))

    get = lambda self, p: self._call("GET", p)                      # noqa: E731
    post = lambda self, p, b: self._call("POST", p, b)              # noqa: E731


def mint_token(base, credentials):
    """Create a permanent token scoped to Hub + YouTrack, using admin credentials."""
    yt = YouTrack(base, basic=credentials)
    me = yt.get("/hub/api/rest/users/me?fields=id,login")
    services = yt.get("/hub/api/rest/services?fields=id,applicationName&$top=50")
    yt_svc = [s["id"] for s in services["services"] if s["applicationName"] == "YouTrack"]
    scope = [{"id": HUB_SERVICE_ID}] + [{"id": s} for s in yt_svc]
    created = yt.post(
        "/hub/api/rest/users/%s/permanenttokens?fields=id,name,token" % me["id"],
        {"name": "ignition-mcp", "scope": scope})
    return created["token"]


def ensure_project(yt):
    existing = yt.get("/api/admin/projects?fields=id,name,shortName&$top=200") or []
    for p in existing:
        if p.get("shortName") == PROJECT_KEY:
            print("project %s already exists (%s)" % (PROJECT_KEY, p["id"]))
            return p["id"]
    me = yt.get("/api/users/me?fields=id")
    created = yt.post("/api/admin/projects?fields=id,name,shortName", {
        "name": PROJECT_NAME,
        "shortName": PROJECT_KEY,
        "leader": {"id": me["id"]},
        "description": "UI defects reported from Perspective by the Report Issue Agent. "
                       "Stage drives the board columns and each column change fires a "
                       "webhook back into Ignition.",
    })
    print("created project %s (%s)" % (PROJECT_KEY, created["id"]))
    return created["id"]


def _find_field_prototype(yt, name):
    fields = yt.get(
        "/api/admin/customFieldSettings/customFields"
        "?fields=id,name,fieldType(id)&$top=300") or []
    for f in fields:
        if f.get("name") == name:
            return f
    return None


def ensure_enum_field(yt, project_id, name, values):
    proto = _find_field_prototype(yt, name)
    if proto is None:
        bundle = yt.post(
            "/api/admin/customFieldSettings/bundles/enum?fields=id,name",
            {"name": name + " values",
             "values": [{"name": v} for v in values]})
        proto = yt.post(
            "/api/admin/customFieldSettings/customFields?fields=id,name",
            {"name": name,
             "fieldType": {"id": "enum[1]"},
             "isDisplayedInIssueList": True,
             "fieldDefaults": {"$type": "EnumBundleCustomFieldDefaults",
                               "bundle": {"id": bundle["id"]}}})
        print("created enum field '%s' with %s" % (name, ", ".join(values)))
    else:
        print("enum field '%s' already exists" % name)
    return _attach(yt, project_id, proto, "EnumProjectCustomField")


def ensure_text_field(yt, project_id, name):
    proto = _find_field_prototype(yt, name)
    if proto is None:
        proto = yt.post(
            "/api/admin/customFieldSettings/customFields?fields=id,name",
            {"name": name,
             "fieldType": {"id": "string"},
             "isDisplayedInIssueList": False})
        print("created string field '%s'" % name)
    else:
        print("string field '%s' already exists" % name)
    return _attach(yt, project_id, proto, "SimpleProjectCustomField")


def _attach(yt, project_id, proto, type_name):
    attached = yt.get(
        "/api/admin/projects/%s/customFields?fields=id,field(id,name)&$top=200"
        % project_id) or []
    for a in attached:
        if (a.get("field") or {}).get("id") == proto["id"]:
            return a["id"]
    created = yt.post(
        "/api/admin/projects/%s/customFields?fields=id,field(id,name)" % project_id,
        {"$type": type_name, "field": {"id": proto["id"]}, "canBeEmpty": True})
    print("  attached '%s' to %s" % (proto["name"], PROJECT_KEY))
    return created["id"]


def _enable_default_sprint(yt, board_id):
    """Point the board at a default sprint so new issues land on it automatically.

    Counterintuitive but load-bearing: an issue created in the board's project is
    NOT on the board. Membership is explicit -- something has to add it to a
    sprint. Setting a *default* sprint makes YouTrack do that on creation, which
    is what keeps the agent's create_issue call a single call.

    Note this requires sprints to be ENABLED. A board with
    ``disableSprints: true`` rejects a default sprint outright ("Board can't have
    sprints") and then silently never shows a card -- the failure mode this
    function exists to prevent.
    """
    board = yt.get("/api/agiles/%s?fields=id,currentSprint(id,name),sprints(id,name)" % board_id)
    sprint = board.get("currentSprint") or (board.get("sprints") or [None])[0]
    if not sprint:
        print("  WARNING: board has no sprint; cards will not appear automatically")
        return
    yt.post("/api/agiles/%s?fields=sprintsSettings(disableSprints,defaultSprint(name))" % board_id,
            {"sprintsSettings": {"disableSprints": False,
                                 "defaultSprint": {"id": sprint["id"], "$type": "Sprint"}}})
    print("  default sprint set to '%s' -- new issues join the board on creation"
          % sprint.get("name"))


def ensure_board(yt, project_id):
    boards = yt.get("/api/agiles?fields=id,name&$top=200") or []
    for b in boards:
        if b.get("name") == BOARD_NAME:
            print("board '%s' already exists (%s)" % (BOARD_NAME, b["id"]))
            return b["id"]
    stage = _find_field_prototype(yt, STAGE_FIELD)
    if stage is None:
        raise SystemExit("'%s' field not found; cannot build the board." % STAGE_FIELD)
    # Build from the kanban template -- it wires up a board that actually renders.
    # The template defaults its columns to State, so repoint them at Stage after.
    created = yt.post("/api/agiles?template=kanban&fields=id,name", {
        "name": BOARD_NAME,
        "projects": [{"id": project_id}],
    })
    yt.post("/api/agiles/%s?fields=id,columnSettings(field(name))" % created["id"],
            {"columnSettings": {"field": {"id": stage["id"], "name": STAGE_FIELD}}})
    _enable_default_sprint(yt, created["id"])
    print("created board '%s' (%s) with columns from '%s'"
          % (BOARD_NAME, created["id"], STAGE_FIELD))
    return created["id"]


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = env_from_dotenv(os.path.join(here, ".env"))

    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:%s" % env.get("YOUTRACK_PORT", "8089"))
    ap.add_argument("--token", default=env.get("YOUTRACK_TOKEN") or None)
    ap.add_argument("--mint-token", metavar="USER:PASS",
                    help="Mint a permanent token with these admin credentials and exit.")
    args = ap.parse_args()

    if args.mint_token:
        print(mint_token(args.base, args.mint_token))
        return

    if not args.token:
        sys.exit("No token. Set YOUTRACK_TOKEN in .env, pass --token, "
                 "or mint one with --mint-token admin:admin")

    yt = YouTrack(args.base, token=args.token)
    project_id = ensure_project(yt)
    ensure_enum_field(yt, project_id, STAGE_FIELD, STAGES)
    for name in TEXT_FIELDS:
        ensure_text_field(yt, project_id, name)
    ensure_board(yt, project_id)
    print("\nDone. Board: %s/agiles" % args.base.rstrip("/"))


if __name__ == "__main__":
    main()
