#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate the Home landing page's demo cards inline in Home/view.json.

Why inline, and not `ia.display.view` + `Shared/Demo Card`
----------------------------------------------------------
That is how this page was originally built, and it is why the cards took a
visible beat to populate: every one of the card's four interesting props was
bound to `view.params.*` inside the embedded view --

    props.text  <- property  view.params.title
    props.text  <- property  view.params.description
    props.path  <- expr      'material/' + {view.params.icon}
    props.style <- expr-struct  {'--card-accent': {view.params.accent}}

`ia.display.view` mounts fast; a binding sourced from `view.params.*` inside it
does not. Measured on this gateway when the suggestion chips had the same shape:
a static literal rendered in **39 ms**, the identical prop driven by a
`view.params.*` property binding took **2918 ms** -- and the latency is roughly
fixed rather than per-instance, so 13 cards cost about what 4 did. The cards were
therefore already in the DOM within ~100 ms showing `Shared/Demo Card`'s *seed*
params ("Demo", "What this demo shows.", a grey dashboard icon), and only the
real values were seconds late. That is exactly the reported symptom.

See CLAUDE.md, "Prompt chips are generated inline", for the full measurement --
this is the same fix applied to the same pathology.

So CARDS below is the single declaration, and this script emits one plain flex container per card
with **static** props into `CardGrid`. Add a demo by adding an entry
here and re-running; then rescan the gateway.

Notes for the next person:
  * `--card-accent` is a *static* string in `props.style`. Perspective passes a
    custom property in `props.style` through to the container's inline style, and
    it inherits into the badge tint and the hover border. A *binding* whose
    propConfig key contains `--` never evaluates -- but a static value is fine,
    and static is all this needs.
  * The card's 324x180 used to come from `Shared/Demo Card`'s `defaultSize`.
    Inline cards have no such thing, so it lives in `.psc-exchange\\/demo\\/demo-card` in the
    project stylesheet instead. Change it there, not here.
  * `events.dom.onClick` on an `ia.container.flex` works at **gateway** scope
    ("scope": "G"), which is what the left nav and the old card both used. It is
    *client* scope that silently never fires on a flex container.

Usage:
    python scripts/gen_home_cards.py            # rewrite Home/view.json
    python scripts/gen_home_cards.py --check    # exit 1 if the file is stale
