# Barcoding Application — Design Spec

**Date:** 2026-05-19
**Status:** Superseded in part — see `2026-06-11-production-hardening.md` for the
current barcode format (insert field is now 0-4), safety guards, vector
rendering, per-piece accountability, and watched intake directories.
**Stack:** Python + FastAPI + SQLite + Jinja2/HTMX

## Overview

A local web application that generates and applies 2D DataMatrix barcodes to compiled documents for intelligent inserting machines. Runs on Windows 10/11 (including WSL). Single-user with occasional handoff — profile switching without authentication.

## Barcode Format

13-character numeric string:

| Position | 1 | 2 | 3 | 4 | 5-13 |
|---|---|---|---|---|---|
| Field | End of Group | Sheet # | Insert | Set Count | Unique ID |
| Type | Binary (0/1) | Integer (1-9) | Integer (0-4) | Integer (1-9) | 9-digit |
| Example | 0 | 3 | 0 | 7 | 158404144 |

- **End of Group (pos 1):** 1 on the last sheet fed into the machine. Placement depends on feed direction.
- **Sheet # (pos 2):** Current sheet, 1-based from logical first page, always counts 1,2,3 regardless of feed direction.
- **Insert (pos 3):** number of insert pockets to feed, 0-4 (machines have four pockets; updated 2026-06-11, previously binary 0/1). Set per job/preset/template before processing — no auto-detection.
- **Set Count (pos 4):** Total sheets in this document set (1-9, capped by 6-sheet machine limit).
- **Unique ID (pos 5-13):** 9-digit identifier unique to each document set. Sequential, account number, or file number. Auto-pads/right-justifies if shorter.

### Feed Direction

- **Ascending (first-to-last):** Sheets fed 1→2→3. EOG on logically-last sheet. Sheet counter sequential.
- **Descending (last-to-first):** Sheets fed 3→2→1. EOG on logically-first sheet (fed last). Sheet counter still 1,2,3 — machine detects out-of-sequence errors.
- Feed direction is a per-run setting, stored on Preset or Template.

### Sheet Limit

The inserting machines mechanically max out at ~6 sheets. Any document set exceeding 6 sheets is flagged, separated into a `manual_overflow` output directory, and excluded from the machine-ready batch. These documents still receive barcodes but are set aside for manual processing. Documents are never split.

## Architecture

```
FastAPI (REST + WebSocket) → Service Layer → Storage (SQLite + filesystem)
         ↓
   Jinja2 + HTMX + vanilla JS (browser UI)
```

### Project Structure

```
barcoding-app/
├── app/
│   ├── main.py              # FastAPI app, startup, routes
│   ├── config.py            # Settings, port, paths
│   ├── db.py                # SQLAlchemy models + session
│   ├── routes/
│   │   ├── jobs.py          # Job CRUD + processing endpoints
│   │   ├── templates.py     # Preset/template management
│   │   └── files.py         # Upload, SFTP, directory browse
│   ├── services/
│   │   ├── barcode.py       # Barcode string + DataMatrix image generation
│   │   ├── pdf_reader.py    # Text extraction, region queries
│   │   ├── pdf_writer.py    # Embed barcode + text into PDF
│   │   ├── detector.py      # Pattern detection from regions
│   │   ├── template.py      # Template CRUD, apply to docs
│   │   ├── job.py           # Orchestration: ingest → detect → embed → report
│   │   ├── sftp.py          # SFTP connect, list, download
│   │   ├── watcher.py       # Directory monitor (watchdog)
│   │   └── reporter.py      # Output report + verification
│   ├── templates/           # Jinja2 HTML templates
│   └── static/              # CSS, JS, images
├── tests/
├── requirements.txt
└── pyproject.toml
```

### Tech Choices

| Layer | Choice | Reason |
|---|---|---|
| Framework | FastAPI + Uvicorn | Async, auto-docs, WebSocket for progress |
| PDF Read | pdfplumber / pypdf | Best text extraction for machine-generated PDFs |
| PDF Write | pypdf / reportlab | Embed barcode images, overlay text |
| Barcode | treepoem or pylibdmtx | DataMatrix ECC200 generation |
| SFTP | Paramiko | Mature, no extra dependencies |
| Database | SQLite + SQLAlchemy | Zero config, single file, portable |
| Frontend | Jinja2 + HTMX + vanilla JS | No Node.js, no build step |
| Word→PDF | python-docx → LibreOffice headless | Converts .docx before processing |

