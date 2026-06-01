import json
from pathlib import Path
from unittest.mock import patch

from app.enums import FeedDirection, IdSource, ImportMethod, JobStatus, PageFormat
from app.models import BatchImport, Job, Preset
from app.services.job import run_job


class TestEndToEndPipeline:
    def test_single_sheet_duplex_job(self, db_session, sample_duplex_pdf, tmp_dir):
        preset = Preset(
            name="Test Single Sheet",
            sheets_per_doc=1,
            page_format=PageFormat.DUPLEX,
            has_insert=False,
            has_divert=False,
            divert_overflow=False,
            feed_direction=FeedDirection.ASCENDING,
            id_source=IdSource.SEQUENTIAL,
            embed_config={
                "barcode": {
                    "anchor": "bottom-right",
                    "x_offset_pt": 36,
                    "y_offset_pt": 36,
                    "module_size_mm": 0.50,
                    "quiet_zone_mm": 6.5,
                    "dpi": 600,
                },
                "human_readable": {"enabled": False},
            },
        )
        db_session.add(preset)
        db_session.commit()

        job = Job(
            name="Test Job",
            session_id="TEST-001",
            source_path=str(sample_duplex_pdf),
            preset_id=preset.id,
            status=JobStatus.DRAFT,
        )
        db_session.add(job)
        db_session.commit()

        batch = BatchImport(
            job_id=job.id,
            batch_id="TestBatch",
            expected_letters=10,
            expected_sheets=10,
            import_method=ImportMethod.MANUAL,
        )
        db_session.add(batch)
        db_session.commit()

        result = run_job(db_session, job)

        assert job.status == JobStatus.COMPLETE
        assert result.total_documents == 10
        assert result.total_sheets == 10
        assert result.total_barcodes == 10
        assert result.overflow_docs == 0

        output_dir = Path(result.output_dir)
        assert (output_dir / "machine_ready").exists()
        assert (output_dir / "combined_output.pdf").exists()
        assert (output_dir / "report.json").exists()

        report = json.loads((output_dir / "report.json").read_text())
        assert report["status"] == "OK"
        assert report["verification"]["match"] is True

        machine_files = list((output_dir / "machine_ready").glob("*.pdf"))
        assert len(machine_files) == 10

    def test_multisheet_with_overflow(self, db_session, tmp_dir):
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        pdf_path = tmp_dir / "overflow_test.pdf"
        c = canvas.Canvas(str(pdf_path), pagesize=letter)
        for i in range(84):
            c.drawString(72, 700, f"Page {i + 1}")
            c.showPage()
        c.save()

        preset = Preset(
            name="Test Overflow",
            sheets_per_doc=7,
            page_format=PageFormat.DUPLEX,
            has_insert=False,
            has_divert=True,
            divert_overflow=True,
            feed_direction=FeedDirection.ASCENDING,
            id_source=IdSource.SEQUENTIAL,
            embed_config={
                "barcode": {
                    "anchor": "bottom-right",
                    "x_offset_pt": 36,
                    "y_offset_pt": 36,
                    "module_size_mm": 0.50,
                    "quiet_zone_mm": 6.5,
                    "dpi": 600,
                },
                "human_readable": {"enabled": False},
            },
        )
        db_session.add(preset)
        db_session.commit()

        job = Job(
            name="Overflow Test",
            session_id="TEST-002",
            source_path=str(pdf_path),
            preset_id=preset.id,
            status=JobStatus.DRAFT,
        )
        db_session.add(job)
        db_session.commit()

        result = run_job(db_session, job)

        assert result.total_documents == 6
        assert result.overflow_docs == 6
        assert result.diverts_triggered > 0

        output_dir = Path(result.output_dir)
        overflow_files = list((output_dir / "manual_overflow").glob("*.pdf"))
        assert len(overflow_files) == 6


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
        assert "BrazeBars Job Report" in first_text
        assert "BrazeBars Job Report" in last_text


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
        assert call_kwargs.kwargs["subject"].startswith("[BrazeBars]")

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


