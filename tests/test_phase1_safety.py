"""Phase 1 safety tests — payload integrity, detection invariants, and
output gating that prevent mis-mailed packets."""
import json
from pathlib import Path

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas as pdf_canvas

from app.config import settings
from app.enums import (
    FeedDirection, IdSource, ImportMethod, JobMode, JobStatus, MatchType,
    PageFormat, RegionRole, VerificationStatus,
)
from app.models import BatchImport, Job, MailPiece, Preset, Region, Template
from app.services.barcode import BarcodePayloadError, generate_barcode_string
from app.services.detector import DetectionError, detect_from_regions
from app.services.job import QUARANTINE_MARKER, run_job


EMBED_CONFIG = {
    "barcode": {
        "anchor": "bottom-right",
        "x_offset_pt": 36,
        "y_offset_pt": 36,
        "module_size_mm": 0.50,
        "quiet_zone_mm": 6.5,
        "dpi": 600,
    },
    "human_readable": {"enabled": False},
}


def _make_preset(db, name="phase1", sheets_per_doc=1, **kwargs):
    preset = Preset(
        name=name,
        sheets_per_doc=sheets_per_doc,
        page_format=PageFormat.DUPLEX,
        feed_direction=FeedDirection.ASCENDING,
        id_source=IdSource.SEQUENTIAL,
        embed_config=EMBED_CONFIG,
        **kwargs,
    )
    db.add(preset)
    db.commit()
    db.refresh(preset)
    return preset


