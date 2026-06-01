# Phase 2: Job Report Improvements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a single-page PDF job report (ReportLab) that serves as a legal certification document, embed it as cover/end sheets in the combined output, and deliver it via email (auto + manual).

**Architecture:** New `report_pdf.py` service generates the PDF from the existing report data dict. New `email.py` service handles Gmail SMTP. The job pipeline (`job.py`) gains three post-processing steps: generate PDF, wrap combined output with cover/end sheets, and trigger auto-email. Two new API endpoints serve download and manual certification send.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy, SQLite, ReportLab, smtplib (stdlib), Jinja2/HTMX, Pico CSS

**Project path:** `/Volumes/NVME4TB/Users/joeldavidson/projects/barcoding-app`

**Spec:** `/Volumes/NVME4TB/Users/joeldavidson/docs/superpowers/specs/2026-05-20-barcoding-app-phase2-report-design.md`

---

## File Structure

### New files

| File | Responsibility |
|---|---|
| `app/services/report_pdf.py` | ReportLab PDF generation — takes report data dict, returns PDF bytes |
| `app/services/email.py` | SMTP email construction and sending |
| `tests/test_report_pdf.py` | PDF generation tests |
| `tests/test_email.py` | Email service tests (mocked SMTP) |

### Modified files

| File | Changes |
|---|---|
| `app/services/job.py:154-184` | Fix verification key bug; add PDF generation, cover/end sheet wrapping, auto-email trigger after job completion |
| `app/models.py:43-57` | Add `auto_email_enabled` (Boolean) and `email_recipients` (String) to Preset |
| `app/config.py:1-18` | Add SMTP settings (host, port, username, password) |
| `app/routes/jobs.py` | Add `/api/jobs/{id}/report/download` and `/api/jobs/{id}/report/send` endpoints |
| `app/main.py` | Add `/jobs/{id}/report/download` and `/jobs/{id}/report/send` HTML routes; update preset form handlers for new email fields |
| `app/templates/report.html` | Add "Download Report" and "Send Certification" buttons |
| `app/templates/presets/form.html` | Add "Email Settings" collapsed section |
| `app/schemas.py` | Add `auto_email_enabled` and `email_recipients` to PresetCreate/PresetResponse |

---

### Task 1: Fix verification key bug in job.py

Line 164 of `app/services/job.py` does `report["verification"]["verdict"]` but the `verification` key is now only present when batch data was provided (changed in Phase 1 smoke testing). This crashes for jobs without batch data.

**Files:**
- Modify: `app/services/job.py:164`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_integration.py`:

```python
class TestJobWithoutBatchData:
    def test_job_completes_without_batch_data(self, db_session, sample_duplex_pdf):
        """Job without batch imports should complete with OK verification."""
        from app.enums import FeedDirection, IdSource, JobStatus, PageFormat
        from app.models import Job, Preset
        from app.services.job import run_job

        preset = Preset(
            name="test",
            sheets_per_doc=1,
            page_format=PageFormat.DUPLEX,
            feed_direction=FeedDirection.ASCENDING,
            id_source=IdSource.SEQUENTIAL,
            embed_config={
                "barcode": {"anchor": "bottom-right", "x_offset_pt": 36, "y_offset_pt": 36, "module_size_mm": 0.50, "quiet_zone_mm": 6.5, "dpi": 600},
                "human_readable": {"enabled": False, "anchor": "bottom-left", "x_offset_pt": 36, "y_offset_pt": 36, "rotation": 90, "font_name": "Courier", "font_size": 8},
            },
        )
        db_session.add(preset)
        db_session.commit()
        db_session.refresh(preset)

        job = Job(
            name="no-batch-test",
            session_id="NB001",
            date=__import__("datetime").date.today(),
            source_path=str(sample_duplex_pdf),
            preset_id=preset.id,
            status=JobStatus.DRAFT,
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)

        result = run_job(db_session, job)
        assert result.verification.value == "OK"
        assert result.total_documents == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_integration.py::TestJobWithoutBatchData::test_job_completes_without_batch_data -v`
Expected: FAIL with `KeyError: 'verification'`

- [ ] **Step 3: Fix the bug**

In `app/services/job.py`, replace line 164:

```python
    verification = VerificationStatus(report["verification"]["verdict"])
```

with:

```python
    verification_data = report.get("verification")
    verification = VerificationStatus(verification_data["verdict"]) if verification_data else VerificationStatus.OK
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_integration.py::TestJobWithoutBatchData -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add app/services/job.py tests/test_integration.py
git commit -m "fix: handle missing verification key when no batch data provided"
```

---

### Task 2: PDF Report Generation Service

The core new service. Takes the report data dict (same structure as `report.json`) and returns PDF bytes using ReportLab.

**Files:**
- Create: `app/services/report_pdf.py`
- Create: `tests/test_report_pdf.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_report_pdf.py`:

```python
import io
from pypdf import PdfReader

from app.services.report_pdf import generate_report_pdf


