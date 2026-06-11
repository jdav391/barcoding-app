# Production Hardening — Safety, Output Quality, Throughput & Intake

**Date:** 2026-06-11
**Status:** Implemented (branch `phase1-safety`, commits `cf1fce0`, `2b32798`, `6378f71`)
**Supersedes in part:** `2026-05-19-barcoding-app-design.md` (barcode insert field, output guarantees)

This work came out of a full architecture review focused on mis-mail risk:
the failure mode where the inserter stuffs the wrong sheets into an envelope.
Four critical paths were found and closed, then output quality, throughput,
and automated intake were addressed.

---

## 1. Barcode format change: Insert field is now 0-4

| Position | 1 | 2 | 3 | 4 | (5) | 5-13 / 6-14 |
|---|---|---|---|---|---|---|
| Field | End of Group | Sheet # | **Insert** | Set Count | Divert (optional) | Unique ID |
| Type | 0/1 | 1-9 | **0-4** | 1-9 | 0/1 | 9-digit |

- The inserters have four insert pockets; the single insert character now
  carries the pocket count (0 = none). Previously boolean 0/1.
- `Preset.insert_count`, `Template.insert_count`, `MailPiece.insert_count`
  (integer 0-4). Legacy `has_insert` booleans are kept in sync
  (`insert_count > 0`) for backward compatibility; the API still accepts
  `has_insert: true` and maps it to `insert_count = 1`.
- SQLite migration in `database.create_tables()` backfills existing rows.
- **Variable inserts** (different pocket combos per document in one batch)
  are NOT implemented. Pending: confirm whether the machines interpret the
  character as a count, bitmask, or job-table code. If job-table code
  (typical), the planned design is a per-batch CSV cross-reference
  `unique_id -> insert_code` validated for 100% coverage before stamping.
  Until then: split into separate batches per insert configuration.

## 2. Safety guards (fail closed — nothing mis-mails silently)

| Guard | Behavior | Where |
|---|---|---|
| Payload field ranges | Sheet#/SetCount 1-9, Insert 0-4, sheet ≤ set; violation raises `BarcodePayloadError` before anything prints | `barcode.generate_barcode_string` |
| Payload validation | Every emitted string re-validated in the pipeline | `job._process_pipeline` |
| Detection invariant | `sheet_count == len(side_a_pages)` always | `detector._build_doc` |
| PAGE_COUNTER cross-check | "Page X of Y" disagreeing with the detected span aborts (`DetectionError`) instead of overriding | `detector._build_doc` |
| Duplex parity | Odd page count in DUPLEX mode rejected up front | `detector.detect_from_regions` |
| Merge guard | Doc exceeding `max_sheets_per_doc` (default 9) aborts — catches adjacent recipients with identical boundary text | `detector._build_doc` |
| Empty signatures | Pages with no boundary text are treated as continuations and reported as warnings | `detector.detect_from_regions` |
| Duplicate UIDs | Any repeated effective 9-digit UID within a job aborts before stamping | `job._check_unique_ids` |
| Sheet capacity | Doc sets with <1 or >9 sheets abort (no valid barcode possible) | `job._check_doc_sets` |
| Verification gating | Count MISMATCH vs batch data: `combined_output.pdf` withheld, `QUARANTINED_DO_NOT_MAIL.txt` written | `job._process_pipeline` |
| Output protection | A fresh run refuses to overwrite a prior run's output directory | `job._has_prior_output` |
| Clear-zone inspection | Text/images under the barcode footprint reported (`warn`) or abort (`abort`); `BARCODE_CLEAR_ZONE_MODE` | `clear_zone.py` |
| Concurrency | Atomic DRAFT/PARTIAL/ERROR → PROCESSING claim prevents double-runs (REST + WebSocket) | `job.run_job` |

## 3. Per-piece accountability: `MailPiece`

One row per document set: doc index, effective UID, sheet count, page range,
overflow/insert/divert, every barcode string, output path. Written in the
same commit as the resume checkpoint (`job.last_processed_index`), so the
records are always consistent with the files on disk.

All job totals, the machine-ready merge order, the session compile order, and
the manifest are rebuilt from these rows — resumed runs report whole-job
totals (previously a resume produced tail-only counts and false MISMATCHes).
Jobs in ERROR can be re-run and resume from the checkpoint.

**`mail_run_data.csv`** (sidecar manifest, per job): columns `piece,
unique_id, sheets, start_page, end_page, overflow, insert, divert, barcodes,
output_file`. This is the file to adapt to the inserter's job-import format
(MRDF) once the machine spec is in hand, and the reconciliation anchor for
Phase 3.

