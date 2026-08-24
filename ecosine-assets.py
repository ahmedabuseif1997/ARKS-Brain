#!/usr/bin/env python3
"""
Company asset register reader for AHMED — Python standard library only.

Reads the newest asset sheet from Tom's inputs folder and answers questions
about who holds what: laptops, phones, SIM cards, furniture, vehicles.

Two things about these workbooks that matter:

  * They carry more than one sheet. "Company Assets.xlsx" has an "Actual List"
    of real records and an "Input" sheet holding the dropdown lists that feed
    the form. Reading sheet one blindly would work today and break the moment
    the tabs are reordered, so the sheet is chosen by looking for a header with
    an "Assigned To" column.

  * Dates arrive as numbers. Excel stores a date as days since 1899-12-30, and
    a cell that was never formatted comes through as "45668" rather than
    "11/01/2025". Twenty of the sixty-eight rows are like this.

Usage:
    ecosine-assets.py list < {"folder": "...", "person": "...",
                              "category": "...", "asset": "..."}
"""

import datetime
import importlib.util
import json
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
HERE = os.path.dirname(os.path.abspath(__file__))

# Reuse the file-picking and date-from-filename logic rather than keeping a
# second copy of it in step.
_spec = importlib.util.spec_from_file_location("fleet", os.path.join(HERE, "ecosine-fleet.py"))
_fleet = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fleet)
pick_newest = _fleet.pick_newest
tidy = _fleet.tidy


