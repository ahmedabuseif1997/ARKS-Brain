# ARKS Brain

A personal AI assistant — voice in, voice out, a living-brain interface, and
real access to the files, mail and fleet data on the Mac it runs on. The
assistant answers to the name **AHMED**; ARKS Brain is the project.

Everything runs locally. The server is yours, the keys are yours, and nothing
leaves the machine except the model and search calls you configure yourself.
Point it at your own documents, your own mailbox and your own fleet sheet — it
ships knowing nothing about anybody.

Two files do almost all of the work:

| File | What it is |
|---|---|
| `Ecosine.html` | The whole front end — the procedural point-cloud brain (Canvas 2D, hand-rolled 3D, no libraries), speech recognition, speech playback, transcript, settings. One self-contained file. |
| `ecosine-server.js` | The companion server. Zero dependencies — Node standard library only. Serves the app, holds the API keys, and runs every tool. |

Everything else is a tool the server shells out to.

## Running it

```bash
node ecosine-server.js
```

Then open **http://localhost:7777**.

**Open it through the server, not by double-clicking `Ecosine.html`.** Under
`file://` Chrome blocks `localStorage` outright — so no settings and no saved
API key — and speech-synthesis voices never load. Over `http://localhost:7777`
both work. If settings stop saving or the voice goes silent, check this first.

Requires Node (built on v24) and Python 3 (built on 3.14), both already on macOS
or via Homebrew. There is nothing to `npm install`.

## Configuration

Copy `.env.example` to `.env` and fill in the keys. `.env` is git-ignored and
must stay that way.

Three more files work the same way — copy each template, fill it in, and it
stays out of git. They hold the details that make the assistant yours:

```bash
cp ecosine-profile.example.json   ecosine-profile.json
cp ecosine-team.example.json      ecosine-team.json
cp ecosine-locations.example.json ecosine-locations.json
```

All three are optional. Without them the assistant still runs — it just does
not know who you are, who reports to you, or where your vehicles are parked.

| Variable | Purpose |
|---|---|
| `OPENAI_COMPAT_API_KEY` | MiniMax — the deep brain, the voice, and web search, all three |
| `GROQ_API_KEY` | Optional fast brain. With both set, quick asks go to Groq and deep work to MiniMax |
| `TTS_VOICE`, `TTS_MODEL`, `TTS_SPEED` | Speech output. Voice IDs verified against MiniMax's own list |
| `MAIL_HOST`, `MAIL_USER` | IMAP read + SMTP send, Python stdlib only |
| `TAVILY_API_KEY` | Only needed for non-MiniMax brains, which have no native web search |

**Never put the mail password in `.env`.** Run `./setup-mail.sh` (or
double-click **Setup Mail.command** in Finder) and it goes into the macOS
Keychain instead, encrypted at rest and unlocked by your macOS login. The
Keychain is checked first either way. **Check Mail Login.command** works out
which username format the server actually accepts.

`ecosine-profile.json` is who AHMED thinks you are — your name, your role, your
employer, how you want to be addressed and written for. The server re-reads it
on every single request, so an edit takes effect without a restart. It is the
one place to change what the assistant knows about you. Leave it out and the
assistant still runs; it just does not know who you are.

`ecosine-team.json` lists the people who file a daily sheet, and which
specialist follows each of them up. It is read fresh whenever a report runs.
Leave it out and the weekly report simply comes back without a daily section.

`ecosine-locations.json` names the workshops, depots and yards your vehicle
sheet refers to, with coordinates, plus the alternate spellings each one shows
up under. Leave it out and locations are reported exactly as the sheet writes
them.

| Variable | Purpose |
|---|---|
| `TIMEZONE`, `PLACE_NAME` | Where you are. Drives the clock, the Friday report deadline and the briefing weather. Defaults to `Asia/Dubai` / `Dubai` |
| `PLACE_LAT`, `PLACE_LON` | Coordinates for the morning weather lookup |

## The specialist team

AHMED delegates departmental questions rather than answering them himself. Each
specialist has its own persona, its own MiniMax voice, and its own folder.

| Agent | Remit |
|---|---|
| **Tom** | HR, staff KPIs, UAE Labour Law, MoHRE, WPS, Emiratisation |
| **Oliver** | Limousine fleet operations, drivers, downtime, RTA |
| **Arthur** | Spare parts pricing, garage vs agency quotes |
| **Harry** | Sales performance by rep, EV expansion, hotel contracts |

Reports are read from `~/Documents/Weekly Report/` and written to
`~/Documents/Executive_Reports/`. One folder per agent; inside it, one folder
per person they follow up with, plus an optional `<Agent> inputs/` folder of
standing reference data. An empty person folder is not ignored — the agent
reports that person by name as not having filed, which is usually the more
useful half of the answer.

