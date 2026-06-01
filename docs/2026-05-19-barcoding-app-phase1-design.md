# Barcoding Application — Phase 1 Design Spec

**Date:** 2026-05-19
**Status:** Draft
**Parent spec:** [Full application spec](2026-05-19-barcoding-app-design.md)
**Stack:** Python + FastAPI + SQLite + Jinja2/HTMX
**Project path:** /Volumes/NVME4TB/Users/joeldavidson/projects/barcoding-app
**Runtime:** Windows 10/11 (native Python). Developed on macOS, all dependencies must be Windows-compatible.

## Scope

Phase 1 delivers **manual preset mode**: fixed-parameter barcode generation and embedding into large multi-page PDFs. One job per source PDF. No auto-detect, no SFTP, no directory watching, no profile switching.

### In scope

- Project scaffolding (FastAPI + SQLite + HTMX)
- Preset CRUD (create, edit, delete, list)
- Rolling SequenceCounter for unique IDs
- BarcodeService (13/14-char string generation + DataMatrix ECC200 images)
- PDF splitting by fixed sheet count (duplex and simplex aware)
- PDF embedding (barcode image + optional human-readable text on side-A pages)
- Batch data import (manual entry, paste-and-parse from email text, CSV upload)
- Server-side file browser for source PDF selection
- Output directory with machine_ready/, manual_overflow/, combined_output.pdf
- Verification report comparing output against imported batch data
- Job history with status tracking and resume from partial failure
- Optional divert character support (extends barcode to 14 chars)

### Out of scope (Phase 2+)

- Template mode / auto-detect / region selection UI
- SFTP connections and remote file access
- Directory watcher for automatic processing
- Session/job combination (merging outputs across jobs)
- Profile switching
- Word document conversion (LibreOffice headless)

## Source Document Model

Each source is a single large multi-page duplex-formatted PDF containing many document sets back-to-back. A batch of 300 single-sheet letters arrives as one 600-page PDF (each letter = 2 PDF pages: side A + side B). Typically 4-5 source PDFs are processed per day, each as its own job.

**Page format (per preset):**
- **Duplex (default):** `pdf_pages_per_set = sheets_per_doc x 2`
- **Simplex:** `pdf_pages_per_set = sheets_per_doc x 1`

Source PDFs are never modified. All output is written to a new directory.

## Barcode Format

13- or 14-character numeric string (14 when optional divert character is enabled).

### Standard format (13 characters)

| Position | 1 | 2 | 3 | 4 | 5-13 |
|---|---|---|---|---|---|
| Field | End of Group | Sheet # | Insert | Set Count | Unique ID |
| Type | Binary (0/1) | Integer (1-9) | Binary (0/1) | Integer (1-9) | 9-digit |

### Extended format with divert (14 characters)

| Position | 1 | 2 | 3 | 4 | 5 | 6-14 |
|---|---|---|---|---|---|---|
| Field | End of Group | Sheet # | Insert | Set Count | Divert | Unique ID |
| Type | Binary (0/1) | Integer (1-9) | Binary (0/1) | Integer (1-9) | Binary (0/1) | 9-digit |

### Field definitions

- **End of Group (pos 1):** 1 on the last sheet fed into the machine. Placement depends on feed direction (ascending: EOG on last sheet; descending: EOG on first sheet).
- **Sheet # (pos 2):** Current sheet, 1-based, always counts 1,2,3 regardless of feed direction.
- **Insert (pos 3):** 1 triggers additional insert pocket. Manually toggled per preset.
- **Set Count (pos 4):** Total sheets in this document set (1-9).
- **Divert (pos 5, optional):** 1 triggers machine divert bin. Enabling extends barcode to 14 characters — the inserting machine must be reprogrammed for the extended format.
  - Quadient DS-1200: divert bin before folding mechanism (ideal for overflow).
  - B&H Forerunner: divert bin after folding mechanism (overflow docs should still be physically separated).
- **Unique ID (pos 5-13 or 6-14):** 9-digit identifier. Sequential rolling counter or extracted from document. Zero-padded / right-justified if shorter.

### Feed direction

