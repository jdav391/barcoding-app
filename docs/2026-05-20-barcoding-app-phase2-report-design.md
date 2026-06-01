# Barcoding Application — Phase 2 Design Spec: Job Report Improvements

**Date:** 2026-05-20
**Status:** Draft
**Parent spec:** [Phase 1 spec](/Volumes/NVME4TB/Users/joeldavidson/docs/superpowers/specs/2026-05-19-barcoding-app-phase1-design.md)
**Stack:** Python + FastAPI + SQLite + Jinja2/HTMX + ReportLab
**Project path:** /Volumes/NVME4TB/Users/joeldavidson/projects/barcoding-app

## Context

Phase 1 delivers barcode generation and PDF embedding with a web UI, job wizard, and an HTML-only job report. Phase 2 improves the job report to serve as a **legal certification document** that is shared with machine operators, supervisors/QA, and the customer. A legal mandate requires the organization to certify that each mail piece was processed and mailed; this report fulfills that requirement.

## Scope

### In scope

- Single-page PDF report generated with ReportLab (no new dependencies)
- PDF download button on the job report page
- Report PDF as cover and end sheet in the combined output file
- Auto-send email on job completion (Gmail SMTP, configurable per preset)
- Manual "Send Certification" email from the report page
- SMTP configuration in app settings
- Preset model changes for email settings

### Out of scope

- Dedicated report archive system (current file-based storage alongside output is sufficient)
- Custom branding/logos on the report (can be added later)
- Non-Gmail SMTP providers (Gmail/Google Workspace only for now)
- Digital signatures or PDF encryption

## PDF Report Layout