def _make_job(db, source_path, preset=None, template=None, name="phase1-job", session_id="P1-001"):
    job = Job(
        name=name,
        session_id=session_id,
        source_path=str(source_path),
        preset_id=preset.id if preset else None,
        template_id=template.id if template else None,
        mode=JobMode.TEMPLATE if template else JobMode.PRESET,
        status=JobStatus.DRAFT,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


class _FakeRegion:
    _id_counter = 1000

    def __init__(self, role, x, y, width, height,
                 match_type=MatchType.EXACT, match_pattern=None, priority=0):
        self.id = _FakeRegion._id_counter
        _FakeRegion._id_counter += 1
        self.role = role
        self.x, self.y = x, y
        self.width, self.height = width, height
        self.page = 1
        self.match_type = match_type
        self.match_pattern = match_pattern
        self.priority = priority


# ---------------------------------------------------------------------------
# Barcode payload enforcement
# ---------------------------------------------------------------------------

class TestPayloadEnforcement:
    def test_valid_string_generates(self):
        s = generate_barcode_string(123456789, 3, 7, False, False)
        assert s == "0307123456789"

    def test_sheet_number_zero_rejected(self):
        with pytest.raises(BarcodePayloadError):
            generate_barcode_string(1, 0, 5, False, False)

    def test_sheet_number_ten_rejected(self):
        with pytest.raises(BarcodePayloadError):
            generate_barcode_string(1, 10, 10, False, False)

    def test_set_count_ten_rejected(self):
        with pytest.raises(BarcodePayloadError):
            generate_barcode_string(1, 1, 10, False, False)

    def test_sheet_above_set_count_rejected(self):
        with pytest.raises(BarcodePayloadError):
            generate_barcode_string(1, 5, 3, False, False)

    def test_negative_unique_id_rejected(self):
        with pytest.raises(BarcodePayloadError):
            generate_barcode_string(-1, 1, 1, False, False)


# ---------------------------------------------------------------------------
# Detection invariants
# ---------------------------------------------------------------------------

class TestDetectionInvariants:
    def test_duplex_odd_page_count_rejected(self, tmp_dir):
        path = tmp_dir / "odd.pdf"
        c = pdf_canvas.Canvas(str(path), pagesize=letter)
        for i in range(3):
            c.drawString(72, 700, f"Account: {1000 + i}")
            c.showPage()
        c.save()

        regions = [_FakeRegion(RegionRole.GROUP_BOUNDARY, 72, 695, 200, 15)]
        with pytest.raises(DetectionError, match="even page count"):
            detect_from_regions(path, regions, PageFormat.DUPLEX)

    def test_page_counter_disagreement_rejected(self, tmp_dir):
        """Doc spans 2 sheets but declares 'Page 1 of 5' — mis-segmentation."""
        path = tmp_dir / "counter_mismatch.pdf"
        c = pdf_canvas.Canvas(str(path), pagesize=letter)
        for sheet in range(2):
            c.drawString(72, 700, "Account: 1001")
            c.drawString(72, 680, f"Page {sheet + 1} of 5")
            c.showPage()
            c.showPage()  # side B
        c.save()

        regions = [
            _FakeRegion(RegionRole.GROUP_BOUNDARY, 72, 695, 200, 15),
            _FakeRegion(RegionRole.PAGE_COUNTER, 72, 675, 200, 15),
        ]
        with pytest.raises(DetectionError, match="mis-segmented"):
            detect_from_regions(path, regions, PageFormat.DUPLEX)

    def test_sheet_count_always_matches_side_a_pages(self, sample_multi_doc_pdf):
        regions = [_FakeRegion(RegionRole.GROUP_BOUNDARY, 72, 695, 200, 15)]
        docs = detect_from_regions(sample_multi_doc_pdf, regions, PageFormat.DUPLEX)
        for d in docs:
            assert d.sheet_count == len(d.side_a_pages)

    def test_max_sheets_guard_catches_merged_docs(self, sample_duplex_pdf):
        # No GROUP_BOUNDARY regions -> everything merges into one 10-sheet doc
        regions = [_FakeRegion(RegionRole.UNIQUE_ID, 72, 655, 200, 15,
                               match_type=MatchType.NUMERIC)]
        with pytest.raises(DetectionError, match="merged"):
            detect_from_regions(
                sample_duplex_pdf, regions, PageFormat.DUPLEX,
                max_sheets_per_doc=9,
            )

    def test_empty_signature_pages_reported(self, sample_first_page_only_pdf):
        regions = [_FakeRegion(RegionRole.GROUP_BOUNDARY, 72, 695, 250, 15)]
        warnings: list[str] = []
        docs = detect_from_regions(
            sample_first_page_only_pdf, regions, PageFormat.DUPLEX,
            warnings=warnings,
        )
        assert len(docs) == 3
        assert len(warnings) == 1
        assert "2 side-A page(s)" in warnings[0]


# ---------------------------------------------------------------------------
# Pipeline safety
# ---------------------------------------------------------------------------

class TestUniqueIdIntegrity:
    def test_duplicate_extracted_uids_abort_job(self, db_session, tmp_dir):
        """Two different recipients carrying the same ID must stop the job."""
        path = tmp_dir / "dup_uid.pdf"
        c = pdf_canvas.Canvas(str(path), pagesize=letter)
        for account in ("1001", "1002"):
            c.drawString(72, 700, f"Account: {account}")
            c.drawString(72, 660, "ID: 999888777")
            c.showPage()
            c.showPage()  # side B
        c.save()

        template = Template(
            name="dup-uid", page_format=PageFormat.DUPLEX,
            feed_direction=FeedDirection.ASCENDING, has_insert=False,
            embed_config=EMBED_CONFIG,
        )
        db_session.add(template)
        db_session.commit()
        db_session.refresh(template)
        for role, y in ((RegionRole.GROUP_BOUNDARY, 695), (RegionRole.UNIQUE_ID, 655)):
            db_session.add(Region(
                template_id=template.id, name=str(role), role=role,
                page=1, x=72, y=y, width=200, height=15,
                match_type=MatchType.NUMERIC if role == RegionRole.UNIQUE_ID else MatchType.EXACT,
            ))
        db_session.commit()

        job = _make_job(db_session, path, template=template, name="dup-uid")
        with pytest.raises(ValueError, match="Duplicate unique ID"):
            run_job(db_session, job)
        assert job.status == JobStatus.ERROR
        assert "Duplicate unique ID" in job.error_message


class TestVerificationGating:
    def test_mismatch_quarantines_output(self, db_session, sample_duplex_pdf):
        preset = _make_preset(db_session, name="quarantine")
        job = _make_job(db_session, sample_duplex_pdf, preset=preset, name="quarantine")
        db_session.add(BatchImport(
            job_id=job.id, batch_id="B1",
            expected_letters=12, expected_sheets=12,  # PDF actually has 10
            import_method=ImportMethod.MANUAL,
        ))
        db_session.commit()

        result = run_job(db_session, job)

        assert result.verification == VerificationStatus.MISMATCH
        output_dir = Path(result.output_dir)
        assert not (output_dir / "combined_output.pdf").exists()
        marker = output_dir / QUARANTINE_MARKER
        assert marker.exists()
        assert "Do not feed" in marker.read_text()

    def test_ok_run_produces_combined_and_no_marker(self, db_session, sample_duplex_pdf):
        preset = _make_preset(db_session, name="ok-run")
        job = _make_job(db_session, sample_duplex_pdf, preset=preset, name="ok-run")
        db_session.add(BatchImport(
            job_id=job.id, batch_id="B1",
            expected_letters=10, expected_sheets=10,
            import_method=ImportMethod.MANUAL,
        ))
        db_session.commit()

        result = run_job(db_session, job)

        output_dir = Path(result.output_dir)
        assert (output_dir / "combined_output.pdf").exists()
        assert not (output_dir / QUARANTINE_MARKER).exists()


class TestOutputProtection:
    def test_refuses_to_overwrite_prior_run(self, db_session, sample_duplex_pdf):
        preset = _make_preset(db_session, name="no-overwrite")
        job1 = _make_job(db_session, sample_duplex_pdf, preset=preset, name="no-overwrite")
        run_job(db_session, job1)

        # Same name/session/date -> same output directory
        job2 = _make_job(db_session, sample_duplex_pdf, preset=preset, name="no-overwrite")
        with pytest.raises(ValueError, match="refusing to overwrite"):
            run_job(db_session, job2)

    def test_completed_job_cannot_be_rerun(self, db_session, sample_duplex_pdf):
        preset = _make_preset(db_session, name="rerun-guard")
        job = _make_job(db_session, sample_duplex_pdf, preset=preset, name="rerun-guard")
        run_job(db_session, job)
        assert job.status == JobStatus.COMPLETE

        with pytest.raises(ValueError, match="already running or complete"):
            run_job(db_session, job)


class TestResumeAccountability:
    def test_resume_reports_full_totals(self, db_session, sample_duplex_pdf):
        """Resumed runs must report whole-job totals, not just the tail."""
        preset = _make_preset(db_session, name="resume-totals")
        job = _make_job(db_session, sample_duplex_pdf, preset=preset, name="resume-totals")
        db_session.add(BatchImport(
            job_id=job.id, batch_id="B1",
            expected_letters=10, expected_sheets=10,
            import_method=ImportMethod.MANUAL,
        ))
        db_session.commit()

        run_job(db_session, job)

        # Simulate an interruption after doc 2 and resume
        job.last_processed_index = 2
        job.status = JobStatus.PARTIAL
        job.completed_at = None
        db_session.commit()

        result = run_job(db_session, job)

        assert result.total_documents == 10
        assert result.total_sheets == 10
        assert result.total_barcodes == 10
        assert result.verification == VerificationStatus.OK

        pieces = db_session.query(MailPiece).filter_by(job_id=job.id).all()
        assert len(pieces) == 10
        assert len({p.doc_index for p in pieces}) == 10

    def test_mail_pieces_recorded_per_document(self, db_session, sample_duplex_pdf):
        preset = _make_preset(db_session, name="piece-records")
        job = _make_job(db_session, sample_duplex_pdf, preset=preset, name="piece-records")
        run_job(db_session, job)

        pieces = (
            db_session.query(MailPiece)
            .filter_by(job_id=job.id)
            .order_by(MailPiece.doc_index)
            .all()
        )
        assert len(pieces) == 10
        for p in pieces:
            assert len(p.barcodes) == p.sheet_count == 1
            assert Path(p.output_path).exists()
            # Every persisted barcode is a valid payload
            from app.services.barcode import validate_barcode_string
            assert all(validate_barcode_string(b) for b in p.barcodes)


class TestClearZone:
    def _pdf_with_corner_text(self, tmp_dir):
        """Letter page with text inside the bottom-right barcode footprint."""
        path = tmp_dir / "corner_text.pdf"
        c = pdf_canvas.Canvas(str(path), pagesize=letter)
        for _ in range(2):  # 1 duplex doc set
            c.drawString(72, 700, "Body text")
            c.drawString(530, 60, "FOOTER-IN-ZONE")
            c.showPage()
        c.save()
        return path

    def test_warn_mode_records_warning(self, db_session, tmp_dir, monkeypatch):
        monkeypatch.setattr(settings, "clear_zone_mode", "warn")
        path = self._pdf_with_corner_text(tmp_dir)
        preset = _make_preset(db_session, name="cz-warn")
        job = _make_job(db_session, path, preset=preset, name="cz-warn")

        result = run_job(db_session, job)

        report = json.loads(Path(result.report_path).read_text())
        assert any("clear-zone" in w for w in report["warnings"])

    def test_abort_mode_stops_job(self, db_session, tmp_dir, monkeypatch):
        monkeypatch.setattr(settings, "clear_zone_mode", "abort")
        path = self._pdf_with_corner_text(tmp_dir)
        preset = _make_preset(db_session, name="cz-abort")
        job = _make_job(db_session, path, preset=preset, name="cz-abort")

        with pytest.raises(ValueError, match="clear-zone"):
            run_job(db_session, job)
        assert job.status == JobStatus.ERROR

    def test_clean_page_passes(self, db_session, sample_duplex_pdf, monkeypatch):
        monkeypatch.setattr(settings, "clear_zone_mode", "abort")
        preset = _make_preset(db_session, name="cz-clean")
        job = _make_job(db_session, sample_duplex_pdf, preset=preset, name="cz-clean")

        result = run_job(db_session, job)
        assert result.total_documents == 10


class TestRegionRegexValidation:
    def test_invalid_regex_rejected_at_save(self):
        from pydantic import ValidationError
        from app.schemas import RegionCreate

        with pytest.raises(ValidationError, match="Invalid regex"):
            RegionCreate(
                name="bad", role=RegionRole.PAGE_COUNTER,
                x=0, y=0, width=10, height=10,
                match_type=MatchType.REGEX, match_pattern="(unclosed",
            )

    def test_regex_without_pattern_rejected(self):
        from pydantic import ValidationError
        from app.schemas import RegionCreate

        with pytest.raises(ValidationError, match="requires a match_pattern"):
            RegionCreate(
                name="bad", role=RegionRole.PAGE_COUNTER,
                x=0, y=0, width=10, height=10,
                match_type=MatchType.REGEX, match_pattern=None,
            )

    def test_valid_regex_accepted(self):
        from app.schemas import RegionCreate

        region = RegionCreate(
            name="ok", role=RegionRole.PAGE_COUNTER,
            x=0, y=0, width=10, height=10,
            match_type=MatchType.REGEX, match_pattern=r"Page (\d+) of (\d+)",
        )
        assert region.match_pattern == r"Page (\d+) of (\d+)"
