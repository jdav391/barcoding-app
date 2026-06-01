import json
from datetime import date
from pathlib import Path

from app.enums import JobStatus, OutputMode
from app.models import Job, JobResult, Preset, Session
from app.schemas import SessionCreate, SessionResponse
from app.services.session import compile_session


class TestSessionModel:
    def test_create_session(self, db_session):
        session = Session(
            name="DLD Tuesday",
            session_id="2026-05-24-001",
            date=date(2026, 5, 24),
            output_mode=OutputMode.COMBINED,
        )
        db_session.add(session)
        db_session.commit()
        db_session.refresh(session)

        assert session.id is not None
        assert session.name == "DLD Tuesday"
        assert session.session_id == "2026-05-24-001"
        assert session.output_mode == OutputMode.COMBINED
        assert session.compiled_output_path is None
        assert session.created_at is not None

    def test_session_job_relationship(self, db_session):
        from app.models import Job
        from app.enums import JobStatus

        session = Session(
            name="Relationship Test",
            session_id="2026-05-24-002",
            date=date(2026, 5, 24),
            output_mode=OutputMode.COMBINED,
        )
        db_session.add(session)
        db_session.commit()
        db_session.refresh(session)

        job = Job(
            name="Test Job",
            session_id="2026-05-24-002",
            session_fk=session.id,
            source_path="/fake/path.pdf",
            status=JobStatus.DRAFT,
        )
        db_session.add(job)
        db_session.commit()

        db_session.refresh(session)
        assert len(session.jobs) == 1
        assert session.jobs[0].name == "Test Job"
        assert job.session.name == "Relationship Test"


class TestSessionSchemas:
    def test_session_create_defaults(self):
        data = SessionCreate(name="Test Session", session_id="2026-05-24-001")
        assert data.output_mode == OutputMode.COMBINED
        assert data.date == date.today()

    def test_session_create_explicit(self):
        data = SessionCreate(
            name="Test",
            session_id="2026-05-24-002",
            date=date(2026, 5, 24),
            output_mode=OutputMode.SEPARATE,
        )
        assert data.output_mode == OutputMode.SEPARATE
        assert data.date == date(2026, 5, 24)

    def test_session_response_from_model(self, db_session):
        session = Session(
            name="Schema Test",
            session_id="2026-05-24-003",
            date=date(2026, 5, 24),
            output_mode=OutputMode.COMBINED,
        )
        db_session.add(session)
        db_session.commit()
        db_session.refresh(session)

        resp = SessionResponse.model_validate(session)
        assert resp.id == session.id
        assert resp.name == "Schema Test"
        assert resp.session_id == "2026-05-24-003"
        assert resp.output_mode == OutputMode.COMBINED
        assert resp.compiled_output_path is None


class TestCompileSession:
    def _make_preset(self, db_session):
        preset = Preset(
            name="compile-test",
            sheets_per_doc=1,
            embed_config={
                "barcode": {
                    "anchor": "bottom-right", "x_offset_pt": 36, "y_offset_pt": 36,
                    "module_size_mm": 0.50, "quiet_zone_mm": 6.5, "dpi": 600,
                },
                "human_readable": {"enabled": False},
            },
        )
        db_session.add(preset)
        db_session.commit()
        db_session.refresh(preset)
        return preset

    def _make_completed_job(self, db_session, session, preset, source_path, tmp_dir, job_name, doc_count):
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        job = Job(
            name=job_name,
            session_id=session.session_id,
            session_fk=session.id,
            source_path=str(source_path),
            preset_id=preset.id,
            status=JobStatus.COMPLETE,
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)

        output_dir = tmp_dir / f"output_{job.id}"
        machine_dir = output_dir / "machine_ready"
        machine_dir.mkdir(parents=True)

        for i in range(doc_count):
            pdf_path = machine_dir / f"doc_{i:06d}.pdf"
            c = canvas.Canvas(str(pdf_path), pagesize=letter)
            for p in range(2):
                c.drawString(72, 700, f"Job {job_name} Doc {i} Page {p}")
                c.showPage()
            c.save()

        report_data = {
            "job": job_name,
            "session_id": session.session_id,
            "date": "2026-05-24",
            "status": "OK",
            "totals": {
                "documents_processed": doc_count,
                "total_sheets": doc_count,
                "total_barcodes": doc_count,
                "inserts_triggered": 0,
                "diverts_triggered": 0,
                "overflow_documents": 0,
            },
        }
        report_path = output_dir / "report.json"
        report_path.write_text(json.dumps(report_data))

        result = JobResult(
            job_id=job.id,
            total_barcodes=doc_count,
            total_documents=doc_count,
            total_sheets=doc_count,
            overflow_docs=0,
            diverts_triggered=0,
            insert_count=0,
            report_path=str(report_path),
            output_dir=str(output_dir),
        )
        db_session.add(result)
        db_session.commit()
        return job

    def test_compile_merges_all_job_outputs(self, db_session, tmp_dir):
        from pypdf import PdfReader

        session = Session(
            name="Compile Test",
            session_id="2026-05-24-010",
            date=date(2026, 5, 24),
            output_mode=OutputMode.COMBINED,
        )
        db_session.add(session)
        db_session.commit()
        db_session.refresh(session)

        preset = self._make_preset(db_session)

        self._make_completed_job(db_session, session, preset, "/fake/a.pdf", tmp_dir, "Job-A", 3)
        self._make_completed_job(db_session, session, preset, "/fake/b.pdf", tmp_dir, "Job-B", 2)

        result = compile_session(db_session, session, base_output_dir=str(tmp_dir))

        assert result["status"] == "ok"
        assert result["total_documents"] == 5
        assert result["compiled_path"] is not None

        compiled_pdf = PdfReader(result["compiled_path"])
        assert len(compiled_pdf.pages) == 12  # 5 docs × 2 pages + cover + end

        db_session.refresh(session)
        assert session.compiled_output_path == result["compiled_path"]

    def test_compile_no_completed_jobs_raises(self, db_session, tmp_dir):
        session = Session(
            name="Empty Test",
            session_id="2026-05-24-011",
            date=date(2026, 5, 24),
            output_mode=OutputMode.COMBINED,
        )
        db_session.add(session)
        db_session.commit()
        db_session.refresh(session)

        try:
            compile_session(db_session, session, base_output_dir=str(tmp_dir))
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "No completed jobs" in str(e)

    def test_compile_skips_errored_jobs(self, db_session, tmp_dir):
        from pypdf import PdfReader

        session = Session(
            name="Partial Test",
            session_id="2026-05-24-012",
            date=date(2026, 5, 24),
            output_mode=OutputMode.COMBINED,
        )
        db_session.add(session)
        db_session.commit()
        db_session.refresh(session)

        preset = self._make_preset(db_session)
        self._make_completed_job(db_session, session, preset, "/fake/good.pdf", tmp_dir, "Good-Job", 4)

        errored = Job(
            name="Bad-Job",
            session_id=session.session_id,
            session_fk=session.id,
            source_path="/fake/bad.pdf",
            preset_id=preset.id,
            status=JobStatus.ERROR,
        )
        db_session.add(errored)
        db_session.commit()

        result = compile_session(db_session, session, base_output_dir=str(tmp_dir))

        assert result["status"] == "partial"
        assert result["total_documents"] == 4
        assert result["skipped_jobs"] == 1

        compiled_pdf = PdfReader(result["compiled_path"])
        assert len(compiled_pdf.pages) == 10  # 4 docs × 2 pages + cover + end