- **Ascending (first-to-last):** Sheets fed 1->2->3. EOG on logically-last sheet.
- **Descending (last-to-first):** Sheets fed 3->2->1. EOG on logically-first sheet (fed last).
- Sheet counter always sequential (1,2,3) regardless of feed direction.

### Sheet limit

Overflow threshold is **6 sheets** — the mechanical folding/inserting limit of the Quadient DS-1200 and B&H Forerunner. Documents exceeding 6 sheets are separated to `manual_overflow/` and optionally marked with divert=1 in their barcode. Documents are never split.

### Physical specs (DataMatrix ECC200)

Defaults satisfy Quadient DS-1200 published requirements (BCR Reading Reference Guide Rev 2.0, Nov 2024).

| Parameter | Default | Notes |
|---|---|---|
| Symbol size | 18x18 modules | Fits 36 numeric digits; 13-14 chars with strong ECC |
| Module size | 0.50 mm | Quadient range: 0.35-0.50 mm |
| Physical barcode | 9.0 x 9.0 mm | Under 30 mm max |
| Quiet zone | 6.5 mm all sides | Quadient requirement |
| Total footprint | ~22 x 22 mm | Barcode + quiet zone |
| Print DPI | 600 (preferred) | 12 px/module at 0.50 mm |
| Pixel dimensions (600 DPI) | 216x216 px barcode, ~520x520 px with quiet zone | |
| Edge clearance | >=7 mm from leading/trailing edge | Quadient requirement |
| Orientation | Any | DataMatrix is omnidirectional |
| Color | Black on white | Maximum contrast |

## Architecture

```
FastAPI (REST + WebSocket) -> Service Layer -> Storage (SQLite + filesystem)
         |
   Jinja2 + HTMX + vanilla JS (browser UI)
```

### Project structure

```
barcoding-app/
├── app/
│   ├── main.py              # FastAPI app, startup, routes
│   ├── config.py            # Settings, port, paths
│   ├── db.py                # SQLAlchemy models + session
│   ├── routes/
│   │   ├── jobs.py          # Job CRUD + processing endpoints
│   │   ├── presets.py       # Preset management
│   │   ├── batch_import.py  # Batch data import endpoints
│   │   └── files.py         # File browser API
│   ├── services/
│   │   ├── barcode.py       # Barcode string + DataMatrix image generation
│   │   ├── pdf_splitter.py  # Split large PDF into document sets
│   │   ├── pdf_writer.py    # Embed barcode + text into PDF
│   │   ├── batch_import.py  # Parse email text, CSV, manual entry
│   │   ├── job.py           # Orchestration pipeline
│   │   └── reporter.py      # Output report + verification
│   ├── templates/           # Jinja2 HTML templates
│   └── static/              # CSS, JS
├── tests/
├── requirements.txt
└── pyproject.toml
```

### Tech choices

| Layer | Choice | Reason |
|---|---|---|
| Framework | FastAPI + Uvicorn | Async, auto-docs, WebSocket for progress |
| PDF Read | pdfplumber / pypdf | Page count, text extraction for future phases |
| PDF Write | pypdf / reportlab | Embed barcode images, overlay text |
| Barcode | treepoem or pylibdmtx | DataMatrix ECC200 generation |
| Database | SQLite + SQLAlchemy | Zero config, single file, portable |
| Frontend | Jinja2 + HTMX + vanilla JS | No Node.js, no build step |

## Data Model

### SequenceCounter

Persistent rolling counter for unique IDs. Each job claims a range atomically.

```
SequenceCounter
  id: int (PK)
  name: str                  # "global" default; named counters optional
  last_value: int            # Next job starts at last_value + 1
  updated_at: datetime
```

### Preset

Fixed barcode parameters for recurring jobs.

```
Preset
  id: int (PK)
  name: str
  sheets_per_doc: int        # 1-6
  page_format: enum          # DUPLEX | SIMPLEX
  has_insert: bool
  has_divert: bool           # Enable divert character (14-char barcode)
  divert_overflow: bool      # Auto-set divert=1 on overflow docs
  feed_direction: enum       # ASCENDING | DESCENDING
  id_source: enum            # SEQUENTIAL | DOCUMENT_EXTRACT
  embed_config: JSON         # Barcode + human-readable position config
  created_at: datetime
  updated_at: datetime
```

### Job

