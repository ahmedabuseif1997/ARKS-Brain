#!/usr/bin/env python3
"""
Minimal styled .xlsx writer — Python standard library only.

An .xlsx file is a zip of XML parts. Everything here writes those parts by
hand: no openpyxl, no xlsxwriter, nothing to install. It supports what a report
template actually needs — several sheets, a styled header row, column widths, a
frozen top row, and dropdown lists on a column — and nothing more.

Used by make-report-templates.py; not meant to be run directly.
"""

import zipfile
from xml.sax.saxutils import escape

# Style ids, in the order they are written into styles.xml below.
S_DEFAULT = 0
S_TITLE = 1
S_HEADER = 2
S_LABEL = 3
S_CELL = 4
S_DATE = 5
S_NOTE = 6


def _col_letter(i):
    """0 → A, 25 → Z, 26 → AA."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _content_types(n_sheets):
    sheets = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i+1}.xml" '
        f'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(n_sheets))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        f'{sheets}</Types>')


def _styles():
    """Fonts, fills and the cell formats that reference them."""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="5">'
        '<font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="15"/><color rgb="FF16303F"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><color rgb="FF2C4A5E"/><name val="Calibri"/></font>'
        '<font><i/><sz val="10"/><color rgb="FF6C7A89"/><name val="Calibri"/></font>'
        '</fonts>'
        '<fills count="4">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF2C4A5E"/><bgColor indexed="64"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFEDF1F4"/><bgColor indexed="64"/></patternFill></fill>'
        '</fills>'
        '<borders count="2">'
        '<border><left/><right/><top/><bottom/><diagonal/></border>'
        '<border>'
        '<left style="thin"><color rgb="FFD1D8E0"/></left>'
        '<right style="thin"><color rgb="FFD1D8E0"/></right>'
        '<top style="thin"><color rgb="FFD1D8E0"/></top>'
        '<bottom style="thin"><color rgb="FFD1D8E0"/></bottom>'
        '<diagonal/></border>'
        '</borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="7">'
        # 0 default
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        # 1 title
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        # 2 header row
        '<xf numFmtId="0" fontId="2" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1">'
        '<alignment vertical="center" wrapText="1"/></xf>'
        # 3 label
        '<xf numFmtId="0" fontId="3" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/>'
        # 4 body cell
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1">'
        '<alignment vertical="top" wrapText="1"/></xf>'
        # 5 date cell (dd/mm/yyyy)
        '<xf numFmtId="14" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/>'
        # 6 note
        '<xf numFmtId="0" fontId="4" fillId="0" borderId="0" xfId="0" applyFont="1"><alignment wrapText="1"/></xf>'
        '</cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>')


def _sheet_xml(sheet):
    """One worksheet. `rows` is a list of lists of (value, style) or plain str."""
    cols = ""
    if sheet.get("widths"):
        cols = "<cols>" + "".join(
            f'<col min="{i+1}" max="{i+1}" width="{w}" customWidth="1"/>'
            for i, w in enumerate(sheet["widths"])) + "</cols>"

    pane = ""
    if sheet.get("freeze_at"):
        ref = sheet["freeze_at"]
        row = int("".join(ch for ch in ref if ch.isdigit()))
        pane = (f'<sheetViews><sheetView workbookViewId="0">'
                f'<pane ySplit="{row-1}" topLeftCell="{ref}" activePane="bottomLeft" state="frozen"/>'
                f'</sheetView></sheetViews>')
    else:
        pane = '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'

    merges = ""
    if sheet.get("merges"):
        merges = ('<mergeCells count="%d">' % len(sheet["merges"])
                  + "".join(f'<mergeCell ref="{m}"/>' for m in sheet["merges"])
                  + "</mergeCells>")

    body = []
    for r, row in enumerate(sheet["rows"], start=1):
        cells = []
        for c, cell in enumerate(row):
            value, style = (cell if isinstance(cell, tuple) else (cell, S_CELL))
            ref = f"{_col_letter(c)}{r}"
            if value is None or value == "":
                cells.append(f'<c r="{ref}" s="{style}"/>')
            elif isinstance(value, (int, float)):
                cells.append(f'<c r="{ref}" s="{style}"><v>{value}</v></c>')
            else:
                cells.append(f'<c r="{ref}" s="{style}" t="inlineStr">'
                             f'<is><t xml:space="preserve">{escape(str(value))}</t></is></c>')
        if cells:
            h = ' ht="30" customHeight="1"' if sheet.get("header_row") == r else ""
            body.append(f'<row r="{r}"{h}>' + "".join(cells) + "</row>")

    # Dropdowns. Written inline rather than as a separate list sheet, which
    # keeps the file to one part per sheet and survives being emailed around.
    validations = ""
    if sheet.get("validations"):
        vs = []
        for ref, options in sheet["validations"]:
            joined = escape(",".join(options))
            vs.append(f'<dataValidation type="list" allowBlank="1" showInputMessage="1" '
                      f'showErrorMessage="1" sqref="{ref}">'
                      f'<formula1>"{joined}"</formula1></dataValidation>')
        validations = f'<dataValidations count="{len(vs)}">' + "".join(vs) + "</dataValidations>"

    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'{pane}{cols}<sheetData>' + "".join(body) + '</sheetData>'
            f'{merges}{validations}</worksheet>')


def write_workbook(path, sheets):
    """sheets: [{name, rows, widths, freeze_at, merges, validations, header_row}]"""
    sheet_tags = "".join(
        f'<sheet name="{escape(s["name"])}" sheetId="{i+1}" r:id="rId{i+1}"/>'
        for i, s in enumerate(sheets))
    workbook = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                f'<sheets>{sheet_tags}</sheets></workbook>')

    rels = "".join(
        f'<Relationship Id="rId{i+1}" '
        f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{i+1}.xml"/>' for i in range(len(sheets)))
    rels += (f'<Relationship Id="rId{len(sheets)+1}" '
             'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
             'Target="styles.xml"/>')

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _content_types(len(sheets)))
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" '
                   'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                   'Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + rels + "</Relationships>")
        z.writestr("xl/styles.xml", _styles())
        for i, s in enumerate(sheets):
            z.writestr(f"xl/worksheets/sheet{i+1}.xml", _sheet_xml(s))
    return path