class TestJobResume:
    def test_resume_partial_job_includes_all_files_in_combined_output(self, db_session, sample_duplex_pdf):
        from pypdf import PdfReader

        from app.enums import FeedDirection, IdSource, JobStatus, PageFormat
        from app.models import Job, Preset
        from app.services.job import run_job

        preset = Preset(
            name="resume-test",
            sheets_per_doc=1,
            page_format=PageFormat.DUPLEX,
            feed_direction=FeedDirection.ASCENDING,
            id_source=IdSource.SEQUENTIAL,
            embed_config={
                "barcode": {
                    "anchor": "bottom-right",
                    "x_offset_pt": 36,
                    "y_offset_pt": 36,
                    "module_size_mm": 0.50,
                    "quiet_zone_mm": 6.5,
                    "dpi": 600,
                },
                "human_readable": {"enabled": False},
            },
        )
        db_session.add(preset)
        db_session.commit()
        db_session.refresh(preset)

        job = Job(
            name="resume-test",
            session_id="RS001",
            date=__import__("datetime").date.today(),
            source_path=str(sample_duplex_pdf),
            preset_id=preset.id,
            status=JobStatus.DRAFT,
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)

        # First run: full job to establish baseline page count
        result = run_job(db_session, job)
        output_dir = Path(result.output_dir)
        combined_path = output_dir / "combined_output.pdf"
        baseline_reader = PdfReader(str(combined_path))
        baseline_page_count = len(baseline_reader.pages)

        # Simulate a partial run by rolling back progress
        job.last_processed_index = 2
        job.status = JobStatus.PARTIAL
        job.completed_at = None
        db_session.commit()

        # Second run: resume from where we left off
        result2 = run_job(db_session, job)
        output_dir2 = Path(result2.output_dir)
        combined_path2 = output_dir2 / "combined_output.pdf"
        resume_reader = PdfReader(str(combined_path2))
        resume_page_count = len(resume_reader.pages)

        assert resume_page_count == baseline_page_count, (
            f"Resume combined output has {resume_page_count} pages, "
            f"expected {baseline_page_count}"
        )


class TestTemplateModePipeline:
    """Integration tests for template-based auto-detection pipeline."""

    def test_template_mode_basic(self, db_session, sample_multi_doc_pdf):
        from app.enums import JobMode, MatchType, RegionRole
        from app.models import Template, Region

        template = Template(
            name="Test Template",
            page_format=PageFormat.DUPLEX,
            feed_direction=FeedDirection.ASCENDING,
            has_insert=False,
            embed_config={
                "barcode": {
                    "anchor": "bottom-right",
                    "x_offset_pt": 36,
                    "y_offset_pt": 36,
                    "module_size_mm": 0.50,
                    "quiet_zone_mm": 6.5,
                    "dpi": 600,
                },
                "human_readable": {"enabled": False},
            },
        )
        db_session.add(template)
        db_session.commit()
        db_session.refresh(template)

        regions = [
            Region(
                template_id=template.id, name="Account",
                role=RegionRole.GROUP_BOUNDARY,
                page=1, x=72, y=695, width=200, height=15,
                match_type=MatchType.EXACT, match_pattern=None, priority=0,
            ),
            Region(
                template_id=template.id, name="Page Counter",
                role=RegionRole.PAGE_COUNTER,
                page=1, x=72, y=675, width=200, height=15,
                match_type=MatchType.REGEX,
                match_pattern=r"Page (\d+) of (\d+)", priority=0,
            ),
            Region(
                template_id=template.id, name="UID",
                role=RegionRole.UNIQUE_ID,
                page=1, x=72, y=655, width=200, height=15,
                match_type=MatchType.NUMERIC, match_pattern=None, priority=0,
            ),
        ]
        for r in regions:
            db_session.add(r)
        db_session.commit()

        job = Job(
            name="Template Test",
            session_id="TT001",
            source_path=str(sample_multi_doc_pdf),
            template_id=template.id,
            mode=JobMode.TEMPLATE,
            status=JobStatus.DRAFT,
        )
        db_session.add(job)
        db_session.commit()

        result = run_job(db_session, job)

        assert job.status == JobStatus.COMPLETE
        assert result.total_documents == 3
        assert result.total_sheets == 4
        assert result.total_barcodes == 4
        assert result.overflow_docs == 0
        assert result.diverts_triggered == 0

        output_dir = Path(result.output_dir)
        assert (output_dir / "machine_ready").exists()
        assert (output_dir / "combined_output.pdf").exists()
        assert (output_dir / "report.json").exists()

        machine_files = list((output_dir / "machine_ready").glob("*.pdf"))
        assert len(machine_files) == 3

        report = json.loads((output_dir / "report.json").read_text())
        assert report["status"] == "OK"
        assert report["totals"]["documents_processed"] == 3
        assert report["totals"]["total_sheets"] == 4

    def test_template_mode_no_unique_id(self, db_session, sample_multi_doc_pdf):
        from app.enums import JobMode, MatchType, RegionRole
        from app.models import Template, Region

        template = Template(
            name="No UID Template",
            page_format=PageFormat.DUPLEX,
            feed_direction=FeedDirection.ASCENDING,
            has_insert=False,
            embed_config={
                "barcode": {
                    "anchor": "bottom-right",
                    "x_offset_pt": 36,
                    "y_offset_pt": 36,
                    "module_size_mm": 0.50,
                    "quiet_zone_mm": 6.5,
                    "dpi": 600,
                },
                "human_readable": {"enabled": False},
            },
        )
        db_session.add(template)
        db_session.commit()
        db_session.refresh(template)

        # Only GROUP_BOUNDARY and PAGE_COUNTER regions, no UNIQUE_ID
        regions = [
            Region(
                template_id=template.id, name="Account",
                role=RegionRole.GROUP_BOUNDARY,
                page=1, x=72, y=695, width=200, height=15,
                match_type=MatchType.EXACT, match_pattern=None, priority=0,
            ),
            Region(
                template_id=template.id, name="Page Counter",
                role=RegionRole.PAGE_COUNTER,
                page=1, x=72, y=675, width=200, height=15,
                match_type=MatchType.REGEX,
                match_pattern=r"Page (\d+) of (\d+)", priority=0,
            ),
        ]
        for r in regions:
            db_session.add(r)
        db_session.commit()

        job = Job(
            name="No UID Test",
            session_id="NU001",
            source_path=str(sample_multi_doc_pdf),
            template_id=template.id,
            mode=JobMode.TEMPLATE,
            status=JobStatus.DRAFT,
        )
        db_session.add(job)
        db_session.commit()

        result = run_job(db_session, job)

        assert job.status == JobStatus.COMPLETE
        assert result.total_documents == 3
        assert result.total_sheets == 4
        assert result.total_barcodes == 4

        output_dir = Path(result.output_dir)
        machine_files = list((output_dir / "machine_ready").glob("*.pdf"))
        assert len(machine_files) == 3


