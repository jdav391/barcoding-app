"""Tests for multi-pocket insert counts and watched intake directories."""
import shutil
from pathlib import Path

import pytest

from app.enums import (
    FeedDirection, IdSource, JobMode, JobStatus, MatchType, PageFormat, RegionRole,
)
from app.models import Job, MailPiece, Preset, Region, Template
from app.services.barcode import BarcodePayloadError, generate_barcode_string
from app.services.job import run_job
from app.services.watcher import find_stable_pdfs, ingest_file, process_template_dirs

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


# ---------------------------------------------------------------------------
# Multi-pocket insert counts
# ---------------------------------------------------------------------------

class TestInsertPockets:
    def test_insert_counts_encode_as_position_3(self):
        for n in range(5):
            s = generate_barcode_string(42, 1, 1, insert_count=n, is_end_of_group=True)
            assert s[2] == str(n)

    def test_insert_count_five_rejected(self):
        with pytest.raises(BarcodePayloadError, match="insert_count"):
            generate_barcode_string(42, 1, 1, insert_count=5, is_end_of_group=True)

    def test_legacy_bool_callers_still_work(self):
        assert generate_barcode_string(42, 1, 1, True, True)[2] == "1"
        assert generate_barcode_string(42, 1, 1, False, True)[2] == "0"

    def test_preset_insert_count_flows_to_barcodes(self, db_session, sample_duplex_pdf):
        preset = Preset(
            name="pockets-3",
            sheets_per_doc=1,
            page_format=PageFormat.DUPLEX,
            feed_direction=FeedDirection.ASCENDING,
            id_source=IdSource.SEQUENTIAL,
            insert_count=3,
            has_insert=True,
            embed_config=EMBED_CONFIG,
        )
        db_session.add(preset)
        db_session.commit()
        job = Job(
            name="pockets-3", session_id="PK-001",
            source_path=str(sample_duplex_pdf),
            preset_id=preset.id, status=JobStatus.DRAFT,
        )
        db_session.add(job)
        db_session.commit()

        result = run_job(db_session, job)

        pieces = db_session.query(MailPiece).filter_by(job_id=job.id).all()
        assert all(p.insert_count == 3 for p in pieces)
        assert all(b[2] == "3" for p in pieces for b in p.barcodes)
        assert result.insert_count == 10  # all 10 sheets carry an insert flag

    def test_preset_schema_legacy_has_insert_maps_to_one(self):
        from app.schemas import PresetCreate

        legacy = PresetCreate(name="x", sheets_per_doc=1, has_insert=True)
        assert legacy.insert_count == 1
        modern = PresetCreate(name="x", sheets_per_doc=1, insert_count=4)
        assert modern.has_insert is True
        with pytest.raises(Exception):
            PresetCreate(name="x", sheets_per_doc=1, insert_count=5)


# ---------------------------------------------------------------------------
# Watched intake directories
# ---------------------------------------------------------------------------

def _make_template(db, input_dir=None):
    template = Template(
        name="intake-template",
        page_format=PageFormat.DUPLEX,
        feed_direction=FeedDirection.ASCENDING,
        embed_config=EMBED_CONFIG,
        input_dir=str(input_dir) if input_dir else None,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    db.add(Region(
        template_id=template.id, name="Account",
        role=RegionRole.GROUP_BOUNDARY,
        page=1, x=72, y=695, width=200, height=15,
        match_type=MatchType.EXACT, match_pattern=None, priority=0,
    ))
    db.commit()
    return template


class TestStability:
    def test_file_not_picked_up_on_first_sight(self, tmp_path):
        (tmp_path / "batch.pdf").write_bytes(b"%PDF-1.4")
        state: dict = {}
        assert find_stable_pdfs(tmp_path, state) == []

    def test_file_picked_up_once_stable(self, tmp_path):
        f = tmp_path / "batch.pdf"
        f.write_bytes(b"%PDF-1.4")
        state: dict = {}
        find_stable_pdfs(tmp_path, state)
        assert find_stable_pdfs(tmp_path, state) == [f]

    def test_growing_file_not_picked_up(self, tmp_path):
        import os
        f = tmp_path / "batch.pdf"
        f.write_bytes(b"%PDF-1.4")
        state: dict = {}
        find_stable_pdfs(tmp_path, state)
        f.write_bytes(b"%PDF-1.4 more data appended")
        os.utime(f, (f.stat().st_atime, f.stat().st_mtime + 10))
        assert find_stable_pdfs(tmp_path, state) == []

    def test_non_pdf_and_hidden_ignored(self, tmp_path):
        (tmp_path / "notes.txt").write_text("x")
        (tmp_path / ".partial.pdf").write_bytes(b"x")
        state: dict = {}
        find_stable_pdfs(tmp_path, state)
        assert find_stable_pdfs(tmp_path, state) == []


class TestIngest:
    def test_ingest_moves_file_and_creates_job(self, db_session, tmp_path, sample_multi_doc_pdf):
        intake = tmp_path / "intake"
        intake.mkdir()
        template = _make_template(db_session, intake)
        dropped = intake / "LetterBatch123.pdf"
        shutil.copy(sample_multi_doc_pdf, dropped)

        job = ingest_file(db_session, template, dropped)

        assert not dropped.exists(), "file must leave the intake root"
        ingested = intake / "ingested" / "LetterBatch123.pdf"
        assert ingested.exists()
        assert job.source_path == str(ingested)
        assert job.mode == JobMode.TEMPLATE
        assert job.template_id == template.id
        assert job.name == "LetterBatch123"
        assert job.session_id.startswith("AUTO-")


class TestEndToEndIntake:
    def test_scan_processes_dropped_pdf(self, db_session, tmp_path, sample_multi_doc_pdf):
        intake = tmp_path / "intake"
        intake.mkdir()
        _make_template(db_session, intake)
        shutil.copy(sample_multi_doc_pdf, intake / "Batch709999.pdf")

        state: dict = {}
        assert process_template_dirs(db_session, state) == []  # first scan: not stable yet
        jobs = process_template_dirs(db_session, state)        # second scan: processed

        assert len(jobs) == 1
        job = jobs[0]
        assert job.status == JobStatus.COMPLETE
        assert job.result.total_documents == 3
        output_dir = Path(job.result.output_dir)
        assert output_dir.parent == intake / "ingested"
        assert (output_dir / "combined_output.pdf").exists()

    def test_failed_job_writes_error_marker_and_continues(self, db_session, tmp_path):
        intake = tmp_path / "intake"
        intake.mkdir()
        _make_template(db_session, intake)
        # Not a real PDF -> detection/processing must fail
        (intake / "corrupt.pdf").write_bytes(b"%PDF-1.4 garbage")

        state: dict = {}
        process_template_dirs(db_session, state)
        jobs = process_template_dirs(db_session, state)

        assert len(jobs) == 1
        assert jobs[0].status == JobStatus.ERROR
        marker = intake / "ingested" / "corrupt.ERROR.txt"
        assert marker.exists()
        assert "Error:" in marker.read_text()

    def test_templates_without_input_dir_ignored(self, db_session, tmp_path):
        _make_template(db_session, None)
        assert process_template_dirs(db_session, {}) == []