class TestGenerateReportPdf:
    def _make_report(self, **overrides):
        report = {
            "job": "Test Job",
            "session_id": "TEST001",
            "date": "2026-05-20",
            "status": "OK",
            "totals": {
                "documents_processed": 300,
                "total_sheets": 300,
                "total_barcodes": 300,
                "inserts_triggered": 0,
                "diverts_triggered": 0,
                "overflow_documents": 0,
            },
            "overflow_detail": [],
            "warnings": [],
        }
        report.update(overrides)
        return report

    def test_returns_valid_pdf_bytes(self):
        report = self._make_report()
        pdf_bytes = generate_report_pdf(report)
        assert isinstance(pdf_bytes, bytes)
        assert pdf_bytes[:5] == b"%PDF-"

    def test_single_page(self):
        report = self._make_report()
        pdf_bytes = generate_report_pdf(report)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        assert len(reader.pages) == 1

    def test_contains_job_name(self):
        report = self._make_report(job="My Special Job")
        pdf_bytes = generate_report_pdf(report)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = reader.pages[0].extract_text()
        assert "My Special Job" in text

    def test_contains_session_id(self):
        report = self._make_report(session_id="SESS999")
        pdf_bytes = generate_report_pdf(report)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = reader.pages[0].extract_text()
        assert "SESS999" in text

    def test_contains_totals(self):
        report = self._make_report()
        pdf_bytes = generate_report_pdf(report)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = reader.pages[0].extract_text()
        assert "300" in text

    def test_processing_complete_status_when_no_verification(self):
        report = self._make_report()
        pdf_bytes = generate_report_pdf(report)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = reader.pages[0].extract_text()
        assert "PROCESSING COMPLETE" in text

    def test_verification_pass_when_batch_data(self):
        report = self._make_report(verification={
            "expected_letters": 300,
            "actual_documents": 300,
            "expected_sheets": 300,
            "actual_sheets": 300,
            "match": True,
            "verdict": "OK",
            "details": None,
        })
        pdf_bytes = generate_report_pdf(report)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = reader.pages[0].extract_text()
        assert "PROCESSING COMPLETE" in text
        assert "PASS" in text

    def test_verification_fail(self):
        report = self._make_report(
            status="MISMATCH",
            verification={
                "expected_letters": 300,
                "actual_documents": 299,
                "expected_sheets": 300,
                "actual_sheets": 299,
                "match": False,
                "verdict": "MISMATCH",
                "details": "Documents: expected 300, got 299",
            },
        )
        pdf_bytes = generate_report_pdf(report)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = reader.pages[0].extract_text()
        assert "VERIFICATION FAILED" in text
        assert "FAIL" in text

    def test_overflow_detail_rendered(self):
        report = self._make_report(
            overflow_detail=[
                {"doc_index": 0, "sheets": 8, "unique_id": 100000001},
                {"doc_index": 5, "sheets": 7, "unique_id": 100000006},
            ],
        )
        report["totals"]["overflow_documents"] = 2
        pdf_bytes = generate_report_pdf(report)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = reader.pages[0].extract_text()
        assert "100000001" in text

    def test_inserts_shown_when_nonzero(self):
        report = self._make_report()
        report["totals"]["inserts_triggered"] = 50
        pdf_bytes = generate_report_pdf(report)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = reader.pages[0].extract_text()
        assert "Inserts" in text

    def test_inserts_hidden_when_zero(self):
        report = self._make_report()
        pdf_bytes = generate_report_pdf(report)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = reader.pages[0].extract_text()
        assert "Inserts" not in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_report_pdf.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.report_pdf'`

- [ ] **Step 3: Implement the service**

Create `app/services/report_pdf.py`:

```python
"""PDF report generation using ReportLab."""
from __future__ import annotations

import io
from datetime import UTC, datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle


def generate_report_pdf(report: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle", parent=styles["Title"], fontSize=18, spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle", parent=styles["Normal"], fontSize=11, textColor=colors.grey, spaceAfter=8,
    )
    section_style = ParagraphStyle(
        "SectionHeader", parent=styles["Heading2"], fontSize=12, spaceBefore=12, spaceAfter=4,
    )
    footer_style = ParagraphStyle(
        "Footer", parent=styles["Normal"], fontSize=8, textColor=colors.grey, spaceBefore=12,
    )

    elements = []

    elements.append(Paragraph("Barcoding Job Report", title_style))
    elements.append(Paragraph(
        f"{report['job']} &mdash; Session {report['session_id']} &mdash; {report['date']}",
        subtitle_style,
    ))

    has_verification = "verification" in report
    is_fail = report.get("status") == "MISMATCH"

    if is_fail:
        banner_text = "VERIFICATION FAILED"
        banner_bg = colors.Color(0.9, 0.2, 0.2)
    else:
        banner_text = "PROCESSING COMPLETE"
        banner_bg = colors.Color(0.2, 0.7, 0.3)

    banner_data = [[Paragraph(
        f'<font color="white"><b>{banner_text}</b></font>',
        ParagraphStyle("Banner", parent=styles["Normal"], fontSize=14, alignment=1),
    )]]
    banner_table = Table(banner_data, colWidths=[7 * inch])
    banner_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), banner_bg),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    elements.append(banner_table)
    elements.append(Spacer(1, 8))

    elements.append(Paragraph("Summary", section_style))
    totals = report["totals"]
    summary_rows = [
        ["Letters Processed", str(totals["documents_processed"])],
        ["Total Sheets", str(totals["total_sheets"])],
        ["Barcodes Applied", str(totals["total_barcodes"])],
    ]
    if totals.get("inserts_triggered", 0) > 0:
        summary_rows.append(["Inserts", str(totals["inserts_triggered"])])
    if totals.get("diverts_triggered", 0) > 0:
        summary_rows.append(["Diverts", str(totals["diverts_triggered"])])
    if totals.get("overflow_documents", 0) > 0:
        summary_rows.append(["Overflow (Manual Processing)", str(totals["overflow_documents"])])

    summary_table = Table(summary_rows, colWidths=[4.5 * inch, 2.5 * inch])
    summary_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("BACKGROUND", (0, 0), (0, -1), colors.Color(0.95, 0.95, 0.95)),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(summary_table)

    if has_verification:
        v = report["verification"]
        elements.append(Paragraph("Verification Details", section_style))
        result_text = "PASS" if v["match"] else "FAIL"
        verify_rows = [
            ["Expected Letters", str(v["expected_letters"])],
            ["Letters Processed", str(v["actual_documents"])],
            ["Expected Sheets", str(v["expected_sheets"])],
            ["Sheets Processed", str(v["actual_sheets"])],
            ["Result", result_text],
        ]
        verify_table = Table(verify_rows, colWidths=[4.5 * inch, 2.5 * inch])
        verify_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("BACKGROUND", (0, 0), (0, -1), colors.Color(0.95, 0.95, 0.95)),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("TEXTCOLOR", (1, -1), (1, -1), colors.green if v["match"] else colors.red),
            ("FONTNAME", (1, -1), (1, -1), "Helvetica-Bold"),
        ]))
        elements.append(verify_table)

    overflow = report.get("overflow_detail", [])
    if overflow:
        elements.append(Paragraph("Overflow Documents", section_style))
        elements.append(Paragraph(
            "The following documents exceeded the folding threshold and were diverted for manual processing.",
            styles["Normal"],
        ))
        elements.append(Spacer(1, 4))
        max_rows = 15
        overflow_rows = [["Document", "Sheets", "Unique ID"]]
        for od in overflow[:max_rows]:
            overflow_rows.append([str(od["doc_index"] + 1), str(od["sheets"]), str(od["unique_id"])])
        if len(overflow) > max_rows:
            overflow_rows.append([
                f"Showing {max_rows} of {len(overflow)} overflow documents. See full report in output directory.",
                "", "",
            ])
        overflow_table = Table(overflow_rows, colWidths=[2.33 * inch, 2.33 * inch, 2.34 * inch])
        overflow_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.85, 0.85, 0.85)),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(overflow_table)

    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    elements.append(Paragraph(
        f"Generated: {timestamp}<br/>This report was generated automatically by the Barcoding Application.",
        footer_style,
    ))

    doc.build(elements)
    return buf.getvalue()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_report_pdf.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add app/services/report_pdf.py tests/test_report_pdf.py
git commit -m "feat: PDF report generation service using ReportLab"
```

---

### Task 3: Preset Model and Config Changes

Add email-related fields to the Preset model and SMTP settings to app config.