class TestSessionCompile:
    def test_multi_job_session_compile(self, db_session, tmp_dir):
        """Two jobs in a session, compile merges their outputs."""
        from pypdf import PdfReader

        from app.enums import FeedDirection, IdSource, JobStatus, OutputMode, PageFormat
        from app.models import Job, Preset, Session
        from app.services.job import run_job
        from app.services.session import compile_session
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        preset = Preset(
            name="multi-test",
            sheets_per_doc=1,
            page_format=PageFormat.DUPLEX,
            feed_direction=FeedDirection.ASCENDING,
            id_source=IdSource.SEQUENTIAL,
            embed_config={
                "barcode": {
                    "anchor": "bottom-right",
                    "x_offset_pt": 36,
                    "y_offset_pt": 36,
                    "module_size_mm": 0.50,
                    "quiet_zone_mm": 6.5,
                    "dpi": 600,
                },
                "human_readable": {"enabled": False},
            },
        )
        db_session.add(preset)
        db_session.commit()
        db_session.refresh(preset)

        session_obj = Session(
            name="Multi Test",
            session_id="MULTI-001",
            output_mode=OutputMode.COMBINED,
        )
        db_session.add(session_obj)
        db_session.commit()
        db_session.refresh(session_obj)

        # PDF A: 4 pages = 2 doc sets
        pdf_a = tmp_dir / "batch_a.pdf"
        c = canvas.Canvas(str(pdf_a), pagesize=letter)
        for i in range(4):
            c.drawString(72, 700, f"Batch A Page {i + 1}")
            c.showPage()
        c.save()

        # PDF B: 6 pages = 3 doc sets
        pdf_b = tmp_dir / "batch_b.pdf"
        c = canvas.Canvas(str(pdf_b), pagesize=letter)
        for i in range(6):
            c.drawString(72, 700, f"Batch B Page {i + 1}")
            c.showPage()
        c.save()

        job_a = Job(
            name="Multi Test A",
            session_id="MULTI-001",
            session_fk=session_obj.id,
            source_path=str(pdf_a),
            preset_id=preset.id,
            status=JobStatus.DRAFT,
        )
        job_b = Job(
            name="Multi Test B",
            session_id="MULTI-001",
            session_fk=session_obj.id,
            source_path=str(pdf_b),
            preset_id=preset.id,
            status=JobStatus.DRAFT,
        )
        db_session.add(job_a)
        db_session.add(job_b)
        db_session.commit()

        run_job(db_session, job_a)
        run_job(db_session, job_b)

        assert job_a.status == JobStatus.COMPLETE
        assert job_b.status == JobStatus.COMPLETE

        result = compile_session(db_session, session_obj, base_output_dir=str(tmp_dir))

        assert result["status"] == "ok"
        assert result["total_documents"] == 5  # 2 + 3

        compiled_pdf = PdfReader(result["compiled_path"])
        # 5 docs × 2 pages each = 10 + cover + end = 12
        assert len(compiled_pdf.pages) == 12

        first_text = compiled_pdf.pages[0].extract_text()
        assert "BrazeBars Session Report" in first_text