## Data Model

### Preset (manual mode)
Stores fixed barcode parameters for recurring jobs where parameters are identical every run.

```
Preset
  id: int (PK)
  name: str
  sheets_per_doc: int       # 1-6
  has_insert: bool
  feed_direction: enum      # ASCENDING | DESCENDING
  id_source: enum           # SEQUENTIAL | MANUAL_ENTRY
  embed_config: JSON        # Barcode + human-readable position config
  created_at: datetime
  updated_at: datetime
```

### Template (auto-detect mode)
Stores region definitions and detection rules for automatic parameter extraction from variable documents.

```
Template
  id: int (PK)
  name: str
  description: str
  has_insert: bool
  feed_direction: enum
  embed_config: JSON
  created_at: datetime
  updated_at: datetime

Region
  id: int (PK)
  template_id: int (FK → Template)
  name: str
  role: enum                # GROUP_BOUNDARY | PAGE_COUNTER | UNIQUE_ID | CUSTOM
  page: int                 # Which page (usually 1)
  x, y, width, height: float  # Absolute position in PDF points
  match_type: enum          # EXACT | REGEX | NUMERIC
  match_pattern: str
  priority: int             # Evaluation order
```

### Job & Results

```
Job
  id: int (PK)
  name: str
  session_id: str
  date: date
  source_type: enum         # LOCAL_DIR | SFTP
  source_path: str
  preset_id: int? (FK)
  template_id: int? (FK)
  status: enum              # DRAFT | PROCESSING | COMPLETE | ERROR
  created_at: datetime
  completed_at: datetime?

JobResult
  id: int (PK)
  job_id: int (FK → Job)
  total_barcodes: int
  total_documents: int
  total_sheets: int
  overflow_docs: int
  insert_count: int
  verification: enum        # OK | MISMATCH | ERROR
  report_path: str
  output_dir: str
  created_at: datetime
```

### Embed Config (JSON)

```json
{
  "barcode": {
    "anchor": "bottom-right",
    "x_offset": 36,
    "y_offset": 36,
    "pixel_width": 300
  },
  "human_readable": {
    "enabled": true,
    "x": 36,
    "y": 400,
    "rotation": 90,
    "font_name": "Courier",
    "font_size": 8
  }
}
```

## Service Layer

### BarcodeService
- `generate_barcode_string(unique_id, sheet_number, set_count, has_insert, is_end_of_group) → str`
- `generate_barcode_image(barcode_string, pixel_width) → PIL.Image`
- `validate_barcode_string(barcode_string) → bool`
- `batch_generate(documents, feed_direction) → list[SheetBarcode]`

### PDFReaderService
- `render_page_preview(pdf_path, page_num) → bytes` — PNG for region selection UI
- `extract_text_in_regions(pdf_path, page_num, regions) → dict`
- `get_page_count(pdf_path) → int`

### PDFWriterService
- `embed_barcode(pdf_path, page_num, barcode_image, position, size) → bytes`
- `embed_human_readable(pdf_path, page_num, text, position, font, rotation) → bytes`
- `process_document(input_path, barcodes, embed_config, output_path) → None`

### DetectorService
- `detect_from_regions(pdf_path, regions, page_range) → list[DetectedDoc]`
  - Side-A pages only (odd page numbers). Even pages skipped for detection.
  - Group boundary: address change → new document set
  - Page counter: extract "Page X of Y" → sheet number + set count
  - Unique ID: extract account/file number → 9-digit barcode ID
- `validate_consistency(detected, expected) → VerificationResult`

### JobService (orchestration)
Pipeline: Ingest → Detect → Classify → Generate → Embed → Verify & Report
1. **Ingest:** Load source documents (local or SFTP). Convert Word to PDF if needed. Build document list.
2. **Detect:** If Template, scan side-A pages through regions. If Preset, apply fixed parameters.
3. **Classify:** Split into ≤6 sheets (machine-ready) and >6 sheets (manual overflow).
4. **Generate:** Create 13-char barcode strings and DataMatrix images per sheet.
5. **Embed:** Overlay barcode + optional human-readable text onto PDFs per embed_config.
6. **Verify & Report:** Compare output against imported batch data. Mark OK or ERROR.

