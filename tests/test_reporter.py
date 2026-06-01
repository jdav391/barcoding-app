from app.services.reporter import verify_against_imports, generate_report
from app.enums import VerificationStatus


class TestVerifyAgainstImports:
    def test_matching_counts(self):
        actual = {"total_documents": 296, "total_sheets": 592}
        expected = [{"expected_letters": 296, "expected_sheets": 592}]
        result = verify_against_imports(actual, expected)
        assert result.status == VerificationStatus.OK
        assert result.match is True

    def test_letter_mismatch(self):
        actual = {"total_documents": 295, "total_sheets": 592}
        expected = [{"expected_letters": 296, "expected_sheets": 592}]
        result = verify_against_imports(actual, expected)
        assert result.status == VerificationStatus.MISMATCH
        assert result.match is False
        assert "documents" in result.details.lower()

    def test_sheet_mismatch(self):
        actual = {"total_documents": 296, "total_sheets": 590}
        expected = [{"expected_letters": 296, "expected_sheets": 592}]
        result = verify_against_imports(actual, expected)
        assert result.status == VerificationStatus.MISMATCH
        assert "sheets" in result.details.lower()

    def test_multiple_imports_summed(self):
        actual = {"total_documents": 350, "total_sheets": 700}
        expected = [
            {"expected_letters": 200, "expected_sheets": 400},
            {"expected_letters": 150, "expected_sheets": 300},
        ]
        result = verify_against_imports(actual, expected)
        assert result.status == VerificationStatus.OK

    def test_no_imports_skips_verification(self):
        actual = {"total_documents": 100, "total_sheets": 200}
        result = verify_against_imports(actual, [])
        assert result.status == VerificationStatus.OK
        assert result.match is True


class TestGenerateReport:
    def test_report_structure(self):
        job_info = {"name": "Daily Letters", "session_id": "20260519-001", "date": "2026-05-19"}
        totals = {
            "total_documents": 296,
            "total_sheets": 592,
            "total_barcodes": 592,
            "inserts_triggered": 0,
            "diverts_triggered": 0,
            "overflow_documents": 0,
        }
        imports = [{"expected_letters": 296, "expected_sheets": 592}]
        report = generate_report(job_info, totals, imports)
        assert report["job"] == "Daily Letters"
        assert report["session_id"] == "20260519-001"
        assert report["status"] == "OK"
        assert report["totals"]["documents_processed"] == 296
        assert report["verification"]["match"] is True
        assert report["verification"]["verdict"] == "OK"

    def test_report_with_overflow(self):
        job_info = {"name": "Test", "session_id": "001", "date": "2026-05-19"}
        totals = {
            "total_documents": 10,
            "total_sheets": 50,
            "total_barcodes": 50,
            "inserts_triggered": 0,
            "diverts_triggered": 2,
            "overflow_documents": 2,
        }
        overflow = [{"doc_index": 5, "sheets": 8}, {"doc_index": 9, "sheets": 7}]
        report = generate_report(job_info, totals, [], overflow_detail=overflow)
        assert report["totals"]["overflow_documents"] == 2
        assert len(report["overflow_detail"]) == 2
