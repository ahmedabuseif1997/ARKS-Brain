#!/usr/bin/env python3
"""
Reads the daily-report sheets that individuals fill in — whoever is listed in
ecosine-team.json — and returns their week as structured JSON.

Columns are matched by NAME, not position, so someone reordering or inserting a
column does not silently shift every field by one. The sheet is found the same
way the other readers find theirs: newest date in the file name, falling back to
modification time.

Usage:
    ecosine-daily.py week < {"folder": "...", "person": "..."}
    ecosine-daily.py all  < {"people": [{"name": "...", "folder": "..."}, ...]}
"""

import importlib.util
import json
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
HERE = os.path.dirname(os.path.abspath(__file__))

_spec = importlib.util.spec_from_file_location("fleet", os.path.join(HERE, "ecosine-fleet.py"))
_fleet = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fleet)
pick_newest, tidy, find_column = _fleet.pick_newest, _fleet.tidy, _fleet.find_column

_aspec = importlib.util.spec_from_file_location("assets", os.path.join(HERE, "ecosine-assets.py"))
_assets = importlib.util.module_from_spec(_aspec)
_aspec.loader.exec_module(_assets)
excel_date, sheet_names, read_sheet = _assets.excel_date, _assets.sheet_names, _assets.read_sheet


def out(obj):
    json.dump(obj, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.exit(0)


def read_week(folder, person):
    """One person's week. Returns a dict; never raises for a missing folder."""
    if not os.path.isdir(folder):
        return {"person": person, "error": "No folder", "entries": [], "filed": False}

    path, why, _ = pick_newest(folder)
    if not path:
        return {"person": person, "error": "No sheet in the folder",
                "entries": [], "filed": False}

    try:
        z = zipfile.ZipFile(path)
    except Exception as exc:
        return {"person": person, "error": f"Could not open the sheet: {exc}",
                "entries": [], "filed": False}

    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        r = ET.fromstring(z.read("xl/sharedStrings.xml"))
        shared = ["".join(t.text or "" for t in si.iter(NS + "t")) for si in r.findall(NS + "si")]

    # Find the sheet whose header carries a Task column; the Guide tab has none.
    picked = None
    for name, part in sheet_names(z):
        full = f"xl/worksheets/{part}" if part else None
        if not full or full not in z.namelist():
            continue
        rows = read_sheet(z, shared, full)
        for i, row in enumerate(rows[:12]):
            header = [tidy(h) for h in row]
            if find_column(header, "task", "activity") is not None and \
               find_column(header, "date") is not None:
                picked = (name, header, rows[i + 1:])
                break
        if picked:
            break

    if not picked:
        return {"person": person, "source_file": os.path.basename(path),
                "error": "No table with Date and Task columns", "entries": [], "filed": False}

    sheet, header, data = picked
    ci = {
        "date":     find_column(header, "date"),
        "category": find_column(header, "category", "type"),
        "task":     find_column(header, "task", "activity"),
        "status":   find_column(header, "status"),
        "hours":    find_column(header, "time", "hours", "hrs"),
        "outcome":  find_column(header, "outcome", "result"),
        "blocker":  find_column(header, "blocker", "support", "issue"),
    }

    def cell(row, key):
        i = ci[key]
        return tidy(row[i]) if i is not None and i < len(row) else ""

    entries, last_date = [], ""
    for row in data:
        task = cell(row, "task")
        date = excel_date(cell(row, "date")) or last_date
        if date:
            last_date = date
        if not task:
            continue                     # a blank template line, not an entry
        entries.append({
            "date": date,
            "category": cell(row, "category"),
            "task": task,
            "status": cell(row, "status"),
            "hours": cell(row, "hours"),
            "outcome": cell(row, "outcome"),
            "blocker": cell(row, "blocker"),
        })

    by_status, by_category = {}, {}
    for e in entries:
        by_status[e["status"] or "(blank)"] = by_status.get(e["status"] or "(blank)", 0) + 1
        by_category[e["category"] or "(blank)"] = by_category.get(e["category"] or "(blank)", 0) + 1
    blockers = [e for e in entries if e["blocker"]]

    hours = 0.0
    for e in entries:
        try:
            hours += float(re.sub(r"[^0-9.]", "", e["hours"]) or 0)
        except ValueError:
            pass

    return {
        "person": person,
        "source_file": os.path.basename(path),
        "chosen_because": why,
        "sheet": sheet,
        "filed": bool(entries),
        "entry_count": len(entries),
        "total_hours": round(hours, 1) if hours else None,
        "by_status": by_status,
        "by_category": by_category,
        "blockers": blockers,
        "entries": entries[:60],
    }


def cmd_week(args):
    out(read_week(args.get("folder") or "", args.get("person") or "Unknown"))


def cmd_all(args):
    people = args.get("people") or []
    results = [read_week(p.get("folder", ""), p.get("name", "Unknown")) for p in people]
    filed = [r["person"] for r in results if r.get("filed")]
    missing = [r["person"] for r in results if not r.get("filed")]
    out({
        "filed": filed,
        "did_not_file": missing,
        "total_entries": sum(r.get("entry_count", 0) for r in results),
        "all_blockers": [
            {"person": r["person"], **b} for r in results for b in (r.get("blockers") or [])
        ],
        "people": results,
    })


COMMANDS = {"week": cmd_week, "all": cmd_all}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        out({"error": f"Usage: ecosine-daily.py [{'|'.join(COMMANDS)}]"})
    raw = sys.stdin.read().strip() or "{}"
    try:
        args = json.loads(raw)
    except Exception as exc:
        out({"error": f"Bad arguments: {exc}"})
    try:
        COMMANDS[sys.argv[1]](args)
    except Exception as exc:
        out({"error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    main()
