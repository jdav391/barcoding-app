from pypdf import PdfReader
import io

from app.services.session_report import generate_session_report_pdf


class TestSessionReportPdf:
    def test_generates_valid_pdf(self):
        report_data = {
            "session_name": "DLD Tuesday",
            "session_id": "2026-05-24-001",
            "date": "2026-05-24",
            "jobs": [
                {
                    "name": "1pg-no-insert",
                    "source_file": "1pg-no-insert.pdf",
                    "preset": "Single Sheet",
                    "documents": 50,
                    "sheets": 50,
                    "barcodes": 50,
                    "status": "COMPLETE",
                },
                {
                    "name": "2pg-no-insert",
                    "source_file": "2pg-no-insert.pdf",
                    "preset": "Two Sheet",
                    "documents": 30,
                    "sheets": 60,
                    "barcodes": 60,
                    "status": "COMPLETE",
                },
            ],
            "totals": {
                "total_documents": 80,
                "total_sheets": 110,
                "total_barcodes": 110,
                "overflow_documents": 0,
            },
        }

        pdf_bytes = generate_session_report_pdf(report_data)
        assert len(pdf_bytes) > 0
        assert pdf_bytes[:5] == b"%PDF-"

        reader = PdfReader(io.BytesIO(pdf_bytes))
        assert len(reader.pages) == 1

        text = reader.pages[0].extract_text()
        assert "Braze Codes Session Report" in text
        assert "DLD Tuesday" in text
        assert "2026-05-24-001" in text

    def test_includes_all_jobs(self):
        report_data = {
            "session_name": "Test",
            "session_id": "TEST-001",
            "date": "2026-05-24",
            "jobs": [
                {"name": f"Job-{i}", "source_file": f"file{i}.pdf", "preset": "P",
                 "documents": 10, "sheets": 10, "barcodes": 10, "status": "COMPLETE"}
                for i in range(5)
            ],
            "totals": {
                "total_documents": 50,
                "total_sheets": 50,
                "total_barcodes": 50,
                "overflow_documents": 0,
            },
        }

        pdf_bytes = generate_session_report_pdf(report_data)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = reader.pages[0].extract_text()
        for i in range(5):
            assert f"Job-{i}" in text
