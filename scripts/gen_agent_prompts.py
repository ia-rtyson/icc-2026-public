# -*- coding: utf-8 -*-
"""Declare every `ia.ai.chat` component's suggested prompts and agent icon.

This replaces `scripts/gen_suggestion_chips.py` (deleted). The chips it
generated -- a pill-shaped flex row per prompt, under the chat, each with a
`copy-to-clipboard` iframe beside the label -- existed for exactly one reason:
`ia.ai.chat` used to expose no way to put text into its input box, so a chip
could not type-and-enter. Clicking one copied the prompt and the user pasted it
into the chat by hand.

The component now carries the feature itself:

    "suggestedPrompts": ["...", "..."]   # offered on the empty conversation;
                                         # clicking one SENDS it
    "agentIcon": "material/alarm"        # shown beside the agent's replies

So the whole chip apparatus is gone -- the markup, the `*.suggest` page
messages, the `autoPrompt`/`nonce` remount dance that tried to make the agent
answer a chip, and the `copy-to-clipboard` WebDev endpoint. What is left is this
table.

`agentIcon` is the same icon the left nav and the Home card use for that demo
(`views/Exchange/.../Navigation/LeftNavigation` and `scripts/gen_home_cards.py`),
so an agent looks the same wherever it appears. Keep the three in step.

Note a prompt string is both the label and the message: clicking it sends that
exact text. So no numbering prefixes -- "1. Propose a structure" would put the
"1." into the conversation. Order in this list is the demo script.

Usage:  python scripts/gen_agent_prompts.py [--check]

`--check` regenerates in memory and exits 1 if anything on disk is stale, so the
views cannot silently drift from this file. Re-run it after editing PAGES, then
rescan the gateway.
"""

import argparse
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIEWS = os.path.join(ROOT, "ignition", "projects", "icc-2026",
                     "com.inductiveautomation.perspective", "views")

# The chip row this script removes on sight, wherever it still exists.
CHIP_CONTAINER = "Suggestions"

# Views that carried a chip row for a chat embedded from *another* view, so they
# appear nowhere in PAGES and would otherwise keep their chips forever. Empty
# since 2026-09-30: the two embedded panels (`Exchange/Alarm Flood Agent/Agent Panel`,
# `Exchange/Security Agent/Chat Panel`) each wrapped a single ia.ai.chat and were inlined
# into their hosts, which are now PAGES entries in their own right. A host listed
# here AND in PAGES would be rewritten twice, so keep them out of this list.
CHIP_HOSTS = []


# --------------------------------------------------------------------------
# One entry per ia.ai.chat in the project. Editing this table is the whole
# maintenance story: change a prompt here, re-run, rescan.
#
#   view      - the view holding the chat (NOT always the page: some of these
#               chats sit in a dock or an embedded view, and the prompts have
#               to live on the component, wherever it is)
#   component - meta.name of the ia.ai.chat inside it
#   icon      - matches that demo's nav / Home-card icon
# --------------------------------------------------------------------------

PAGES = [
    {
        "view": "Exchange/Alarm Flood Agent/Agent Dock",
        "component": "AiChat",
        "icon": "material/alarm",
        "prompts": [
            "Analyze the most recent alarm flood on this gateway and give me "
            "the root-cause report.",
            "For the latest flood, what should the operator do right now, and "
            "what is the separate engineering fix?",
        ],
    },
    {
        "view": "Exchange/Dashboard Agent/Agent Dock",
        "component": "AiChat",
        "icon": "material/dashboard",
        "prompts": [
            "Build me a full operations dashboard for the line: how it's "
            "running, where product is piling up, and what alarms fired "
            "recently.",
            "Build a shift-handover screen: alarm density over the last 12 "
            "hours, current buffer levels, and a station health comparison so "
            "the next crew knows what they're walking into.",
            "Build a bottleneck dashboard: which station is actually setting "
            "the line's throughput right now, a material flow view, and a "
            "bar chart comparing every station's rate.",
        ],
    },
    {
        "view": "Exchange/Report Issue Agent/Report Chat",
        "component": "AiChat",
        "icon": "material/bug_report",
        # Operator voice, not engineering language -- that is what the agent is
        # built to take. Two, on purpose: filing the ticket is the last thing
        # this chat can do. Validate and Implement fire from the YouTrack
        # column-change webhook (webdev/issue-stage), driven by a human moving
        # the card on the board, so there is no third prompt to offer here.
        "prompts": [
            "There's an issue with the drive torque.",
            "Go ahead and file this ticket.",
        ],
    },
    {
        "view": "Exchange/Security Agent/Security Audit",
        "component": "AiChat",
        "icon": "material/lock",
        "prompts": [
            "Run a full gateway security audit",
            "Show me the role to page access matrix",
            "Which users hold administrator privileges, and should they?",
            "Are my AI agents and MCP server secured?",
        ],
    },
    {
        "view": "Exchange/Tag Import Agent/Tag Import",
        "component": "AiChat",
        "icon": "material/account_tree",
        # The demo script, in order. Shorter than the others on purpose: this
        # chat is half of a 50/50 split beside the review tree, and
        # paragraph-length prompts scrolled the empty state.
        #
        # There is deliberately no "what are the Unresolved entries?" prompt.
        # It is the best *question* in the demo and it is better asked live,
        # off the review panel the audience is already looking at, than
        # offered as a canned one-click. The presenter cue card still has it.
        "prompts": [
            "Read the Studio 5000 controller export on this gateway and show "
            "me the structure you propose, before you create anything.",
            "Looks good, go ahead and create it and report the tag paths.",
            "Delete the old demo tags and clear out the Tag Import Agent "
            "folder so we can start fresh.",
        ],
    },
    {
        "view": "Exchange/Drawing Agent/Drawing AI Chat",
        "component": "AiChat",
        "icon": "material/edit",
        # The real demo is whatever the audience shouts out. These are the
        # opener, for a room that has not warmed up yet -- so they are all
        # plant equipment rather than the recliner-chair sort of prompt: the
        # point being made is that the agent can draw the thing on the screen
        # beside it, not that it can draw.
        #
        # One vertical each, so the opener also makes the "this isn't just
        # food and bev" point. Each names exactly one defining feature, not a
        # handful -- cut 2026-09-17 after the six-verb/multi-feature prompts
        # ran long. The agent's budget is 20-40 elements (~60 ceiling); one
        # feature per prompt is what keeps a drawing well under that ceiling
        # instead of inviting the model to spend it. See the Drawing Agent
        # section in CLAUDE.md.
        "prompts": [
            "Draw a pharmaceutical tablet press with a hopper feeding it.",
            "Draw a data center server rack with cooling fans.",
            "Draw a solar panel array on a tilted mount.",
            "Draw a wastewater clarifier tank with a skimmer arm.",
        ],
    },
]


