#!/usr/bin/env python3
"""Generate the Line 1 controller exports the Tag Import Agent reads.

Usage (from projects/icc-2026/):

    python scripts/generate_line1_export.py
    python scripts/generate_line1_export.py --check     # CI: fail if stale

Writes two files into reference/line1/, both from scripts/line1_model.py:

    Line1_ControllerTags_Export.CSV      Studio 5000 tag export
    Line1_MainProgram_Logic_Export.CSV   ladder rung export, neutral text

Format notes, because these are meant to look like the real thing:

* The tag export follows the RSLogix 5000 / Studio 5000 CSV interchange format:
  `remark,"..."` lines, then a bare version number (0.3), then the column header
  TYPE,SCOPE,NAME,DESCRIPTION,DATATYPE,SPECIFIER,ATTRIBUTES. SCOPE is empty for
  controller-scoped tags. ATTRIBUTES carries the RADIX / Constant /
  ExternalAccess triple that Logix Designer writes.
* Studio 5000 has no native rung-level CSV export - ladder comes out as L5X/L5K,
  as rung mnemonics copied from the editor, or as a print. The logic export here
  is the third-party/DIY shape a reviewer actually gets handed: one row per rung
  carrying the rung comment and the neutral text, with the same remark header so
  it is obvious which project and processor it came from.
* Neutral text is exactly what the Logix editor puts on the clipboard for a
  rung: instructions concatenated, operands in brackets, branches in [ , ],
  terminated by a semicolon.
"""

import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import line1_model as model  # noqa: E402

OUT_DIR = os.path.join(ROOT, "reference", "line1")

TAG_FILE = "Line1_ControllerTags_Export.CSV"
LOGIC_FILE = "Line1_MainProgram_Logic_Export.CSV"


def _remarks(export_description, extra=()):
    """The header block Logix Designer writes above the column row."""
    lines = [
        ["remark", "CSV-Import-Export"],
        ["remark", "Date = %s" % model.EXPORT_DATE],
        ["remark", "Version = %s" % model.SOFTWARE_VERSION],
        ["remark", "Owner = %s" % model.OWNER],
        ["remark", "Controller = %s (%s)" % (model.CONTROLLER, model.PROCESSOR)],
        ["remark", export_description],
    ]
    for note in extra:
        lines.append(["remark", note])
    return lines


def _attributes(datatype):
    """The ATTRIBUTES cell for a tag of this datatype."""
    if datatype == "STRING":
        # A STRING is a structure, so it carries no RADIX.
        return "(Constant := false, ExternalAccess := Read/Write)"
    return "(RADIX := %s, Constant := false, ExternalAccess := Read/Write)" % (
        model.RADIX[datatype]
    )


def write_tag_export(path):
    tags = model.build_tags()
    if len(tags) != model.EXPECTED_TAG_COUNT:
        raise SystemExit(
            "model produced %d tags, expected %d"
            % (len(tags), model.EXPECTED_TAG_COUNT)
        )
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        for row in _remarks("Export = Controller tags",
                            extra=[model.PROGRAM_SCOPE_NOTE]):
            w.writerow(row)
        w.writerow(["0.3"])
        w.writerow(["TYPE", "SCOPE", "NAME", "DESCRIPTION", "DATATYPE",
                    "SPECIFIER", "ATTRIBUTES"])
        for t in tags:
            # Written by hand rather than through csv.writer: Logix quotes the
            # last four fields unconditionally, including the empty SPECIFIER as
            # "", and csv only quotes what it has to.
            fh.write('TAG,,%s,"%s","%s","","%s"\r\n' % (
                t.name,
                t.description.replace('"', '""'),
                t.datatype,
                _attributes(t.datatype),
            ))
    return len(tags)


def write_logic_export(path):
    rungs = model.build_rungs()
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        for row in _remarks("Export = Routine logic, neutral text",
                            extra=[
                                "Language = RLL (Ladder Diagram)",
                                "Instruction mnemonics are described in "
                                "Rockwell publication 1756-RM003.",
                                model.PROGRAM_SCOPE_NOTE,
                            ]):
            w.writerow(row)
        w.writerow(["0.3"])
        w.writerow(["PROGRAM", "ROUTINE", "RUNG", "TYPE", "COMMENT", "TEXT"])
        for r in rungs:
            w.writerow([r.program, r.routine, r.number, "N", r.comment, r.text])
    return len(rungs)


WRITERS = [
    (TAG_FILE, write_tag_export, "controller tags"),
    (LOGIC_FILE, write_logic_export, "rungs"),
]


def main():
    check = "--check" in sys.argv
    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)

    stale = []
    for filename, writer, unit in WRITERS:
        path = os.path.join(OUT_DIR, filename)
        before = None
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as fh:
                before = fh.read()
        if check:
            tmp = path + ".check"
            count = writer(tmp)
            with open(tmp, "r", encoding="utf-8") as fh:
                after = fh.read()
            os.remove(tmp)
            if after != before:
                stale.append(filename)
            print("%-38s %4d %s%s" % (
                filename, count, unit, "  STALE" if after != before else ""))
        else:
            count = writer(path)
            print("%-38s %4d %s -> %s" % (filename, count, unit, path))

    if check and stale:
        raise SystemExit(
            "stale: %s. Re-run scripts/generate_line1_export.py." % ", ".join(stale)
        )


if __name__ == "__main__":
    main()