"""

import argparse
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIEW = os.path.join(ROOT, "ignition", "projects", "icc-2026",
                    "com.inductiveautomation.perspective", "views",
                    "Exchange", "Demo", "Home", "view.json")

# The container this script owns. Everything else in the view is left alone.
GRID = "CardGrid"


# --------------------------------------------------------------------------
# The cards. This table is the whole maintenance story.
#
# Order is presentation order: the grounding demo first, then the demos that
# land hardest in a first meeting, then the rest. Keep it in step with
# page-config/config.json and exchange.demo.pageInfo._PAGES -- `--check` verifies the first
# two, not the third.
#
# icon must exist in the gateway's bundled Material set; check with
#   curl -s http://localhost:8088/data/perspective/icons/material.svg | grep id=\"name\"
# An icon that is not there renders as an unresolved-icon overlay that also
# eats the click.
# --------------------------------------------------------------------------

CARDS = [
    {
        "title": "What is an Agent?",
        "description": "A four-click explainer: the agent, then its system "
                       "prompt, its tools and its model connection, built up "
                       "one part at a time.",
        "icon": "person",
        "accent": "#3987E5",
        "navTo": "/what-is-an-agent",
    },
    {
        "title": "Alarm Flood Agent",
        "description": "Break a packaging line and watch the cascade walk "
                       "upstream, then ask the agent to reconstruct the root "
                       "cause from tag history.",
        "icon": "alarm",
        "accent": "#ff4d4f",
        "navTo": "/alarm-flood-event",
    },
    {
        "title": "Report Issue Agent",
        "description": "Operators describe a problem in plain language; the "
                       "agent triages it. Pipeline status slides out over the "
                       "same page.",
        "icon": "bug_report",
        "accent": "#ffa940",
        "navTo": "/report-issue",
    },
    {
        "title": "Tag Import Agent",
        "description": "The agent reads a Studio 5000 controller export hosted "
                       "here, proposes a UDT structure, and builds all 117 tags "
                       "when you tell it to.",
        "icon": "account_tree",
        "accent": "#40a9ff",
        "navTo": "/tag-import",
    },
    {
        "title": "Security Audit",
        "description": "End-to-end gateway security audit with deterministic "
                       "findings, cited sources and recommended fixes.",
        "icon": "lock",
        "accent": "#73d13d",
        "navTo": "/security-audit",
    },
    {
        "title": "Dashboard Agent",
        "description": "Describe the dashboard you want and the agent builds "
                       "it from the live production line, widget by widget.",
        "icon": "dashboard",
        "accent": "#36cfc9",
        "navTo": "/dashboard-agent",
    },
    {
        "title": "Drawing Agent",
        "description": "Ask for a graphic and get a real, editable Ignition "
                       "SVG -- not a picture of one.",
        "icon": "edit",
        "accent": "#b37feb",
        "navTo": "/drawing",
    },
    {
        "title": "Translation Manager",
        "description": "Register every hardcoded label on a finished screen, "
                       "then let the agent reach the text a literal scan cannot "
                       "see.",
        "icon": "translate",
        "accent": "#9254de",
        "navTo": "/translation-manager",
    },
    {
        "title": "Designer Embeds",
        "description": "A filtered event log -- filter panel, named query and "
                       "paged table -- built by the AI inside the Designer.",
        "icon": "table_chart",
        "accent": "#8c8c8c",
        "navTo": "/designer-embeds-example",
    },
]


# --------------------------------------------------------------------------
# Emitters
# --------------------------------------------------------------------------

def node_name(card):
    """A stable, unique component name derived from the nav target."""
    words = re.split(r"[^a-z0-9]+", card["navTo"].strip("/").lower())
    return "".join(w.capitalize() for w in words if w) + "Card" if any(words) else "HomeCard"


def card_node(card):
    return {
        "type": "ia.container.flex",
        "meta": {"name": node_name(card)},
        # basis auto + no grow/shrink: the 324x180 comes from the exchange/demo/demo-card class.
        "position": {"basis": "auto", "grow": 0, "shrink": 0},
        "props": {
            "direction": "column",
            "style": {
                "classes": "exchange/demo/demo-card",
                "--card-accent": card["accent"],
            },
        },
        "events": {
            "dom": {
                "onClick": {
                    "config": {
                        "script": "\tsystem.perspective.navigate(%s)"
                                  % json.dumps(card["navTo"]),
                    },
                    "scope": "G",
                    "type": "script",
                },
            },
        },
        "children": [
            {
                "type": "ia.container.flex",
                "meta": {"name": "IconBadge"},
                "position": {"basis": "44px", "shrink": 0},
                "props": {
                    "alignItems": "center",
                    "justify": "center",
                    "style": {"classes": "exchange/demo/demo-card-badge"},
                },
                "children": [
                    {
                        "type": "ia.display.icon",
                        "meta": {"name": "Icon"},
                        "position": {"basis": "24px", "shrink": 0},
                        "props": {
                            "path": "material/%s" % card["icon"],
                            "style": {"classes": "exchange/demo/demo-card-icon"},
                        },
                    },
                ],
            },
            {
                "type": "ia.display.label",
                "meta": {"name": "Title"},
                "position": {"basis": "26px", "shrink": 0},
                "props": {
                    "text": card["title"],
                    "style": {"classes": "exchange/demo/demo-card-title"},
                },
            },
            {
                "type": "ia.display.label",
                "meta": {"name": "Description"},
                "position": {"grow": 1},
                "props": {
                    "text": card["description"],
                    "style": {"classes": "exchange/demo/demo-card-desc"},
                },
            },
        ],
    }


def grid_node():
    return {
        "type": "ia.container.flex",
        "meta": {"name": GRID},
        "position": {"grow": 1},
        "props": {
            "direction": "row",
            "wrap": "wrap",
            "justify": "center",
            # flex-start, or a short card in a row gets stretched to the
            # tallest one in it.
            "alignItems": "flex-start",
            "style": {
                "classes": "exchange/demo/home-grid",
                "gap": "20px",
                "padding": "10px",
            },
        },
        "children": [card_node(c) for c in CARDS],
    }


# --------------------------------------------------------------------------

def find_parent_of(node, name):
    for i, child in enumerate(node.get("children") or []):
        if (child.get("meta") or {}).get("name") == name:
            return node, i
        hit = find_parent_of(child, name)
        if hit:
            return hit
    return None


def render(view):
    hit = find_parent_of(view["root"], GRID)
    if not hit:
        raise SystemExit("gen_home_cards: no %r container in %s" % (GRID, VIEW))
    parent, index = hit
    parent["children"][index] = grid_node()
    # 2-space indent, sorted keys, CRLF, no trailing newline -- matching what is
    # already on disk so the diff stays scoped to the cards.
    text = json.dumps(view, indent=2, sort_keys=True, ensure_ascii=False)
    return text.replace("\n", "\r\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if Home/view.json is out of date")
    args = ap.parse_args()

    current = io.open(VIEW, encoding="utf-8", newline="").read()
    view = json.loads(current)
    wanted = render(view)

    if args.check:
        if current != wanted:
            sys.stderr.write("gen_home_cards: Home/view.json is stale -- "
                             "re-run scripts/gen_home_cards.py\n")
            return 1
        sys.stdout.write("gen_home_cards: up to date (%d cards)\n" % len(CARDS))
        return 0

    if current == wanted:
        sys.stdout.write("gen_home_cards: no change (%d cards)\n" % len(CARDS))
        return 0

    io.open(VIEW, "w", encoding="utf-8", newline="").write(wanted)
    sys.stdout.write("gen_home_cards: wrote %d cards to Home/view.json\n"
                     % len(CARDS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