## 4. Vector barcode rendering

Barcodes are drawn as vector rectangles (opaque white quiet zone + black
module rects) directly in the overlay PDF — no raster, no temp PNG files, no
DPI coupling. Module size on paper is exactly `module_size_mm` at any RIP
resolution. The module grid is sampled from libdmtx output and verified
against the ECC200 finder pattern before rendering; decode round-trip is
covered by tests.

**Raster defect found and fixed:** libdmtx's raster includes a 10px internal
margin; the old code resized the full raster (symbol + margin) to the symbol
size, printing modules ~18% under spec (≈0.41mm instead of the configured
0.50mm). The preview raster path (`generate_barcode_image`) now crops to the
symbol bbox first. **Run a camera test deck after deploying** — symbol size
on paper changes from ~7.4mm to 9mm plus exact quiet zone.

## 5. Page-geometry handling

- `/Rotate` is baked into page content before stamping
  (`transfer_rotation_to_content`), so the barcode lands at the intended
  physical position on rotated print streams.
- Overlays are translated to non-zero MediaBox origins.
- Mixed page sizes within one batch produce a report warning.

## 6. Throughput (measured on the 600-page test batch)

| Stage | Before | After | |
|---|---|---|---|
| Detection (region extraction) | 160s | 19s | 8.4x — one pdfplumber open + per-page cache flush instead of one open per page |
| Stamping (100 doc sets) | 13.4s | 4.3s | 3.1x — one shared `PdfReader` per job instead of re-parsing per doc set |

`process_document` accepts a path or an open `PdfReader`. `merge_pdfs` uses
`PdfWriter.append`.

## 7. Watched intake directories

`Template.input_dir`: each template may own one intake directory (never
shared — a batch physically cannot be processed with the wrong template).

Flow: PDF dropped → size/mtime stable across two polls (half-copied files are
never picked up) → moved to `ingested/` (cannot be picked up twice) → job
created (`AUTO-<timestamp>` session) → run serially through the normal
pipeline. Failures write `<name>.ERROR.txt` next to the file and never block
other batches. Watcher thread starts/stops with the app.

## 8. Configuration reference (env prefix `BARCODE_`)

| Setting | Default | Purpose |
|---|---|---|
| `MAX_SHEETS_PER_DOC` | 9 | Detection merge guard ceiling |
| `CLEAR_ZONE_MODE` | `warn` | `off` / `warn` / `abort` |
| `WATCH_ENABLED` | `true` | Intake watcher thread |
| `WATCH_POLL_SECONDS` | 5.0 | Intake poll interval |
| `OVERFLOW_THRESHOLD` | 6 | Sheets above this route to `manual_overflow/` |
| `ALLOWED_BROWSE_ROOTS` | `[]` (= user home) | File-browser jail |

## 9. Output directory contents (per job)

```
<name>_<session>_<date>/
├── machine_ready/doc_NNNNNN.pdf     # barcoded, ≤ overflow threshold
├── manual_overflow/doc_NNNNNN.pdf   # barcoded, pulled for manual handling
├── report.json / report.pdf         # totals, verification, warnings
├── mail_run_data.csv                # per-piece manifest
├── combined_output.pdf              # cover + docs + end sheet (only when verification OK)
└── QUARANTINED_DO_NOT_MAIL.txt      # present instead of combined output on MISMATCH
```

## 10. Behavior changes operators will notice

1. Marginal batches that used to "work" now stop with a specific error
   (counter mismatch, duplicate UID, >9 sheets, odd duplex pages). Intended.
2. MISMATCH runs complete with a report but no combined deliverable.
3. Re-running a job into an existing output directory is refused.
4. Templates whose PAGE_COUNTER region declares page totals rather than sheet
   totals will error on first run and need a one-time region fix.

## 11. Deferred / next (Phase 3)

- Reconciliation loop: import the inserter's read log, diff against
  `MailPiece`, exception report for unaccounted pieces.
- Output verification pass: decode every stamped barcode from the final PDF
  and assert it matches the manifest.
- Append-only audit log (runs, resumes, overrides, counter claims, emails).
- Per-piece variable insert codes (pending machine firmware confirmation).
- Alembic migrations (current: additive PRAGMA migrations in `database.py`).
- Retention/cleanup policy for uploads and output directories.

## Test suite

219 tests. New files: `tests/test_phase1_safety.py` (payload, detection,
UID, quarantine, resume, clear zone), `tests/test_phase2_output.py` (vector
rendering, rotation/MediaBox, manifest), `tests/test_phase2_intake.py`
(insert pockets, watcher stability/ingest/end-to-end).