A single US letter page (8.5 x 11", 612 x 792 pt) generated with ReportLab. The report uses compact spacing to guarantee all content fits on one page.

### Structure (top to bottom)

**Header:**
- Title: "Barcoding Job Report"
- Job name, session ID, date
- Status banner: green background with "PROCESSING COMPLETE" when verification passes or no batch data was provided; red background with "VERIFICATION FAILED" when a count mismatch is detected

**Summary table:**
- Letters Processed
- Total Sheets
- Barcodes Applied
- Inserts (row only shown when count > 0)
- Diverts (row only shown when count > 0)
- Overflow / Manual Processing (row only shown when count > 0)

**Verification table** (section only present when batch data was provided):
- Expected Letters vs. Letters Processed
- Expected Sheets vs. Sheets Processed
- Result: PASS or FAIL

**Overflow detail table** (section only present when overflow documents exist):
- Columns: Document, Sheets, Unique ID
- If overflow count exceeds available vertical space, truncate with: "Showing N of M overflow documents. See full report in output directory."

**Footer:**
- Output directory path
- Generation timestamp (ISO 8601)
- "This report was generated automatically by the Barcoding Application."

### When no batch data is provided

The status banner reads "PROCESSING COMPLETE". The verification table section is omitted entirely. The summary table stands alone as the record of what was processed.

### When verification fails

The status banner reads "VERIFICATION FAILED" with a red background. The verification table shows the expected vs. actual counts with a FAIL result. The summary table is still shown in full.

## Cover & End Sheet Integration

After job processing completes:

1. The report PDF is generated as `report.pdf` in the output directory (replacing the current `report.json` — JSON is still written separately for programmatic access)
2. The combined output is assembled as:
   - Page 1: Report PDF (cover sheet)
   - Pages 2 through N: Barcoded documents from `machine_ready/` in order
   - Page N+1: Report PDF (end sheet)
3. The cover and end sheet are identical — the same single-page report

The individual `machine_ready/` files, `manual_overflow/` files, `report.json`, and standalone `report.pdf` are all still generated separately. The cover/end sheet is only added to `combined_output.pdf`.

## Email Delivery

### SMTP Configuration

Global app settings (not per-preset), configured once at setup:

| Setting | Description | Example |
|---|---|---|
| `smtp_host` | Gmail SMTP server | `smtp.gmail.com` |
| `smtp_port` | TLS port | `587` |
| `smtp_username` | Gmail address (also used as sender) | `shared-inbox@org.com` |
| `smtp_password` | Gmail app password | (via env var or .env file) |

Stored in `app/config.py` via Pydantic Settings, loaded from environment variables or a `.env` file. The `.env` file is gitignored. The SMTP username doubles as the "From" address for all emails.

### Preset Model Changes

Two new fields on the `Preset` model:

| Field | Type | Default | Description |
|---|---|---|---|
| `auto_email_enabled` | Boolean | False | Send report email automatically on job completion |
| `email_recipients` | String (nullable) | None | Comma-separated email addresses |

The preset form adds an "Email Settings" section (collapsed by default, like "Barcode Placement"):
- Checkbox: "Automatically email report on completion"
- Text input: "Recipients" (comma-separated)

### Auto-send on Completion

Triggered immediately when a job finishes successfully. Uses the preset's recipient list.

**Subject line (success):**
```
[Barcoding] {job_name} — {session_id} — Complete
```

**Subject line (errors — verification failed or overflow occurred):**
```
[Barcoding] [ACTION REQUIRED] {job_name} — {session_id} — Errors Detected
```

**Body:** Plain-text summary:
```
Job: {job_name}
Session: {session_id}
Date: {date}
Status: {COMPLETE or ERRORS DETECTED}

Letters Processed: {count}
Total Sheets: {count}
Barcodes Applied: {count}

See attached report for full details.
```

**Attachment:** `report.pdf`

Email sending is non-blocking — if SMTP fails, the job still completes. The failure is logged and shown as a warning on the report page ("Report email could not be sent: {error}").

### Manual Send (Customer Certification)

A "Send Certification" button on the job report page in the web UI.

Clicking it shows a confirmation with:
- Pre-filled recipients from the preset (editable)
- Option to add additional recipients
- Send button

**Subject line:**
```
[Barcoding] Certification — {job_name} — {session_id}
```

**Body:** Plain-text certification statement:
```
This certifies that barcoding job "{job_name}" (Session: {session_id}, Date: {date})
has been processed and verified.

Letters Processed: {count}
Total Sheets: {count}
Barcodes Applied: {count}

The attached report contains full processing details.

This certification was generated by the Barcoding Application.
```

**Attachment:** `report.pdf`

Success/failure feedback is shown inline on the report page.

## PDF Download

A "Download Report" button on the job report page. Serves the `report.pdf` file from the output directory as a browser download with filename `{job_name}_{session_id}_report.pdf`.

Implementation: a simple FastAPI endpoint that returns `FileResponse` for the stored PDF.

## Architecture Changes

### New files

| File | Purpose |
|---|---|
| `app/services/report_pdf.py` | ReportLab PDF generation — takes report data dict, returns PDF bytes |
| `app/services/email.py` | SMTP email sending — takes recipients, subject, body, attachment |

### Modified files

| File | Change |
|---|---|
| `app/models.py` | Add `auto_email_enabled` and `email_recipients` to Preset |
| `app/config.py` | Add SMTP settings |
| `app/services/job.py` | After job completion: generate PDF report, insert cover/end sheets, trigger auto-email |
| `app/services/reporter.py` | No changes to JSON generation; PDF generation is a separate service |
| `app/routes/jobs.py` | Add `/api/jobs/{id}/report/download` and `/api/jobs/{id}/report/send` endpoints |
| `app/main.py` | Add download and send certification routes for the HTML UI |
| `app/templates/report.html` | Add "Download Report" and "Send Certification" buttons |
| `app/templates/presets/form.html` | Add email settings section |

### Processing pipeline (updated)

```
Split PDF -> Generate barcodes -> Embed on pages -> Write individual PDFs
    -> Generate report.json
    -> Generate report.pdf (ReportLab)
    -> Merge: [report.pdf] + machine_ready/*.pdf + [report.pdf] -> combined_output.pdf
    -> Auto-send email (if enabled)
```

## Testing

- `test_report_pdf.py` — PDF generation produces valid single-page PDF, all sections render correctly, handles missing verification/overflow gracefully
- `test_email.py` — Email service constructs correct messages, handles SMTP errors gracefully (mock SMTP)
- `test_integration.py` — Full pipeline produces `report.pdf` and `combined_output.pdf` with cover/end sheets
- Manual: verify PDF renders correctly when opened, verify email arrives with attachment
