#!/usr/bin/env python3
"""
Builds the daily-report template that each daily reporter fills in.

Who those people are comes from ecosine-team.json, which is git-ignored — see
ecosine-team.example.json for the shape. Anyone marked "daily_template": false
is skipped unless you pass --all.

Two sheets: the log they type into every day, and a short guide. The columns
are the ones AHMED reads on Friday, so changing a header here means changing
what the weekly report can say — see ecosine-daily.py, which matches columns by
name rather than position so a reordered sheet still works.

Run again at any time; it will refuse to overwrite a sheet that already has
entries in it, so nobody's week gets wiped.
"""

import datetime
import importlib.util
import json
import os
import sys
import zipfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("xl", os.path.join(HERE, "ecosine-xlsx.py"))
xl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(xl)

BASE = os.path.expanduser("~/Documents/Weekly Report")

HEADERS = ["Date", "Category", "Task / Activity", "Status",
           "Time (hrs)", "Outcome / Result", "Blocker / Support needed"]
WIDTHS = [12, 22, 42, 14, 10, 46, 34]

# The recruitment pipeline as Sir runs it, in the order a candidate moves
# through it. Excel holds an inline dropdown list as one comma-separated string
# capped at 255 characters, so a value must never contain a comma itself —
# these come to 151, with room to add a couple more stages later.
CATEGORIES = ["Calls",
              "1st interview",
              "2nd interview",
              "offer letters",
              "visa started",
              "RTA Training Applied",
              "VISA renewals",
              "RTA refresher + renewal",
              "handed over the candidate to OPS"]
STATUSES = ["Done", "In progress", "Blocked", "Carried over"]

GUIDE = [
    ("How to use this sheet", ""),
    ("", ""),
    ("One line per task", "A separate line for each piece of work, not one line per day. "
                          "Five short lines beat one long paragraph."),
    ("Fill it daily", "Two minutes at the end of each day. Filling a week in on Thursday "
                      "night is how detail gets lost."),
    ("Category and Status", "Pick from the dropdown — these are the recruitment stages, "
                            "so the weekly report can count how many candidates reached each one."),
    ("Outcome", "What actually changed — a number, a name, a decision. "
                "\"Chased supplier\" says nothing; \"Chased EMC, parts due Tuesday\" does."),
    ("Blocker", "Anything waiting on someone else. This is the column Sir reads first."),
    ("", ""),
    ("Read every Friday at 12:00", "AHMED collects this sheet into the weekly report. "
                                   "Whatever is in it by then is what gets reported."),
    ("Keep the file name", "Leave the name as it is, or add a date — 'Daily Report Omar 29 Aug 26'. "
                           "The newest dated file wins."),
]


def week_dates(start=None):
    """Monday to Friday of the current UAE working week."""
    today = start or datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    return [monday + datetime.timedelta(days=i) for i in range(5)]


def has_entries(path):
    """True if any row below the header has something typed in it."""
    try:
        z = zipfile.ZipFile(path)
        ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            r = ET.fromstring(z.read("xl/sharedStrings.xml"))
            shared = ["".join(t.text or "" for t in si.iter(ns + "t")) for si in r.findall(ns + "si")]
        root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        for row in root.iter(ns + "row"):
            if int(row.get("r", 0)) <= 6:          # title block and header
                continue
            for c in row.iter(ns + "c"):
                col = "".join(ch for ch in c.get("r", "") if ch.isalpha())
                if col in ("A",):                  # the pre-filled dates do not count
                    continue
                t, v = c.get("t"), c.find(ns + "v")
                if t == "inlineStr":
                    is_el = c.find(ns + "is")
                    if is_el is not None and "".join(x.text or "" for x in is_el.iter(ns + "t")).strip():
                        return True
                elif v is not None and v.text and v.text.strip():
                    if t == "s" and v.text.isdigit() and int(v.text) < len(shared):
                        if shared[int(v.text)].strip():
                            return True
                    else:
                        return True
    except Exception:
        return False
    return False


def build(name, role):
    dates = week_dates()
    rows = [
        [(f"DAILY REPORT — {name.upper()}", xl.S_TITLE)],
        [("Role", xl.S_LABEL), (role, xl.S_CELL), ("Reports to", xl.S_LABEL), ("Tom (HR)", xl.S_CELL)],
        [("Week", xl.S_LABEL),
         (f"{dates[0].strftime('%d %b')} – {dates[-1].strftime('%d %b %Y')}", xl.S_CELL),
         ("Collected", xl.S_LABEL), ("Friday 12:00", xl.S_CELL)],
        [],
        [(h, xl.S_HEADER) for h in HEADERS],
    ]
    # A week of dates pre-filled, several blank lines per day.
    for d in dates:
        for i in range(4):
            rows.append([
                (d.strftime("%d/%m/%Y") if i == 0 else "", xl.S_CELL),
                ("", xl.S_CELL), ("", xl.S_CELL), ("", xl.S_CELL),
                ("", xl.S_CELL), ("", xl.S_CELL), ("", xl.S_CELL),
            ])

    header_row = 5
    last = len(rows)
    log = {
        "name": "Daily Report",
        "rows": rows,
        "widths": WIDTHS,
        "freeze_at": f"A{header_row + 1}",
        "header_row": header_row,
        "merges": ["A1:G1"],
        "validations": [
            (f"B{header_row+1}:B{last}", CATEGORIES),
            (f"D{header_row+1}:D{last}", STATUSES),
        ],
    }

    guide_rows = [[("HOW TO FILL THIS IN", xl.S_TITLE)], []]
    for left, right in GUIDE:
        if not left and not right:
            guide_rows.append([])
        elif not right:
            guide_rows.append([(left, xl.S_TITLE)])
        else:
            guide_rows.append([(left, xl.S_LABEL), (right, xl.S_CELL)])
    guide = {"name": "Guide", "rows": guide_rows, "widths": [30, 86], "merges": ["A1:B1"]}

    return [log, guide]


def daily_reporters():
    """The roster, from ecosine-team.json. No file means nothing to build."""
    path_ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ecosine-team.json")
    try:
        with open(path_, encoding="utf-8") as fh:
            entries = json.load(fh).get("daily_reporters") or []
    except (OSError, ValueError):
        return []

    everyone = "--all" in sys.argv
    people = []
    for e in entries:
        name, agent = e.get("name"), e.get("agent")
        if not name or not agent:
            continue
        if not everyone and e.get("daily_template") is False:
            continue
        people.append((name, e.get("role", ""),
                       os.path.join(BASE, agent.capitalize(), name)))
    return people


def main():
    people = daily_reporters()
    if not people:
        print("  nothing to build: no daily reporters in ecosine-team.json")
        print("  copy ecosine-team.example.json to ecosine-team.json and list them")
        return

    for name, role, folder in people:
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"Daily Report - {name}.xlsx")
        if os.path.exists(path) and has_entries(path):
            print(f"  SKIPPED  {name}: the existing sheet already has entries in it")
            continue
        xl.write_workbook(path, build(name, role))
        print(f"  written  {path.replace(os.path.expanduser('~'), '~')}")


if __name__ == "__main__":
    main()