**Files:**
- Modify: `app/models.py:43-57`
- Modify: `app/config.py:1-18`
- Modify: `app/schemas.py:32-57`
- Modify: `app/templates/presets/form.html`
- Modify: `app/main.py` (both `create_preset_form` and `update_preset_form`)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_routes/test_presets.py`:

```python
def test_create_preset_with_email_settings(self):
    r = self.client.post("/api/presets", json={
        "name": "Email Test",
        "sheets_per_doc": 1,
        "auto_email_enabled": True,
        "email_recipients": "shared@example.com, qa@example.com",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["auto_email_enabled"] is True
    assert data["email_recipients"] == "shared@example.com, qa@example.com"

def test_create_preset_email_defaults(self):
    r = self.client.post("/api/presets", json={
        "name": "No Email",
        "sheets_per_doc": 1,
    })
    assert r.status_code == 201
    data = r.json()
    assert data["auto_email_enabled"] is False
    assert data["email_recipients"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_routes/test_presets.py::TestPresetCRUD::test_create_preset_with_email_settings -v`
Expected: FAIL (field not recognized or missing from response)

- [ ] **Step 3: Add columns to Preset model**

In `app/models.py`, add after line 54 (`embed_config = Column(...)`) and before `created_at`:

```python
    auto_email_enabled = Column(Boolean, nullable=False, default=False)
    email_recipients = Column(String, nullable=True)
```

- [ ] **Step 4: Add SMTP settings to config**

In `app/config.py`, add to the `Settings` class after `overflow_threshold`:

```python
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
```

- [ ] **Step 5: Update schemas**

In `app/schemas.py`, add to `PresetCreate` (after `embed_config`):

```python
    auto_email_enabled: bool = False
    email_recipients: str | None = None
```

In `app/schemas.py`, add to `PresetResponse` (after `embed_config: dict`):

```python
    auto_email_enabled: bool
    email_recipients: str | None
```

- [ ] **Step 6: Update preset form template**

In `app/templates/presets/form.html`, add before the closing `<button>` tag:

```html
    <details>
        <summary>Email Settings</summary>
        <input type="hidden" name="auto_email_enabled" value="false">
        <label><input type="checkbox" name="auto_email_enabled" value="true" {{ 'checked' if preset and preset.auto_email_enabled }}> Automatically email report on completion</label>
        <label for="email_recipients">Recipients (comma-separated)
            <input type="text" id="email_recipients" name="email_recipients" value="{{ preset.email_recipients if preset and preset.email_recipients else '' }}" placeholder="shared@example.com, qa@example.com">
        </label>
    </details>
```

- [ ] **Step 7: Update form handlers in main.py**

In `app/main.py`, add parameters to `create_preset_form` (after `hr_enabled`):

```python
    auto_email_enabled: str = Form("false"),
    email_recipients: str = Form(""),
```

In the `Preset(...)` constructor inside `create_preset_form`, add:

```python
        auto_email_enabled=_form_bool(auto_email_enabled),
        email_recipients=email_recipients.strip() or None,
```

Apply the same changes to `update_preset_form` — add the same parameters, and in the update block add:

```python
    preset.auto_email_enabled = _form_bool(auto_email_enabled)
    preset.email_recipients = email_recipients.strip() or None
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_routes/test_presets.py -v`
Expected: All PASS

- [ ] **Step 9: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 10: Commit**

```bash
git add app/models.py app/config.py app/schemas.py app/main.py app/templates/presets/form.html
git commit -m "feat: add email settings to preset model, config, and form"
```

---

### Task 4: Email Service

SMTP email sending with attachment support. Uses stdlib `smtplib` and `email` — no new dependencies.

**Files:**
- Create: `app/services/email.py`
- Create: `tests/test_email.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_email.py`:

```python
from unittest.mock import patch, MagicMock

from app.services.email import send_report_email, build_message


class TestBuildMessage:
    def test_message_structure(self):
        msg = build_message(
            sender="test@example.com",
            recipients=["qa@example.com"],
            subject="Test Subject",
            body="Test body text.",
            attachment_bytes=b"%PDF-fake",
            attachment_filename="report.pdf",
        )
        assert msg["From"] == "test@example.com"
        assert msg["To"] == "qa@example.com"
        assert msg["Subject"] == "Test Subject"
        payloads = msg.get_payload()
        assert len(payloads) == 2
        assert payloads[0].get_content_type() == "text/plain"
        assert payloads[1].get_content_type() == "application/pdf"
        assert payloads[1].get_filename() == "report.pdf"

    def test_multiple_recipients(self):
        msg = build_message(
            sender="test@example.com",
            recipients=["a@example.com", "b@example.com"],
            subject="Multi",
            body="Body",
            attachment_bytes=b"%PDF-fake",
            attachment_filename="report.pdf",
        )
        assert msg["To"] == "a@example.com, b@example.com"

    def test_body_content(self):
        msg = build_message(
            sender="test@example.com",
            recipients=["qa@example.com"],
            subject="Subj",
            body="Expected body content here.",
            attachment_bytes=b"%PDF-fake",
            attachment_filename="report.pdf",
        )
        text_part = msg.get_payload()[0]
        assert "Expected body content here." in text_part.get_payload()


class TestSendReportEmail:
    @patch("app.services.email.smtplib.SMTP")
    def test_sends_via_smtp(self, mock_smtp_class):
        mock_smtp = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        result = send_report_email(
            host="smtp.gmail.com",
            port=587,
            username="user@gmail.com",
            password="secret",
            recipients=["qa@example.com"],
            subject="Test",
            body="Body",
            pdf_bytes=b"%PDF-fake",
            pdf_filename="report.pdf",
        )

        assert result is True
        mock_smtp_class.assert_called_once_with("smtp.gmail.com", 587)
        mock_smtp.starttls.assert_called_once()
        mock_smtp.login.assert_called_once_with("user@gmail.com", "secret")
        mock_smtp.send_message.assert_called_once()

    @patch("app.services.email.smtplib.SMTP")
    def test_returns_false_on_smtp_error(self, mock_smtp_class):
        mock_smtp_class.side_effect = Exception("Connection refused")

        result = send_report_email(
            host="smtp.gmail.com",
            port=587,
            username="user@gmail.com",
            password="secret",
            recipients=["qa@example.com"],
            subject="Test",
            body="Body",
            pdf_bytes=b"%PDF-fake",
            pdf_filename="report.pdf",
        )

        assert result is False

    def test_returns_false_when_no_smtp_configured(self):
        result = send_report_email(
            host="",
            port=587,
            username="",
            password="",
            recipients=["qa@example.com"],
            subject="Test",
            body="Body",
            pdf_bytes=b"%PDF-fake",
            pdf_filename="report.pdf",
        )

        assert result is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_email.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.email'`

- [ ] **Step 3: Implement the email service**

Create `app/services/email.py`:

```python
"""Email sending service for job reports."""
from __future__ import annotations

import logging
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def build_message(
    sender: str,
    recipients: list[str],
    subject: str,
    body: str,
    attachment_bytes: bytes,
    attachment_filename: str,
) -> MIMEMultipart:
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))

    part = MIMEBase("application", "pdf")
    part.set_payload(attachment_bytes)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{attachment_filename}"')
    msg.attach(part)

    return msg


def send_report_email(
    host: str,
    port: int,
    username: str,
    password: str,
    recipients: list[str],
    subject: str,
    body: str,
    pdf_bytes: bytes,
    pdf_filename: str,
) -> bool:
    if not host or not username:
        logger.warning("SMTP not configured — skipping email send")
        return False

    try:
        msg = build_message(
            sender=username,
            recipients=recipients,
            subject=subject,
            body=body,
            attachment_bytes=pdf_bytes,
            attachment_filename=pdf_filename,
        )
        with smtplib.SMTP(host, port) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(msg)
        logger.info("Report email sent to %s", ", ".join(recipients))
        return True
    except Exception:
        logger.exception("Failed to send report email")
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_email.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add app/services/email.py tests/test_email.py
git commit -m "feat: email service with SMTP sending and PDF attachment"
```

---

### Task 5: Cover/End Sheet Integration and PDF in Job Pipeline

Wire the PDF report into the job pipeline: generate `report.pdf`, wrap `combined_output.pdf` with cover/end sheets.

**Files:**
- Modify: `app/services/job.py:133-184`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_integration.py`:

```python
class TestCoverEndSheets:
    def test_combined_output_has_cover_and_end_sheets(self, db_session, sample_duplex_pdf):
        from app.enums import FeedDirection, IdSource, JobStatus, PageFormat
        from app.models import Job, Preset
        from app.services.job import run_job
        from pypdf import PdfReader

        preset = Preset(
            name="cover-test",
            sheets_per_doc=1,
            page_format=PageFormat.DUPLEX,
            feed_direction=FeedDirection.ASCENDING,
            id_source=IdSource.SEQUENTIAL,
            embed_config={
                "barcode": {"anchor": "bottom-right", "x_offset_pt": 36, "y_offset_pt": 36, "module_size_mm": 0.50, "quiet_zone_mm": 6.5, "dpi": 600},
                "human_readable": {"enabled": False, "anchor": "bottom-left", "x_offset_pt": 36, "y_offset_pt": 36, "rotation": 90, "font_name": "Courier", "font_size": 8},
            },
        )
        db_session.add(preset)
        db_session.commit()
        db_session.refresh(preset)

        job = Job(
            name="cover-test",
            session_id="CT001",
            date=__import__("datetime").date.today(),
            source_path=str(sample_duplex_pdf),
            preset_id=preset.id,
            status=JobStatus.DRAFT,
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)

        result = run_job(db_session, job)

        report_pdf_path = Path(result.output_dir) / "report.pdf"
        assert report_pdf_path.exists()

        combined_path = Path(result.output_dir) / "combined_output.pdf"
        combined_reader = PdfReader(str(combined_path))
        # 10 machine_ready docs (each 2 pages) + 1 cover + 1 end = 22 pages
        assert len(combined_reader.pages) == 22

        # First and last pages should contain report text
        first_text = combined_reader.pages[0].extract_text()
        last_text = combined_reader.pages[-1].extract_text()
        assert "Barcoding Job Report" in first_text
        assert "Barcoding Job Report" in last_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_integration.py::TestCoverEndSheets -v`
Expected: FAIL (no `report.pdf` exists, page count wrong)

- [ ] **Step 3: Update job.py**

In `app/services/job.py`, add import at the top (after existing imports):

```python
from app.services.report_pdf import generate_report_pdf
```

Replace the block from `combined_path = output_dir / "combined_output.pdf"` through `report_path.write_text(...)` (lines 133-162) with:

```python
    report = generate_report(
        job_info={"name": job.name, "session_id": job.session_id, "date": job.date.isoformat()},
        totals=totals,
        imports=imports,
        overflow_detail=overflow_detail,
    )

    report_json_path = output_dir / "report.json"
    report_json_path.write_text(json.dumps(report, indent=2))

    report_pdf_bytes = generate_report_pdf(report)
    report_pdf_path = output_dir / "report.pdf"
    report_pdf_path.write_bytes(report_pdf_bytes)

    combined_path = output_dir / "combined_output.pdf"
    if machine_ready_paths:
        merge_pdfs(
            [report_pdf_path] + machine_ready_paths + [report_pdf_path],
            combined_path,
        )
```

Also fix the verification line (from Task 1, should already be done):

```python
    verification_data = report.get("verification")
    verification = VerificationStatus(verification_data["verdict"]) if verification_data else VerificationStatus.OK
```

Update the `report_path` in the JobResult to point to the JSON file:

```python
        report_path=str(report_json_path),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_integration.py::TestCoverEndSheets -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add app/services/job.py tests/test_integration.py
git commit -m "feat: generate PDF report and wrap combined output with cover/end sheets"
```

---

### Task 6: PDF Download Endpoint

Add a download route that serves the PDF report as a file download.

**Files:**
- Modify: `app/routes/jobs.py`
- Modify: `app/main.py`
- Modify: `app/templates/report.html`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_routes/test_presets.py` (or create a new `tests/test_routes/test_jobs.py` — use the existing route test pattern):

Create `tests/test_routes/test_jobs.py`:

```python
from pathlib import Path
from unittest.mock import patch, MagicMock

from tests.test_routes.conftest import *  # noqa: reuse existing fixtures


class TestJobReportDownload:
    def test_download_returns_pdf(self, client, db_session):
        from app.enums import JobStatus, VerificationStatus
        from app.models import Job, JobResult, Preset

        preset = Preset(name="dl-test", sheets_per_doc=1)
        db_session.add(preset)
        db_session.commit()
        db_session.refresh(preset)

        job = Job(
            name="dl-test",
            session_id="DL001",
            date=__import__("datetime").date.today(),
            source_path="/fake",
            preset_id=preset.id,
            status=JobStatus.COMPLETE,
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)

        tmp = Path("/tmp/barcode-test-dl")
        tmp.mkdir(exist_ok=True)
        pdf_path = tmp / "report.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake pdf content")

        result = JobResult(
            job_id=job.id,
            total_barcodes=10,
            total_documents=10,
            total_sheets=10,
            overflow_docs=0,
            diverts_triggered=0,
            insert_count=0,
            verification=VerificationStatus.OK,
            report_path=str(tmp / "report.json"),
            output_dir=str(tmp),
        )
        db_session.add(result)
        db_session.commit()

        r = client.get(f"/api/jobs/{job.id}/report/download")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert b"%PDF-1.4" in r.content

        pdf_path.unlink()
        tmp.rmdir()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_routes/test_jobs.py::TestJobReportDownload -v`
Expected: FAIL with 404 or 405

- [ ] **Step 3: Add the API download endpoint**

In `app/routes/jobs.py`, add at the top:

```python
from pathlib import Path
from fastapi.responses import FileResponse
```

Add the route (after `get_report`):

```python
@router.get("/{job_id}/report/download")
def download_report_pdf(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job or not job.result:
        raise HTTPException(status_code=404, detail="Job not found")
    output_dir = job.result.output_dir
    if not output_dir:
        raise HTTPException(status_code=404, detail="No output directory")
    pdf_path = Path(output_dir) / "report.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Report PDF not found")
    filename = f"{job.name}_{job.session_id}_report.pdf"
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=filename,
    )
```

- [ ] **Step 4: Add "Download Report" button to report.html**

In `app/templates/report.html`, replace the bottom section (the `<p><strong>Output:</strong>...` and back button) with:

```html
<p><strong>Output:</strong> {{ result.output_dir }}</p>
<div style="display: flex; gap: 1rem; flex-wrap: wrap;">
    <a href="/api/jobs/{{ job.id }}/report/download" role="button">Download Report PDF</a>
    <a href="/" role="button" class="secondary">Back to Jobs</a>
</div>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_routes/test_jobs.py -v`
Expected: All PASS

- [ ] **Step 6: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add app/routes/jobs.py app/templates/report.html tests/test_routes/test_jobs.py
git commit -m "feat: PDF report download endpoint and button"
```

---

### Task 7: Auto-send Email on Job Completion

Wire the email service into the job pipeline to auto-send when the preset has it enabled.

**Files:**
- Modify: `app/services/job.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_integration.py`:

```python
from unittest.mock import patch

class TestAutoEmail:
    @patch("app.services.job.send_report_email")
    def test_auto_email_sent_when_enabled(self, mock_send, db_session, sample_duplex_pdf):
        from app.enums import FeedDirection, IdSource, JobStatus, PageFormat
        from app.models import Job, Preset
        from app.services.job import run_job

        mock_send.return_value = True

        preset = Preset(
            name="email-test",
            sheets_per_doc=1,
            page_format=PageFormat.DUPLEX,
            feed_direction=FeedDirection.ASCENDING,
            id_source=IdSource.SEQUENTIAL,
            auto_email_enabled=True,
            email_recipients="shared@example.com, qa@example.com",
            embed_config={
                "barcode": {"anchor": "bottom-right", "x_offset_pt": 36, "y_offset_pt": 36, "module_size_mm": 0.50, "quiet_zone_mm": 6.5, "dpi": 600},
                "human_readable": {"enabled": False, "anchor": "bottom-left", "x_offset_pt": 36, "y_offset_pt": 36, "rotation": 90, "font_name": "Courier", "font_size": 8},
            },
        )
        db_session.add(preset)
        db_session.commit()
        db_session.refresh(preset)

        job = Job(
            name="email-test",
            session_id="EM001",
            date=__import__("datetime").date.today(),
            source_path=str(sample_duplex_pdf),
            preset_id=preset.id,
            status=JobStatus.DRAFT,
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)

        run_job(db_session, job)

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args
        assert "shared@example.com" in call_kwargs.kwargs["recipients"]
        assert "qa@example.com" in call_kwargs.kwargs["recipients"]
        assert call_kwargs.kwargs["subject"].startswith("[Barcoding]")

    @patch("app.services.job.send_report_email")
    def test_no_email_when_disabled(self, mock_send, db_session, sample_duplex_pdf):
        from app.enums import FeedDirection, IdSource, JobStatus, PageFormat
        from app.models import Job, Preset
        from app.services.job import run_job

        preset = Preset(
            name="no-email",
            sheets_per_doc=1,
            page_format=PageFormat.DUPLEX,
            feed_direction=FeedDirection.ASCENDING,
            id_source=IdSource.SEQUENTIAL,
            auto_email_enabled=False,
            embed_config={
                "barcode": {"anchor": "bottom-right", "x_offset_pt": 36, "y_offset_pt": 36, "module_size_mm": 0.50, "quiet_zone_mm": 6.5, "dpi": 600},
                "human_readable": {"enabled": False, "anchor": "bottom-left", "x_offset_pt": 36, "y_offset_pt": 36, "rotation": 90, "font_name": "Courier", "font_size": 8},
            },
        )
        db_session.add(preset)
        db_session.commit()
        db_session.refresh(preset)

        job = Job(
            name="no-email",
            session_id="NE001",
            date=__import__("datetime").date.today(),
            source_path=str(sample_duplex_pdf),
            preset_id=preset.id,
            status=JobStatus.DRAFT,
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)

        run_job(db_session, job)

        mock_send.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_integration.py::TestAutoEmail -v`
Expected: FAIL (mock never called, or import error for `send_report_email`)

- [ ] **Step 3: Add auto-email to job.py**

In `app/services/job.py`, add import:

```python
from app.services.email import send_report_email
```

After the `db.commit()` that saves the JobResult (at the end of `run_job`, before `return result`), add:

```python
    if preset.auto_email_enabled and preset.email_recipients:
        recipients = [r.strip() for r in preset.email_recipients.split(",") if r.strip()]
        if recipients:
            is_error = verification != VerificationStatus.OK or overflow_count > 0
            if is_error:
                subject = f"[Barcoding] [ACTION REQUIRED] {job.name} — {job.session_id} — Errors Detected"
                status_text = "ERRORS DETECTED"
            else:
                subject = f"[Barcoding] {job.name} — {job.session_id} — Complete"
                status_text = "COMPLETE"

            body = (
                f"Job: {job.name}\n"
                f"Session: {job.session_id}\n"
                f"Date: {job.date.isoformat()}\n"
                f"Status: {status_text}\n\n"
                f"Letters Processed: {len(doc_sets)}\n"
                f"Total Sheets: {total_sheets}\n"
                f"Barcodes Applied: {total_barcodes}\n\n"
                f"See attached report for full details."
            )

            pdf_filename = f"{job.name}_{job.session_id}_report.pdf"
            send_report_email(
                host=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_username,
                password=settings.smtp_password,
                recipients=recipients,
                subject=subject,
                body=body,
                pdf_bytes=report_pdf_bytes,
                pdf_filename=pdf_filename,
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_integration.py::TestAutoEmail -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add app/services/job.py tests/test_integration.py
git commit -m "feat: auto-send report email on job completion when enabled"
```

---

### Task 8: Manual Send Certification

Add a "Send Certification" button on the report page that emails the PDF to specified recipients.

**Files:**
- Modify: `app/routes/jobs.py`
- Modify: `app/main.py`
- Modify: `app/templates/report.html`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_routes/test_jobs.py`:

```python
class TestSendCertification:
    @patch("app.routes.jobs.send_report_email")
    def test_send_certification_success(self, mock_send, client, db_session):
        from app.enums import JobStatus, VerificationStatus
        from app.models import Job, JobResult, Preset

        mock_send.return_value = True

        preset = Preset(
            name="cert-test",
            sheets_per_doc=1,
            email_recipients="default@example.com",
        )
        db_session.add(preset)
        db_session.commit()
        db_session.refresh(preset)

        job = Job(
            name="cert-test",
            session_id="CERT001",
            date=__import__("datetime").date.today(),
            source_path="/fake",
            preset_id=preset.id,
            status=JobStatus.COMPLETE,
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)

        tmp = Path("/tmp/barcode-test-cert")
        tmp.mkdir(exist_ok=True)
        (tmp / "report.pdf").write_bytes(b"%PDF-1.4 fake")

        result = JobResult(
            job_id=job.id,
            total_barcodes=10,
            total_documents=10,
            total_sheets=10,
            overflow_docs=0,
            diverts_triggered=0,
            insert_count=0,
            verification=VerificationStatus.OK,
            report_path=str(tmp / "report.json"),
            output_dir=str(tmp),
        )
        db_session.add(result)
        db_session.commit()

        r = client.post(f"/api/jobs/{job.id}/report/send", json={
            "recipients": "customer@example.com",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "sent"
        mock_send.assert_called_once()

        (tmp / "report.pdf").unlink()
        tmp.rmdir()

    @patch("app.routes.jobs.send_report_email")
    def test_send_certification_smtp_failure(self, mock_send, client, db_session):
        from app.enums import JobStatus, VerificationStatus
        from app.models import Job, JobResult, Preset

        mock_send.return_value = False

        preset = Preset(name="fail-test", sheets_per_doc=1)
        db_session.add(preset)
        db_session.commit()
        db_session.refresh(preset)

        job = Job(
            name="fail-test",
            session_id="FAIL001",
            date=__import__("datetime").date.today(),
            source_path="/fake",
            preset_id=preset.id,
            status=JobStatus.COMPLETE,
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)

        tmp = Path("/tmp/barcode-test-cert-fail")
        tmp.mkdir(exist_ok=True)
        (tmp / "report.pdf").write_bytes(b"%PDF-1.4 fake")

        result = JobResult(
            job_id=job.id,
            total_barcodes=5,
            total_documents=5,
            total_sheets=5,
            overflow_docs=0,
            diverts_triggered=0,
            insert_count=0,
            verification=VerificationStatus.OK,
            report_path=str(tmp / "report.json"),
            output_dir=str(tmp),
        )
        db_session.add(result)
        db_session.commit()

        r = client.post(f"/api/jobs/{job.id}/report/send", json={
            "recipients": "customer@example.com",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "failed"

        (tmp / "report.pdf").unlink()
        tmp.rmdir()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_routes/test_jobs.py::TestSendCertification -v`
Expected: FAIL with 404 or 405

- [ ] **Step 3: Add the API send endpoint**

In `app/routes/jobs.py`, add imports:

```python
from pydantic import BaseModel
from app.config import settings
from app.services.email import send_report_email
```

Add route:

```python
class SendCertificationRequest(BaseModel):
    recipients: str


@router.post("/{job_id}/report/send")
def send_certification(job_id: int, data: SendCertificationRequest, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job or not job.result:
        raise HTTPException(status_code=404, detail="Job not found")
    output_dir = job.result.output_dir
    if not output_dir:
        raise HTTPException(status_code=404, detail="No output directory")
    pdf_path = Path(output_dir) / "report.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Report PDF not found")

    recipients = [r.strip() for r in data.recipients.split(",") if r.strip()]
    if not recipients:
        raise HTTPException(status_code=400, detail="No recipients specified")

    subject = f"[Barcoding] Certification — {job.name} — {job.session_id}"
    body = (
        f'This certifies that barcoding job "{job.name}" '
        f"(Session: {job.session_id}, Date: {job.date.isoformat()}) "
        f"has been processed and verified.\n\n"
        f"Letters Processed: {job.result.total_documents}\n"
        f"Total Sheets: {job.result.total_sheets}\n"
        f"Barcodes Applied: {job.result.total_barcodes}\n\n"
        f"The attached report contains full processing details.\n\n"
        f"This certification was generated by the Barcoding Application."
    )

    pdf_bytes = pdf_path.read_bytes()
    pdf_filename = f"{job.name}_{job.session_id}_report.pdf"

    success = send_report_email(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        recipients=recipients,
        subject=subject,
        body=body,
        pdf_bytes=pdf_bytes,
        pdf_filename=pdf_filename,
    )

    return {"status": "sent" if success else "failed"}
```

- [ ] **Step 4: Add "Send Certification" UI to report.html**

In `app/templates/report.html`, update the bottom buttons section to:

```html
<p><strong>Output:</strong> {{ result.output_dir }}</p>

<details id="cert-section">
    <summary>Send Certification</summary>
    <label for="cert-recipients">Recipients (comma-separated)
        <input type="text" id="cert-recipients" value="{{ job.preset.email_recipients or '' }}" placeholder="customer@example.com">
    </label>
    <button type="button" id="btn-send-cert" onclick="sendCertification({{ job.id }})">Send Certification Email</button>
    <p id="cert-status"></p>
</details>

<div style="display: flex; gap: 1rem; flex-wrap: wrap; margin-top: 1rem;">
    <a href="/api/jobs/{{ job.id }}/report/download" role="button">Download Report PDF</a>
    <a href="/" role="button" class="secondary">Back to Jobs</a>
</div>
```

- [ ] **Step 5: Add JavaScript for certification send**

In `app/static/js/app.js`, add at the end:

```javascript
function sendCertification(jobId) {
    var recipients = document.getElementById("cert-recipients").value;
    var status = document.getElementById("cert-status");
    var btn = document.getElementById("btn-send-cert");

    if (!recipients.trim()) {
        status.textContent = "Please enter at least one recipient.";
        return;
    }

    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");
    status.textContent = "Sending...";

    fetch("/api/jobs/" + jobId + "/report/send", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({recipients: recipients}),
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status === "sent") {
            status.textContent = "Certification email sent successfully.";
            status.style.color = "var(--pico-ins-color)";
        } else {
            status.textContent = "Failed to send email. Check SMTP settings.";
            status.style.color = "var(--pico-del-color)";
        }
    })
    .catch(function(err) {
        status.textContent = "Error: " + err.message;
        status.style.color = "var(--pico-del-color)";
    })
    .finally(function() {
        btn.disabled = false;
        btn.removeAttribute("aria-busy");
    });
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_routes/test_jobs.py -v`
Expected: All PASS

- [ ] **Step 7: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add app/routes/jobs.py app/templates/report.html app/static/js/app.js tests/test_routes/test_jobs.py
git commit -m "feat: manual send certification email from report page"
```

---

## Summary

| Task | What it does | New files | Key tests |
|---|---|---|---|
| 1 | Fix verification key bug | — | `test_job_completes_without_batch_data` |
| 2 | PDF report generation service | `report_pdf.py` | 11 tests covering layout, content, edge cases |
| 3 | Preset model + config for email | — | `test_create_preset_with_email_settings` |
| 4 | Email service | `email.py` | 6 tests covering message building, SMTP, errors |
| 5 | Cover/end sheet in combined output | — | `test_combined_output_has_cover_and_end_sheets` |
| 6 | PDF download endpoint + button | — | `test_download_returns_pdf` |
| 7 | Auto-send email on completion | — | `test_auto_email_sent_when_enabled`, `test_no_email_when_disabled` |
| 8 | Manual send certification UI | — | `test_send_certification_success`, `test_send_certification_smtp_failure` |
