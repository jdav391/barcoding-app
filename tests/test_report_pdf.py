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