# --------------------------------------------------------------------------
# Plumbing
# --------------------------------------------------------------------------

def dump(obj):
    """Serialize the way the gateway does: Gson HTML-safe escaping, no trailing
    newline. Matching it keeps the diff scoped and stops the next gateway save
    from rewriting the whole file."""
    out = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)
    for ch in u"<>&='":
        out = out.replace(ch, u"\\u%04x" % ord(ch))
    return out


def page(view_path):
    """The declaration for one chat, looked up by its view path."""
    for p in PAGES:
        if p["view"] == view_path:
            return p
    raise KeyError(view_path)


def find(node, name):
    if isinstance(node, dict):
        if node.get("meta", {}).get("name") == name:
            return node
        for c in node.get("children") or []:
            r = find(c, name)
            if r:
                return r
    return None


def strip_chips(node):
    """Drop the old chip row wherever it is. Returns how many were removed."""
    dropped = 0
    if isinstance(node, dict):
        kids = node.get("children")
        if kids:
            keep = [c for c in kids
                    if c.get("meta", {}).get("name") != CHIP_CONTAINER]
            dropped += len(kids) - len(keep)
            node["children"] = keep
            for c in keep:
                dropped += strip_chips(c)
    return dropped


def read(view_path):
    # Split the declared view path rather than joining it whole: a mixed
    # separator ("...\\views\\Exchange/Report Issue Agent/Report Chat\\view.json") is
    # readable on Windows but raises OSError 22 on write.
    path = os.path.join(VIEWS, *(view_path.split("/") + ["view.json"]))
    original = io.open(path, encoding="utf-8").read()
    return path, original, json.loads(original)


def apply_host(view_path):
    """Strip the chip row from a view that hosts someone else's chat."""
    path, original, d = read(view_path)
    strip_chips(d["root"])
    return path, original, dump(d)


def apply_page(decl):
    """Rewrite one view. Returns (path, original_text, new_text)."""
    path, original, d = read(decl["view"])

    chat = find(d["root"], decl["component"])
    if chat is None:
        sys.exit("no %r component in %s" % (decl["component"], decl["view"]))
    if chat.get("type") != "ia.ai.chat":
        sys.exit("%s/%s is %s, not ia.ai.chat"
                 % (decl["view"], decl["component"], chat.get("type")))

    props = chat.setdefault("props", {})
    props["agentIcon"] = decl["icon"]
    if decl["prompts"]:
        props["suggestedPrompts"] = list(decl["prompts"])
    else:
        props.pop("suggestedPrompts", None)

    strip_chips(d["root"])

    return path, original, dump(d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    total = sum(len(p["prompts"]) for p in PAGES)
    work = [(len(d["prompts"]), apply_page, d) for d in PAGES]
    work += [(0, apply_host, v) for v in CHIP_HOSTS]

    stale, written = [], []
    for count, fn, arg in work:
        path, original, text = fn(arg)
        rel = os.path.relpath(path, ROOT)
        if text == original:
            continue
        if args.check:
            stale.append(rel)
            continue
        io.open(path, "w", encoding="utf-8", newline="").write(text)
        written.append((rel, count))

    if args.check:
        if stale:
            print("stale:")
            for rel in stale:
                print("  %s" % rel)
            sys.exit(1)
        print("up to date (%d chats, %d prompts)" % (len(PAGES), total))
        return

    if not written:
        print("up to date (%d chats, %d prompts)" % (len(PAGES), total))
        return
    for rel, n in written:
        print("wrote %s (%d prompts)" % (rel, n))
    print("")
    print("Now rescan the gateway: bash ../../shared/gateway-api/scan.sh")


if __name__ == "__main__":
    main()