Round 0 of a departmental turn is a **forced** `delegate_to_agent` tool call
(`tool_choice`). That is deliberate and load-bearing: three successive
prompt-only attempts to stop the fast brain from inventing a specialist's
answer all failed. Forcing the first round to be a tool call leaves no text
turn in which anything can be fabricated.

## Tools

Files and documents
: `search_files`, `list_folder`, `list_recent`, `read_document`, `read_pdf`,
  `ocr_document`, `open_file`, `reveal_in_finder`, `preview_image`,
  `write_file`, `edit_file`

Mail
: `search_email`, `read_email`, `read_email_message`, `send_email`

HR
: `expiry_radar` — scans `STAFF DOCUMENTS/<entity>/<employee>/` for visas,
  Emirates IDs, labour cards, passports, insurance and licences that have
  expired or are about to. `deep:true` opens the PDFs and reads the dates
  printed inside.
: `uae_gratuity` — end-of-service under Federal Decree-Law 33/2021. 21 days'
  basic wage per year for years 1–5, 30 days after that, capped at two years'
  basic, entitlement from one year. The old ⅓/⅔ resignation penalty was
  **abolished in February 2022**; most online calculators are still wrong on
  this.

Fleet and assets
: `vehicle_status`, `employee_assets`

Reporting
: `delegate_to_agent`, `read_department_reports`, `weekly_executive_report`,
  `export_report_pdf`, `daily_briefing`

Other
: `web_search`, `system_info`

## Zero-dependency file handling

The whole Python-library stack — pandas, python-docx, pypdf, reportlab — was
deliberately not used. Everything below is verified working on this Mac with
nothing installed:

- **`.docx` / `.doc` / `.rtf`** → `textutil -convert txt -stdout`, built into macOS
- **`.xlsx` / `.xls`** → Python stdlib `zipfile` + `xml.etree` reading
  `sharedStrings.xml` and the sheet XML directly (`ecosine-xlsx.py`)
- **`.pdf`** → `osascript -l JavaScript` + PDFKit, which handles Arabic
- **Scanned images and image-only PDFs** → macOS Vision OCR via JXA
  (`ecosine-ocr.js`), `recognitionLanguages: ['en-US','ar-SA']`. Scanned PDFs
  are rasterised with `sips` first
- **PDF *output*** → Chrome headless `--print-to-pdf` against generated HTML.
  `cupsfilter` is present but fails on HTML; Chrome gives real typography,
  tables and pagination at no dependency cost

### Things that cost time to find out

- UAE bilingual PDFs put the label **after** the value —
  `"15-02-2024  2024-02-15 : Valid Until"`. A forward-only anchor search misses
  every one of them.
- Within an expiry window, take the **latest** date. Issue date and date of
  birth are always earlier and sit on either side of the label, so
  distance-to-anchor heuristics pick the wrong one.
- OCR mangles date separators: `16/12/2027` comes back as `1611212027`.
  `repairOcrDates()` rewrites it, but only when day ≤ 31 and month ≤ 12, so
  permit numbers survive.
- Scans are named by whatever took them (`PHOTO-2026-02-11.jpg`,
  `WhatsApp Image …`), so keyword classification was excluding them *before*
  OCR could run and they stayed invisible. Any image inside a staff folder is
  now admitted as "Scan (unlabelled)" and named from its OCR'd contents
  instead. Adding OCR took expired-document detection from 5 to **30**.
- macOS PDFKit returns Arabic in presentation forms, so standard-form Arabic
  regexes never match. The English label is the reliable anchor.
- macOS screenshot filenames contain U+202F, a narrow no-break space, not a
  regular space. Hand-typed paths silently 404. Always take the path from a
  real directory listing.

## Layout

```
Ecosine.html               front end, self-contained
ecosine-server.js          companion server, Node stdlib only
ecosine-profile.example.json    template — who AHMED thinks you are
ecosine-team.example.json       template — who files a daily sheet
ecosine-locations.example.json  template — workshops and depots, with coordinates
ecosine-logo.html          branding
ecosine-ocr.js             macOS Vision OCR via JXA
ecosine-xlsx.py            .xlsx reader, stdlib zipfile + xml.etree
ecosine-mail.py            IMAP + SMTP, stdlib
ecosine-fleet.py           vehicle status
ecosine-assets.py          company assets by employee
ecosine-daily.py           reads the daily sheets individuals fill in
make-report-templates.py   generates the weekly report templates
setup-mail.sh              puts the mail password in the macOS Keychain
```

`.gitignore` is an allowlist rather than a list of exclusions: it ignores
everything by default and re-admits only the files listed above, so `git add -A`
cannot sweep in
neighbouring checkouts, `.env`, or any of the three filled-in config files.
