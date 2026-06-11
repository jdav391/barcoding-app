# Braze Codes

Generates and applies 2D Data Matrix barcodes to compiled mail documents to
control high-speed intelligent inserting machines. Parses incoming PDFs to
find mailpiece boundaries, computes per-sheet control payloads (collation,
inserts, diverts), stamps vector barcodes onto each side-A page, and produces
machine-ready output with full per-piece accountability.

Local single-user web app: **Python 3.14 / FastAPI / SQLite / Jinja2+HTMX**,
with pdfplumber (extraction), pypdf + ReportLab (output), pylibdmtx (ECC200).

## Running

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. Tests: `.venv/bin/python -m pytest` (219 tests).

## Barcode format

13 characters (14 with the optional divert character), Data Matrix ECC200
18x18, printed as vector rectangles at exactly `module_size_mm` (default
0.50mm) with an opaque quiet zone (default 6.5mm).

| Position | 1 | 2 | 3 | 4 | (5) | last 9 |
|---|---|---|---|---|---|---|
| Field | End of Group | Sheet # | Insert pockets | Set Count | Divert | Unique ID |
| Range | 0/1 | 1-9 | 0-4 | 1-9 | 0/1 | 9 digits |

Feed direction (ascending/descending) controls which sheet carries EOG.
Unique IDs come from a claimed sequential range or are extracted from the
document; duplicates within a job abort the run.

## Processing modes

- **Preset** — fixed sheets-per-document; the PDF must divide evenly.
- **Template** — region-based detection: GROUP_BOUNDARY regions segment
  recipients by text-signature changes, PAGE_COUNTER regions cross-check the
  detected span ("Page X of Y" disagreement aborts), UNIQUE_ID regions
  extract account/file numbers.

Both run through one pipeline with fail-closed guards: payload range
enforcement, duplicate-UID detection, sheet-capacity limits, clear-zone
inspection under the barcode footprint, count verification against imported
batch manifests (MISMATCH quarantines the deliverable), and refusal to
overwrite prior output. See `docs/2026-06-11-production-hardening.md` for the
complete guard list.

## Watched intake (hands-off processing)

Give a template a **Watched Intake Directory** (template form). PDFs dropped
there are picked up once stable, moved to `ingested/`, and processed
automatically with that template — one directory per template, so a batch can
never run with the wrong settings. Failures leave a `<name>.ERROR.txt` marker
next to the file.

## Output (per job)

```
<name>_<session>_<date>/
├── machine_ready/           # barcoded docs within machine sheet limits
├── manual_overflow/         # barcoded docs above the overflow threshold
├── report.json / report.pdf # totals, verification verdict, warnings
├── mail_run_data.csv        # per-piece manifest (UID, sheets, barcodes, flags)
├── combined_output.pdf      # cover + docs + end sheet — only when verification is OK
└── QUARANTINED_DO_NOT_MAIL.txt  # written instead, on count mismatch
```

Every processed piece is also recorded in the `mail_pieces` table (the
accountability backbone: totals, resume, session compile, and the manifest
all derive from it).

## Configuration (environment, prefix `BARCODE_`)

| Variable | Default | |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./barcoding.db` | |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | |
| `OVERFLOW_THRESHOLD` | `6` | sheets above this go to `manual_overflow/` |
| `MAX_SHEETS_PER_DOC` | `9` | detection merge-guard ceiling |
| `CLEAR_ZONE_MODE` | `warn` | `off` / `warn` / `abort` |
| `WATCH_ENABLED` | `true` | intake watcher |
| `WATCH_POLL_SECONDS` | `5.0` | |
| `ALLOWED_BROWSE_ROOTS` | user home | file-browser jail |
| `SMTP_HOST/PORT/USERNAME/PASSWORD` | gmail/587/— | report emails |

## Project layout

```
app/
├── main.py            # FastAPI app, page routes, lifespan (DB init + watcher)
├── config.py          # pydantic-settings
├── database.py        # engine, session, additive SQLite migrations
├── models.py          # Session, Preset, Template, Region, Job, JobResult,
│                      # BatchImport, MailPiece, SequenceCounter
├── routes/            # REST + WebSocket endpoints (jobs, templates, presets,
│                      # files, sessions, wizard, batch_import)
└── services/
    ├── barcode.py     # payload build/validate, ECC200 module matrix
    ├── detector.py    # template-mode boundary detection (single-open)
    ├── pdf_splitter.py# preset-mode splitting
    ├── pdf_writer.py  # vector stamping, rotation/MediaBox handling, merging
    ├── clear_zone.py  # content-under-barcode inspection
    ├── job.py         # pipeline: guards, stamping, MailPiece, report, manifest
    ├── watcher.py     # per-template intake directories
    ├── sequence.py    # unique-ID range claims
    ├── reporter.py / report_pdf.py / session_report.py
    ├── session.py     # multi-job session compile
    ├── batch_import.py# expected-count parsing (email text / CSV)
    └── email.py       # SMTP report delivery
docs/                  # dated design/implementation specs (see below)
tests/                 # 219 tests, pytest
```

## Documentation index

| Doc | Scope |
|---|---|
| `docs/2026-05-19-barcoding-app-design.md` | Original system design (partially superseded) |
| `docs/2026-05-19-barcoding-app-phase1*.md` | Initial build: presets, pipeline, reports |
| `docs/2026-05-20-barcoding-app-phase2*.md` | PDF certification reports + email |
| `docs/2026-06-11-production-hardening.md` | **Current:** safety guards, insert 0-4, vector rendering, MailPiece accountability, throughput, watched intake |