```
Job
  id: int (PK)
  name: str
  session_id: str
  date: date
  source_path: str
  preset_id: int (FK -> Preset)
  status: enum               # DRAFT | PROCESSING | PARTIAL | COMPLETE | ERROR
  last_processed_index: int? # For resume: last successfully processed doc set
  total_doc_sets: int?       # Total document sets detected in source
  created_at: datetime
  completed_at: datetime?
```

### JobResult

```
JobResult
  id: int (PK)
  job_id: int (FK -> Job)
  total_barcodes: int
  total_documents: int
  total_sheets: int
  overflow_docs: int
  diverts_triggered: int
  insert_count: int
  verification: enum         # OK | MISMATCH | ERROR
  report_path: str
  output_dir: str
  created_at: datetime
```

### BatchImport

Imported expected data for verification. One row per batch line (from email, CSV, or manual entry).

```
BatchImport
  id: int (PK)
  job_id: int (FK -> Job)
  batch_id: str              # e.g. "LetterBatch798236"
  source_filename: str       # e.g. "LetterBatch798236.pdf"
  expected_letters: int
  expected_sheets: int
  sheets_per_doc: int
  print_type: str            # "Double sided color", "Single sided black and white", etc.
  has_insert: bool
  insert_description: str?   # e.g. "Donation Inserts"
  import_method: enum        # MANUAL | PASTE | CSV
  raw_text: str?             # Original pasted text, for audit
  created_at: datetime
```

### Embed Config (JSON stored on Preset)

```json
{
  "barcode": {
    "anchor": "bottom-right",
    "x_offset_pt": 36,
    "y_offset_pt": 36,
    "module_size_mm": 0.50,
    "quiet_zone_mm": 6.5,
    "dpi": 600
  },
  "human_readable": {
    "enabled": true,
    "anchor": "bottom-left",
    "x_offset_pt": 36,
    "y_offset_pt": 36,
    "rotation": 90,
    "font_name": "Courier",
    "font_size": 8
  }
}
```

Offsets are in PDF points (1 pt = 1/72 inch), measured inward from the anchor corner. For example, "bottom-right" with x_offset_pt=36 and y_offset_pt=36 places the barcode 0.5 inches from the right edge and 0.5 inches from the bottom edge. Anchor options: top-left, top-right, bottom-left, bottom-right.

## Service Layer

### BarcodeService

- `generate_barcode_string(unique_id, sheet_number, set_count, has_insert, is_end_of_group, divert=None) -> str`
- `generate_barcode_image(barcode_string, module_size_mm, quiet_zone_mm, dpi) -> PIL.Image`
- `validate_barcode_string(barcode_string) -> bool`
- `batch_generate(doc_sets, feed_direction, has_divert) -> list[SheetBarcode]`

### PDFSplitterService

- `split_by_preset(pdf_path, sheets_per_doc, page_format) -> list[DocSet]`
  - DocSet contains: start_page, end_page, sheet_count, page_indices for side-A pages
- `validate_page_count(pdf_path, sheets_per_doc, page_format) -> ValidationResult`
  - Returns error if page count doesn't divide evenly, with the math shown

### PDFWriterService

- `embed_barcode(pdf_path, page_num, barcode_image, embed_config) -> bytes`
- `embed_human_readable(pdf_path, page_num, text, embed_config) -> bytes`
- `process_document(input_path, page_range, barcodes, embed_config, output_path) -> None`
- `merge_pdfs(pdf_paths, output_path) -> None` — for combined_output.pdf

### BatchImportService

- `parse_email_text(text) -> list[BatchImportData]`
  - Parses: `Sent file: <name>.pdf, Letters: <n>, Total Sheets: <n>, [<n> sheets per envelope,] Print type: <type>[, Insert: <desc>]`
- `parse_csv(file) -> list[BatchImportData]`
- `validate_import(data) -> list[ValidationWarning]`

### JobService (orchestration)

Pipeline: Split -> Generate -> Embed -> Merge -> Verify & Report