### SFTP Service (Paramiko)
- Stored connection configs (host, port, username, key file or password)
- Browse remote directory, select files/directories for download
- Downloads to local staging before processing
- Optional polling for new files (opt-in per connection)
- No automatic upload back — output stays local

### Watcher Service (watchdog)
- Background thread monitoring configured directories
- Auto-triggers job using pre-assigned template/preset when new files appear
- File stability check: 5 minutes (file size unchanged for 300s before processing)
- File name pattern filter, max file size limit
- Error quarantine: failed jobs go to review queue, don't halt watcher
- Enable/disable per watch from UI

## Web UI — Pages

1. **Home / Jobs:** List of past jobs with status badges. New Job, Resume, View Report buttons.
2. **New Job Wizard:** Step-by-step: name/session → source → preset/template → batch data import → review & run. WebSocket progress bar.
3. **Template Editor:** Upload sample PDF → rendered page with click-drag region selection → set roles + match patterns → test detection → configure barcode placement → save.
4. **Presets:** Simple form for fixed-parameter jobs. List/grid with quick-select.
5. **Job Detail / Report:** Verification summary with OK/ERROR badge. Overflow document list. Download output. Combine with previous job option.

### Region Selection (Client-Side)
- Server renders PDF page as PNG at known DPI
- Vanilla JS: mousedown → mousemove → mouseup for rectangle drawing
- Pixel coordinates converted to PDF points server-side
- "Test Region" button extracts text from selected area for verification
- Coordinates stored as absolute values (documents are position-consistent per template)

## Output Structure

```
<source_dir>/<Name>_<ID>_<Date>/
├── machine_ready/            # Docs ≤6 sheets, barcoded
├── manual_overflow/          # Docs >6 sheets, barcoded but flagged
├── combined_output.pdf       # Optional: all machine_ready merged
└── report.json               # Verification report
```

### Verification Report

```json
{
  "job": "Daily Processing — 2026-05-19",
  "session_id": "20260519-DAILY",
  "status": "OK",
  "totals": {
    "documents_processed": 847,
    "total_sheets": 2142,
    "total_barcodes": 2142,
    "inserts_triggered": 312,
    "overflow_documents": 3
  },
  "verification": {
    "match": true,
    "verdict": "OK"
  },
  "overflow_detail": [...],
  "warnings": []
}
```

Verification compares processed output counts against any imported prerequisite batch data. A mismatch produces an ERROR verdict with a specific discrepancy description.

## Edge Cases

| Case | Handling |
|---|---|
| Document >6 sheets | Flag, separate to manual_overflow, do not split |
| Single-sheet document | Sheet 1 is both first and last — EOG always 1, set count = 1 |
| Empty source directory | Warn user, don't silently succeed with zero output |
| Region detection failure | Flag as warning, don't halt job — user reviews and decides |
| Output directory exists | Ask: overwrite, append, or new name |
| Word docs in batch | Auto-convert via LibreOffice headless before processing |
| SFTP connection failure | Retry with exponential backoff, surface error to user |
| Duplicate unique IDs in batch | Reject with error message |
| Non-numeric unique ID source | Strip non-digits, warn if truncation occurs |

## Session Combination

After processing, user can optionally combine current output with a previous job's output. Merges machine_ready PDFs into a single combined file so all daily documents can be printed and mailed together. Explicit user action — not automatic.

## Profile Switching

No authentication. Simple profile name selection from dropdown at app startup (or settings page). Profile determines default paths, SFTP connections, and job history view. SQLite stores all profiles in one database, partitioned by profile name.

## Testing Strategy

- **Unit tests:** Each service module independently (barcode generation, PDF parsing, detection logic, report generation)
- **Integration tests:** End-to-end pipeline with sample PDFs (known output vs. expected)
- **Manual verification:** Template creation workflow with real document samples for each recurring job type
