#!/usr/bin/env python3
"""
Fleet status reader for AHMED — Python standard library only.

Reads the newest vehicle sheet from Arthur's inputs folder and returns it as
structured JSON: plate, model, company, ownership, location and remarks per
car, plus counts by company and location.

"Newest" is decided by a date written into the FILE NAME first ("cars status
23 aug 26"), and only falls back to the file's modification time when the name
carries no date. Sir names these files by the date the data represents, and a
sheet edited today may well describe last week — so the name is the better
authority, and copying a file (which resets mtime) must not silently promote it.

Usage:
    ecosine-fleet.py status < {"folder": "...", "company": "...", "location": "...",
                               "plate": "...", "only_issues": false}
"""

import datetime
import json
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

# The sheet spells the group's own name inconsistently. Grouping on the raw
# value would report two separate companies that are plainly the same one.
COMPANY_FIX = {
    "eocsine": "Ecosine",
    "ecosine": "Ecosine",
    "egari":   "Egari",
    "egary":   "Egari",
    "fxtt":    "FXTT",
}


def load_locations():
    """The places the fleet sits, with their real names and coordinates.
    Optional: a missing file just means locations stay as written."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ecosine-locations.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh).get("locations", {})
    except Exception:
        return {}, {}
    # Flatten every spelling to one lookup, so 'AL RAYA' and
    # 'Alraya Albayda Auto' both land on the same workshop.
    index = {}
    for key, rec in data.items():
        for name in [key] + list(rec.get("aliases") or []):
            index[re.sub(r"[^a-z0-9]", "", name.lower())] = key
    return data, index


LOCATIONS, LOCATION_INDEX = load_locations()


def resolve_location(raw):
    """Match a sheet value to a known place. Returns (key, record) or (None, None)."""
    flat = re.sub(r"[^a-z0-9]", "", (raw or "").lower())
    if not flat:
        return None, None
    key = LOCATION_INDEX.get(flat)
    if key:
        return key, LOCATIONS[key]
    # Fall back to containment, which catches 'abu hail parking' and the like.
    for known, k in LOCATION_INDEX.items():
        if known and (known in flat or flat in known):
            return k, LOCATIONS[k]
    return None, None


def out(obj):
    json.dump(obj, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.exit(0)


def fail(message, **extra):
    out({"error": message, **extra})


def date_from_name(name):
    """Pull a date out of a filename like 'cars status 23 aug 26'.

    Each pattern is tried in turn and a miss falls through to the next. An
    earlier version returned as soon as a pattern matched shape but not
    meaning — "cars 31-12-2026" captured "cars" as the month, found it was not
    one, and gave up without ever trying the numeric forms.
    """
    low = name.lower()

    def build(year, month, day):
        try:
            y = int(year)
            y += 2000 if y < 100 else 0
            return datetime.date(y, int(month), int(day))
        except (ValueError, TypeError):
            return None

    # 23 aug 26 · 23 august 2026
    for m in re.finditer(r"(\d{1,2})\s*[-_ ]\s*([a-z]{3,9})\s*[-_ ]\s*(\d{2,4})", low):
        mon = MONTHS.get(m.group(2)[:3])
        if mon:
            d = build(m.group(3), mon, m.group(1))
            if d:
                return d

    # aug 23 26 · august 23 2026
    for m in re.finditer(r"([a-z]{3,9})\s*[-_ ]\s*(\d{1,2})\s*[-_ ]\s*(\d{2,4})", low):
        mon = MONTHS.get(m.group(1)[:3])
        if mon:
            d = build(m.group(3), mon, m.group(2))
            if d:
                return d

    # 2026-08-23 (unambiguous, so it goes before the day-first form)
    for m in re.finditer(r"(\d{4})[-_.](\d{1,2})[-_.](\d{1,2})", low):
        d = build(m.group(1), m.group(2), m.group(3))
        if d:
            return d

    # 23-08-2026 · 23.08.26 — day first, as written in the Gulf
    for m in re.finditer(r"(\d{1,2})[-_.](\d{1,2})[-_.](\d{2,4})", low):
        d = build(m.group(3), m.group(2), m.group(1))
        if d:
            return d

    return None


def pick_newest(folder):
    """The sheet to trust, and why it was chosen."""
    try:
        names = [f for f in os.listdir(folder)
                 if f.lower().endswith((".xlsx", ".xls")) and not f.startswith((".", "~$"))]
    except FileNotFoundError:
        return None, None, []
    if not names:
        return None, None, []

    dated, undated = [], []
    for n in names:
        d = date_from_name(n)
        (dated if d else undated).append((d, n))

    if dated:
        dated.sort(key=lambda t: t[0], reverse=True)
        d, name = dated[0]
        return os.path.join(folder, name), f"newest date in the file name ({d.isoformat()})", names
    undated.sort(key=lambda t: os.path.getmtime(os.path.join(folder, t[1])), reverse=True)
    name = undated[0][1]
    return os.path.join(folder, name), "most recently modified (no date in any file name)", names


def sheet_rows(path):
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        r = ET.fromstring(z.read("xl/sharedStrings.xml"))
        shared = ["".join(t.text or "" for t in si.iter(NS + "t")) for si in r.findall(NS + "si")]
    sheets = [n for n in z.namelist() if n.startswith("xl/worksheets/sheet")]
    rows = []
    for sh in sheets[:1]:                      # fleet lists live on the first sheet
        root = ET.fromstring(z.read(sh))
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
    """Tolerant header matching — the sheet has 'Loaction' for 'Location'."""
    for i, h in enumerate(header):
        flat = re.sub(r"[^a-z]", "", h.lower())
        for w in words:
            if re.sub(r"[^a-z]", "", w.lower()) in flat:
                return i
    return None


def tidy(value):
    return re.sub(r"\s+", " ", (value or "").strip())


def tidy_location(value):
    v = tidy(value)
    if not v:
        return ""
    # "on road", "On Road", "ON Road" are one place written three ways.
    return v.title() if v.lower() in ("on road", "abu hail", "al raya") else v


def cmd_status(args):
    folder = args.get("folder") or ""
    if not os.path.isdir(folder):
        fail(f"No folder at {folder}.")

    path, why, all_names = pick_newest(folder)
    if not path:
        fail("No spreadsheet in that folder yet.", folder=folder)

    rows = sheet_rows(path)
    if len(rows) < 2:
        fail(f"{os.path.basename(path)} has no rows under its header.")

    header = [tidy(h) for h in rows[0]]
    ci = {
        "plate":     find_column(header, "plate"),
        "model":     find_column(header, "make", "model"),
        "company":   find_column(header, "company"),
        "ownership": find_column(header, "ownership", "owner"),
        "location":  find_column(header, "location", "loaction"),
        "remarks":   find_column(header, "remark", "note"),
    }
    if ci["plate"] is None:
        fail(f"Could not find a plate column in {os.path.basename(path)}. "
             f"Columns present: {', '.join(header)}")

    def cell(row, key):
        i = ci[key]
        return tidy(row[i]) if i is not None and i < len(row) else ""

    vehicles, company_typos, unknown_locations = [], set(), set()
    for row in rows[1:]:
        plate = cell(row, "plate")
        if not plate:
            continue
        raw_company = cell(row, "company")
        key = re.sub(r"[^a-z]", "", raw_company.lower())
        company = COMPANY_FIX.get(key, raw_company)
        if company and raw_company and company.lower() != raw_company.lower():
            company_typos.add(f"{raw_company} → {company}")
        raw_location = cell(row, "location")
        loc_key, loc_rec = resolve_location(raw_location)
        vehicle = {
            "plate": plate,
            "model": cell(row, "model"),
            "company": company,
            "ownership": cell(row, "ownership"),
            "location": loc_rec["official_name"] if loc_rec else tidy_location(raw_location),
            "location_as_written": tidy(raw_location),
            "remarks": cell(row, "remarks"),
        }
        if loc_rec:
            vehicle["location_key"] = loc_key
            vehicle["address"] = loc_rec.get("address", "")
            vehicle["location_kind"] = loc_rec.get("kind", "")
            if loc_rec.get("lat") is not None:
                vehicle["lat"] = loc_rec["lat"]
                vehicle["lng"] = loc_rec["lng"]
        elif raw_location.strip():
            unknown_locations.add(tidy(raw_location))
        vehicles.append(vehicle)

    total = len(vehicles)

    # ── filters ───────────────────────────────────────────────────────────
    def matches(v):
        for key in ("company", "location", "plate"):
            want = tidy(str(args.get(key) or ""))
            if not want:
                continue
            if key == "location":
                # Match the resolved name, the spelling in the sheet, and the
                # directory key. Comparing only against the official name meant
                # asking for "Local Self Stores" — exactly what the sheet says —
                # found nothing, because the directory calls it "Storage".
                # Resolve what he asked for, and compare keys when both sides
                # are known places. Only fall back to text matching otherwise.
                resolved_key, _ = resolve_location(want)
                if resolved_key and v.get("location_key"):
                    if v["location_key"] != resolved_key:
                        return False
                    continue
                flat_want = re.sub(r"[^a-z0-9]", "", want.lower())
                haystacks = [v.get("location", ""), v.get("location_as_written", "")]
                if not any(flat_want in re.sub(r"[^a-z0-9]", "", h.lower())
                           for h in haystacks if h):
                    return False
                continue
            if want.lower() not in v[key].lower():
                return False
        if args.get("only_issues"):
            on_road = v["location"].lower().replace(" ", "") == "onroad"
            if on_road and not v["remarks"]:
                return False
        return True

    picked = [v for v in vehicles if matches(v)]

    def tally(field):
        counts = {}
        for v in vehicles:
            counts[v[field] or "(blank)"] = counts.get(v[field] or "(blank)", 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    on_road = sum(1 for v in vehicles
                  if v["location"].lower().replace(" ", "") == "onroad")
    flagged = [v for v in vehicles if v["remarks"]]

    out({
        "source_file": os.path.basename(path),
        "chosen_because": why,
        "other_files_in_folder": [n for n in all_names if n != os.path.basename(path)],
        "total_vehicles": total,
        "on_road": on_road,
        "off_road": total - on_road,
        "with_remarks": len(flagged),
        "by_company": tally("company"),
        "by_location": tally("location"),
        "by_ownership": tally("ownership"),
        "returned": len(picked),
        "vehicles": picked,
        "sheet_inconsistencies": sorted(company_typos),
        "locations_not_in_the_directory": sorted(unknown_locations),
    })


COMMANDS = {"status": cmd_status}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        fail(f"Usage: ecosine-fleet.py [{'|'.join(COMMANDS)}]")
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