def out(obj):
    json.dump(obj, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.exit(0)


def fail(message, **extra):
    out({"error": message, **extra})


def excel_date(value):
    """A bare number in a date column is days since 1899-12-30."""
    v = str(value).strip()
    if not v:
        return ""
    if re.fullmatch(r"\d{5}(\.\d+)?", v):          # 5 digits ≈ 1927-2073
        try:
            d = datetime.date(1899, 12, 30) + datetime.timedelta(days=int(float(v)))
            return d.strftime("%d/%m/%Y")
        except (ValueError, OverflowError):
            return v
    return v


def sheet_names(z):
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {}
    try:
        rl = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        for r in rl:
            rels[r.get("Id")] = r.get("Target")
    except Exception:
        pass
    out_ = []
    for sh in wb.iter(NS + "sheet"):
        rid = sh.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = rels.get(rid, "")
        target = target.split("/")[-1] if target else ""
        out_.append((sh.get("name"), target))
    return out_


def read_sheet(z, shared, part):
    root = ET.fromstring(z.read(part))
    rows = []
    for row in root.iter(NS + "row"):
        cells = []
        for c in row.iter(NS + "c"):
            t = c.get("t")
            if t == "inlineStr":
                is_el = c.find(NS + "is")
                cells.append("".join(x.text or "" for x in is_el.iter(NS + "t")) if is_el is not None else "")
                continue
            v = c.find(NS + "v")
            if v is None or v.text is None:
                cells.append("")
                continue
            if t == "s" and v.text.isdigit() and int(v.text) < len(shared):
                cells.append(shared[int(v.text)])
            else:
                cells.append(v.text)
        while cells and not cells[-1].strip():
            cells.pop()
        if any(x.strip() for x in cells):
            rows.append(cells)
    return rows


def find_column(header, *words):
    for i, h in enumerate(header):
        flat = re.sub(r"[^a-z]", "", h.lower())
        for w in words:
            if re.sub(r"[^a-z]", "", w.lower()) in flat:
                return i
    return None


def cmd_list(args):
    folder = args.get("folder") or ""
    if not os.path.isdir(folder):
        fail(f"No folder at {folder}.")

    path, why, all_names = pick_newest(folder)
    if not path:
        fail("No spreadsheet in that folder yet.", folder=folder)

    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        r = ET.fromstring(z.read("xl/sharedStrings.xml"))
        shared = ["".join(t.text or "" for t in si.iter(NS + "t")) for si in r.findall(NS + "si")]

    # The sheet is chosen by its header, not its position.
    picked = None
    for name, part in sheet_names(z):
        full = f"xl/worksheets/{part}" if part else None
        if not full or full not in z.namelist():
            continue
        rows = read_sheet(z, shared, full)
        if len(rows) < 2:
            continue
        header = [tidy(h) for h in rows[0]]
        if find_column(header, "assignedto", "holder", "custodian") is not None:
            picked = (name, header, rows[1:])
            break
    if not picked:
        fail(f"No sheet in {os.path.basename(path)} has an 'Assigned To' column. "
             f"Sheets present: {', '.join(n for n, _ in sheet_names(z))}")

    sheet, header, data = picked
    ci = {
        "category": find_column(header, "type", "category"),
        "name":     find_column(header, "assetname", "asset", "item", "description"),
        "brand":    find_column(header, "brand", "make"),
        "model":    find_column(header, "model"),
        "person":   find_column(header, "assignedto", "holder", "custodian"),
        "date":     find_column(header, "assigneddate", "date"),
        "condition": find_column(header, "condition", "status"),
        "serial":   find_column(header, "serial", "imei"),
    }

    def cell(row, key):
        i = ci[key]
        return tidy(row[i]) if i is not None and i < len(row) else ""

    assets = []
    for row in data:
        person = cell(row, "person")
        item = cell(row, "name")
        if not person and not item:
            continue
        assets.append({
            "category": cell(row, "category"),
            "asset": item,
            "brand": cell(row, "brand"),
            "model": cell(row, "model"),
            "assigned_to": person,
            "assigned_date": excel_date(cell(row, "date")),
            **({"condition": cell(row, "condition")} if cell(row, "condition") else {}),
            **({"serial": cell(row, "serial")} if cell(row, "serial") else {}),
        })

    total = len(assets)
    holders = {}
    categories = {}
    for a in assets:
        holders[a["assigned_to"] or "(unassigned)"] = holders.get(a["assigned_to"] or "(unassigned)", 0) + 1
        categories[a["category"] or "(none)"] = categories.get(a["category"] or "(none)", 0) + 1

    # ── filters ───────────────────────────────────────────────────────────
    def norm(t):
        return re.sub(r"[^a-z0-9]", "", str(t or "").lower())

    want_person = norm(args.get("person"))
    want_cat = norm(args.get("category"))
    want_asset = norm(args.get("asset"))

    matched_person = None
    if want_person:
        # "Haseeb" should find "Abdul Haseeb"; match on any part of the name.
        names = sorted({a["assigned_to"] for a in assets if a["assigned_to"]})
        hits = [n for n in names if want_person in norm(n)
                or any(want_person == norm(part) for part in n.split())]
        if not hits:
            hits = [n for n in names if norm(n) in want_person]
        if len(hits) == 1:
            matched_person = hits[0]
        elif len(hits) > 1:
            out({
                "source_file": os.path.basename(path), "sheet": sheet,
                "ambiguous_person": hits,
                "note": f"More than one person matches that. Ask Sir which: {', '.join(hits)}.",
            })
        else:
            out({
                "source_file": os.path.basename(path), "sheet": sheet,
                "total_assets": total, "returned": 0, "assets": [],
                "people_on_file": sorted(holders, key=lambda k: -holders[k]),
                "note": f"Nobody on the asset register matches '{args.get('person')}'. "
                        f"The register lists: {', '.join(sorted(holders))}.",
            })

    picked_rows = []
    for a in assets:
        if matched_person and a["assigned_to"] != matched_person:
            continue
        if want_cat and want_cat not in norm(a["category"]):
            continue
        if want_asset and want_asset not in norm(a["asset"]) \
           and want_asset not in norm(a["brand"]) and want_asset not in norm(a["model"]):
            continue
        picked_rows.append(a)

    out({
        "source_file": os.path.basename(path),
        "sheet": sheet,
        "chosen_because": why,
        "other_files_in_folder": [n for n in all_names if n != os.path.basename(path)],
        "total_assets": total,
        "people_on_file": len(holders),
        "by_person": dict(sorted(holders.items(), key=lambda kv: -kv[1])),
        "by_category": dict(sorted(categories.items(), key=lambda kv: -kv[1])),
        "matched_person": matched_person,
        "returned": len(picked_rows),
        "assets": picked_rows[:80],
    })


COMMANDS = {"list": cmd_list}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        fail(f"Usage: ecosine-assets.py [{'|'.join(COMMANDS)}]")
    raw = sys.stdin.read().strip() or "{}"
    try:
        args = json.loads(raw)
    except Exception as exc:
        fail(f"Bad arguments: {exc}")
    try:
        COMMANDS[sys.argv[1]](args)
    except Exception as exc:
        fail(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
