"""Phase 2 tests — vector barcode rendering, page-geometry handling,
manifest generation, and streaming-friendly readers."""
import csv
import json
from pathlib import Path

import pdfplumber
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject
from reportlab.lib.pagesizes import A4, letter
from reportlab.pdfgen import canvas as pdf_canvas

from app.enums import FeedDirection, IdSource, ImportMethod, JobMode, JobStatus, PageFormat
from app.models import BatchImport, Job, MailPiece, Preset
from app.services.barcode import DM_MODULES, dmtx_module_matrix
from app.services.job import run_job
from app.services.pdf_writer import barcode_footprint_pt, embed_barcode_on_page

BARCODE = "0307158404144"

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


def _make_preset(db, name, **kwargs):
    preset = Preset(
        name=name,
        sheets_per_doc=1,
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


def _make_job(db, source_path, preset, name, session_id="P2-001"):
    job = Job(
        name=name,
        session_id=session_id,
        source_path=str(source_path),
        preset_id=preset.id,
        mode=JobMode.PRESET,
        status=JobStatus.DRAFT,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


# ---------------------------------------------------------------------------
# Data Matrix module matrix
# ---------------------------------------------------------------------------

class TestModuleMatrix:
    def test_dimensions(self):
        m = dmtx_module_matrix(BARCODE)
        assert len(m) == DM_MODULES
        assert all(len(row) == DM_MODULES for row in m)

    def test_finder_pattern(self):
        m = dmtx_module_matrix(BARCODE)
        assert all(row[0] for row in m), "left column must be solid dark"
        assert all(m[-1]), "bottom row must be solid dark"
        # Top row and right column are alternating timing patterns
        assert m[0][0] and not m[0][1]

    def test_matrix_decodes_back_to_payload(self):
        """Re-rasterize the sampled matrix and decode it with libdmtx."""
        from PIL import Image
        from pylibdmtx.pylibdmtx import decode

        m = dmtx_module_matrix(BARCODE)
        px = 8
        margin = 40
        size = DM_MODULES * px + 2 * margin
        img = Image.new("L", (size, size), 255)
        for r, row in enumerate(m):
            for c, dark in enumerate(row):
                if dark:
                    for dy in range(px):
                        for dx in range(px):
                            img.putpixel((margin + c * px + dx, margin + r * px + dy), 0)

        results = decode(img.convert("RGB"))
        assert results, "vector module matrix did not decode"
        assert results[0].data == BARCODE.encode("ascii")


# ---------------------------------------------------------------------------
# Vector rendering on the page
# ---------------------------------------------------------------------------

class TestVectorRendering:
    def test_stamped_page_contains_vector_rects(self, sample_duplex_pdf, tmp_dir):
        output = tmp_dir / "vector.pdf"
        embed_barcode_on_page(
            pdf_path=sample_duplex_pdf,
            page_index=0,
            barcode_text=BARCODE,
            embed_config=EMBED_CONFIG,
            output_path=output,
        )

        dark_modules = sum(sum(row) for row in dmtx_module_matrix(BARCODE))
        with pdfplumber.open(output) as pdf:
            rects = pdf.pages[0].rects
        # One white quiet-zone rect + one filled rect per dark module
        assert len(rects) == dark_modules + 1

    def test_no_temp_raster_or_images_embedded(self, sample_duplex_pdf, tmp_dir):
        """Vector output must not contain raster images for the barcode."""
        output = tmp_dir / "vector_noimg.pdf"
        embed_barcode_on_page(
            pdf_path=sample_duplex_pdf,
            page_index=0,
            barcode_text=BARCODE,
            embed_config=EMBED_CONFIG,
            output_path=output,
        )
        with pdfplumber.open(output) as pdf:
            assert pdf.pages[0].images == []

    def test_footprint_position_bottom_right(self, sample_duplex_pdf, tmp_dir):
        output = tmp_dir / "vector_pos.pdf"
        embed_barcode_on_page(
            pdf_path=sample_duplex_pdf,
            page_index=0,
            barcode_text=BARCODE,
            embed_config=EMBED_CONFIG,
            output_path=output,
        )
        footprint = barcode_footprint_pt(EMBED_CONFIG["barcode"])
        page_w = letter[0]
        expected_x0 = page_w - 36 - footprint

        with pdfplumber.open(output) as pdf:
            rects = pdf.pages[0].rects
        bg = min(rects, key=lambda r: r["x0"])  # quiet zone is the largest/leftmost
        assert bg["x0"] == pytest.approx(expected_x0, abs=0.5)
        assert bg["width"] == pytest.approx(footprint, abs=0.5)


# ---------------------------------------------------------------------------
# Page-geometry guards
# ---------------------------------------------------------------------------

class TestPageGeometry:
    def _rotated_pdf(self, tmp_dir):
        src = tmp_dir / "src.pdf"
        c = pdf_canvas.Canvas(str(src), pagesize=letter)
        c.drawString(72, 700, "Rotated source")
        c.showPage()
        c.save()

        rotated = tmp_dir / "rotated.pdf"
        reader = PdfReader(str(src))
        writer = PdfWriter()
        page = reader.pages[0]
        page.rotate(90)
        writer.add_page(page)
        with open(rotated, "wb") as f:
            writer.write(f)
        return rotated

    def test_rotated_page_is_normalized_and_stamped(self, tmp_dir):
        rotated = self._rotated_pdf(tmp_dir)
        output = tmp_dir / "rotated_stamped.pdf"
        embed_barcode_on_page(
            pdf_path=rotated,
            page_index=0,
            barcode_text=BARCODE,
            embed_config=EMBED_CONFIG,
            output_path=output,
        )

        out_page = PdfReader(str(output)).pages[0]
        assert out_page.rotation == 0, "rotation must be baked into content"
        # Printed page is landscape after the 90° rotation
        assert float(out_page.mediabox.width) == pytest.approx(letter[1], abs=1)

        footprint = barcode_footprint_pt(EMBED_CONFIG["barcode"])
        expected_x0 = letter[1] - 36 - footprint
        with pdfplumber.open(output) as pdf:
            rects = pdf.pages[0].rects
        assert rects, "barcode rects missing on rotated page"
        bg = min(rects, key=lambda r: r["x0"])
        assert bg["x0"] == pytest.approx(expected_x0, abs=1.0)

    def test_nonzero_mediabox_origin_offsets_overlay(self, tmp_dir):
        src = tmp_dir / "src.pdf"
        c = pdf_canvas.Canvas(str(src), pagesize=letter)
        c.drawString(72, 700, "Shifted mediabox")
        c.showPage()
        c.save()

        shifted = tmp_dir / "shifted.pdf"
        reader = PdfReader(str(src))
        writer = PdfWriter()
        page = reader.pages[0]
        page.mediabox = RectangleObject((100, 50, 100 + letter[0], 50 + letter[1]))
        writer.add_page(page)
        with open(shifted, "wb") as f:
            writer.write(f)

        output = tmp_dir / "shifted_stamped.pdf"
        embed_barcode_on_page(
            pdf_path=shifted,
            page_index=0,
            barcode_text=BARCODE,
            embed_config=EMBED_CONFIG,
            output_path=output,
        )

        footprint = barcode_footprint_pt(EMBED_CONFIG["barcode"])
        # Anchored to the page's actual right edge (mediabox right = 100 + 612)
        expected_x0 = (100 + letter[0]) - 36 - footprint
        with pdfplumber.open(output) as pdf:
            rects = pdf.pages[0].rects
        assert rects, "barcode rects missing on shifted-origin page"
        bg = min(rects, key=lambda r: r["x0"])
        assert bg["x0"] == pytest.approx(expected_x0, abs=1.0)

    def test_mixed_page_sizes_warn_in_report(self, db_session, tmp_dir):
        path = tmp_dir / "mixed_sizes.pdf"
        c = pdf_canvas.Canvas(str(path), pagesize=letter)
        c.drawString(72, 700, "Letter doc")
        c.showPage()
        c.showPage()
        c.setPageSize(A4)
        c.drawString(72, 700, "A4 doc")
        c.showPage()
        c.showPage()
        c.save()

        preset = _make_preset(db_session, "mixed-sizes")
        job = _make_job(db_session, path, preset, "mixed-sizes")
        result = run_job(db_session, job)

        report = json.loads(Path(result.report_path).read_text())
        assert any("Mixed page sizes" in w for w in report["warnings"])


# ---------------------------------------------------------------------------
# Mail run data manifest
# ---------------------------------------------------------------------------

class TestManifest:
    def test_manifest_written_with_piece_rows(self, db_session, sample_duplex_pdf):
        preset = _make_preset(db_session, "manifest")
        job = _make_job(db_session, sample_duplex_pdf, preset, "manifest")
        db_session.add(BatchImport(
            job_id=job.id, batch_id="B1",
            expected_letters=10, expected_sheets=10,
            import_method=ImportMethod.MANUAL,
        ))
        db_session.commit()

        result = run_job(db_session, job)

        manifest = Path(result.output_dir) / "mail_run_data.csv"
        assert manifest.exists()

        with open(manifest, newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 10

        pieces = (
            db_session.query(MailPiece)
            .filter_by(job_id=job.id)
            .order_by(MailPiece.doc_index)
            .all()
        )
        for row, piece in zip(rows, pieces):
            assert int(row["piece"]) == piece.doc_index + 1
            assert row["unique_id"] == f"{piece.unique_id:09d}"
            assert int(row["sheets"]) == piece.sheet_count
            assert row["barcodes"] == ";".join(piece.barcodes)
            assert row["output_file"] == Path(piece.output_path).name

    def test_manifest_covers_resumed_runs(self, db_session, sample_duplex_pdf):
        preset = _make_preset(db_session, "manifest-resume")
        job = _make_job(db_session, sample_duplex_pdf, preset, "manifest-resume")
        run_job(db_session, job)

        job.last_processed_index = 4
        job.status = JobStatus.PARTIAL
        job.completed_at = None
        db_session.commit()
        result = run_job(db_session, job)

        manifest = Path(result.output_dir) / "mail_run_data.csv"
        with open(manifest, newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 10
        assert [int(r["piece"]) for r in rows] == list(range(1, 11))
