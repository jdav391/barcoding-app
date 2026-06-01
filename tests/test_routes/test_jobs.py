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