1. **Split:** Validate page count divides evenly. Split source PDF into document sets using preset parameters. Classify into machine-ready (<=6 sheets) and overflow (>6 sheets).
2. **Generate:** Claim sequential IDs from SequenceCounter. Create barcode strings per sheet, applying feed direction, insert, and divert flags. Generate DataMatrix images.
3. **Embed:** For each document set, overlay barcode + optional human-readable text onto side-A pages. Write individual barcoded PDFs to output directory (machine_ready/ or manual_overflow/).
4. **Merge:** Combine all machine_ready PDFs into combined_output.pdf.
5. **Verify & Report:** Compare output counts against imported batch data. Write report.json with OK/ERROR verdict.

Progress updates sent via WebSocket at each document set processed.

### ReporterService

- `generate_report(job, job_result, batch_imports) -> dict`
- `verify_against_imports(job_result, batch_imports) -> VerificationResult`
  - Compares: total documents, total sheets, sheets_per_doc, insert presence
  - OK if all match; ERROR with specific discrepancy description if mismatch

## Web UI

### Pages

1. **Home / Jobs** — List of past jobs with status badges (Complete, Error, Partial). New Job button. Click job to view report.
2. **New Job Wizard** — 5-step HTMX wizard (no full page reloads):
   - Step 1: Name & Date (auto-suggested from batch ID if available, date defaults to today)
   - Step 2: Import Batch Data (three tabs: paste email text, upload CSV, manual entry form. Parsed data previewed in table.)
   - Step 3: Select Source PDF (server-side file browser with directory navigation. Shows page count as sanity check.)
   - Step 4: Select or Create Preset (list of existing presets, or inline create form. Paste-and-parse data auto-suggests values.)
   - Step 5: Review & Run (summary of all settings. Start button. WebSocket progress bar.)
3. **Presets** — List/grid of saved presets with edit/delete. Simple form for new presets.
4. **Job Report** — Verification summary with OK/ERROR badge. Totals table. Overflow document list. Download combined_output.pdf.

### File browser (server-side)

FastAPI endpoint returns directory listings as JSON. HTMX renders navigable folder/file list. PDF files show page count on selection. Configurable root paths to restrict browsing scope.

## Output Structure

```
<source_dir>/<JobName>_<SessionID>_<Date>/
├── machine_ready/            # Barcoded PDFs, <=6 sheets each
├── manual_overflow/          # Barcoded PDFs >6 sheets, flagged
├── combined_output.pdf       # All machine_ready merged in processing order
└── report.json               # Verification report
```

### Verification report format

```json
{
  "job": "Daily Letters - 2026-05-19",
  "session_id": "20260519-001",
  "status": "OK",
  "totals": {
    "documents_processed": 296,
    "total_sheets": 592,
    "total_barcodes": 592,
    "inserts_triggered": 0,
    "diverts_triggered": 0,
    "overflow_documents": 0
  },
  "verification": {
    "expected_letters": 296,
    "actual_documents": 296,
    "expected_sheets": 592,
    "actual_sheets": 592,
    "match": true,
    "verdict": "OK"
  },
  "overflow_detail": [],
  "warnings": []
}
```

## Error Handling

| Condition | Behavior |
|---|---|
| Page count doesn't divide evenly | Error before processing starts, with math shown |
| Processing failure mid-batch | Status set to PARTIAL, last_processed_index saved, output retained, user can resume |
| Empty source PDF | Warning, no silent empty output |
| Barcode generation failure on a set | Flag in report, continue with remaining sets |
| Output directory already exists | Prompt: overwrite, create new name, or cancel |
| Sequence counter overflow (>999999999) | Error with message to reset counter |

## File Preservation

Source PDFs are never modified in place. All barcoded output is written to the output directory as new files. Original source files remain untouched for re-processing.

## Resume / Partial Completion

If a job fails mid-processing, the job records which document sets completed successfully (last_processed_index). Resuming picks up from the next unprocessed set. Already-embedded output files are retained. A resumed job appends to existing output and regenerates the combined PDF and report.

## Testing Strategy

- **Unit tests:** BarcodeService (string generation, validation, 13-char and 14-char formats), BatchImportService (email text parsing, CSV parsing, edge cases), PDFSplitterService (duplex/simplex math, uneven page count detection)
- **Integration tests:** End-to-end pipeline with sample duplex PDF — verify correct split, barcode placement, combined output, report accuracy
- **Manual verification:** Process a real document and scan barcodes on the DS-1200 once we have a working build
