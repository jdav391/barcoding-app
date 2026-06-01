from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader

from app.services.pdf_writer import embed_barcode_on_page, merge_pdfs, process_document


def _make_barcode_image(size=100):
    return Image.new("RGB", (size, size), "black")


class TestEmbedBarcodeOnPage:
    def test_produces_valid_pdf(self, sample_duplex_pdf, tmp_dir):
        output = tmp_dir / "embedded.pdf"
        embed_config = {
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
        embed_barcode_on_page(
            pdf_path=sample_duplex_pdf,
            page_index=0,
            barcode_image=_make_barcode_image(),
            barcode_text="0307158404144",
            embed_config=embed_config,
            output_path=output,
        )
        reader = PdfReader(str(output))
        assert len(reader.pages) == 1

    def test_with_human_readable(self, sample_duplex_pdf, tmp_dir):
        output = tmp_dir / "embedded_hr.pdf"
        embed_config = {
            "barcode": {
                "anchor": "bottom-right",
                "x_offset_pt": 36,
                "y_offset_pt": 36,
                "module_size_mm": 0.50,
                "quiet_zone_mm": 6.5,
                "dpi": 600,
            },
            "human_readable": {
                "enabled": True,
                "anchor": "bottom-left",
                "x_offset_pt": 36,
                "y_offset_pt": 36,
                "rotation": 90,
                "font_name": "Courier",
                "font_size": 8,
            },
        }
        embed_barcode_on_page(
            pdf_path=sample_duplex_pdf,
            page_index=0,
            barcode_image=_make_barcode_image(),
            barcode_text="0307158404144",
            embed_config=embed_config,
            output_path=output,
        )
        assert output.exists()

    def test_output_is_single_page_from_middle(self, sample_duplex_pdf, tmp_dir):
        """Extracting a non-first page still produces a single-page PDF."""
        output = tmp_dir / "embedded_mid.pdf"
        embed_config = {
            "barcode": {
                "anchor": "bottom-left",
                "x_offset_pt": 36,
                "y_offset_pt": 36,
                "module_size_mm": 0.50,
                "quiet_zone_mm": 6.5,
                "dpi": 600,
            },
            "human_readable": {"enabled": False},
        }
        embed_barcode_on_page(
            pdf_path=sample_duplex_pdf,
            page_index=10,
            barcode_image=_make_barcode_image(50),
            barcode_text="0307158404144",
            embed_config=embed_config,
            output_path=output,
        )
        reader = PdfReader(str(output))
        assert len(reader.pages) == 1

    def test_all_anchor_positions(self, sample_duplex_pdf, tmp_dir):
        """All four anchor variants produce valid single-page PDFs."""
        for anchor in ("bottom-right", "bottom-left", "top-right", "top-left"):
            output = tmp_dir / f"embedded_{anchor}.pdf"
            embed_config = {
                "barcode": {
                    "anchor": anchor,
                    "x_offset_pt": 36,
                    "y_offset_pt": 36,
                    "module_size_mm": 0.50,
                    "quiet_zone_mm": 6.5,
                    "dpi": 600,
                },
                "human_readable": {"enabled": False},
            }
            embed_barcode_on_page(
                pdf_path=sample_duplex_pdf,
                page_index=0,
                barcode_image=_make_barcode_image(),
                barcode_text="0307158404144",
                embed_config=embed_config,
                output_path=output,
            )
            reader = PdfReader(str(output))
            assert len(reader.pages) == 1, f"anchor={anchor} did not produce 1 page"

    def test_human_readable_all_anchors(self, sample_duplex_pdf, tmp_dir):
        """Human-readable text renders without error for all anchor positions."""
        for anchor in ("bottom-right", "bottom-left", "top-right", "top-left"):
            output = tmp_dir / f"hr_{anchor}.pdf"
            embed_config = {
                "barcode": {
                    "anchor": "bottom-right",
                    "x_offset_pt": 36,
                    "y_offset_pt": 36,
                    "module_size_mm": 0.50,
                    "quiet_zone_mm": 6.5,
                    "dpi": 600,
                },
                "human_readable": {
                    "enabled": True,
                    "anchor": anchor,
                    "x_offset_pt": 36,
                    "y_offset_pt": 36,
                    "rotation": 90,
                    "font_name": "Courier",
                    "font_size": 8,
                },
            }
            embed_barcode_on_page(
                pdf_path=sample_duplex_pdf,
                page_index=0,
                barcode_image=_make_barcode_image(),
                barcode_text="0307158404144",
                embed_config=embed_config,
                output_path=output,
            )
            assert output.exists(), f"human_readable anchor={anchor} failed"


class TestProcessDocument:
    def test_extracts_page_range_and_embeds(self, sample_duplex_pdf, tmp_dir):
        output = tmp_dir / "doc_set_1.pdf"
        embed_config = {
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
        barcodes = {0: (_make_barcode_image(), "1101000000001")}
        process_document(
            input_path=sample_duplex_pdf,
            page_range=(0, 1),
            side_a_barcodes=barcodes,
            embed_config=embed_config,
            output_path=output,
        )
        reader = PdfReader(str(output))
        assert len(reader.pages) == 2

    def test_multipage_range(self, sample_multisheet_pdf, tmp_dir):
        """Extract a 6-page range (3 sheets duplex) and embed barcodes on 3 side-A pages."""
        output = tmp_dir / "multisheet_doc.pdf"
        embed_config = {
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
        # Pages 0-5: side-A pages are 0, 2, 4
        barcodes = {
            0: (_make_barcode_image(), "1101000000001"),
            2: (_make_barcode_image(), "1201000000001"),
            4: (_make_barcode_image(), "1301000000001"),
        }
        process_document(
            input_path=sample_multisheet_pdf,
            page_range=(0, 5),
            side_a_barcodes=barcodes,
            embed_config=embed_config,
            output_path=output,
        )
        reader = PdfReader(str(output))
        assert len(reader.pages) == 6

    def test_no_barcodes(self, sample_duplex_pdf, tmp_dir):
        """process_document with empty side_a_barcodes still produces correct page count."""
        output = tmp_dir / "no_barcodes.pdf"
        embed_config = {
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
        process_document(
            input_path=sample_duplex_pdf,
            page_range=(4, 7),
            side_a_barcodes={},
            embed_config=embed_config,
            output_path=output,
        )
        reader = PdfReader(str(output))
        assert len(reader.pages) == 4

    def test_single_page_range(self, sample_simplex_pdf, tmp_dir):
        """A range of (n, n) produces exactly 1 page."""
        output = tmp_dir / "single_page.pdf"
        embed_config = {
            "barcode": {
                "anchor": "top-left",
                "x_offset_pt": 36,
                "y_offset_pt": 36,
                "module_size_mm": 0.50,
                "quiet_zone_mm": 6.5,
                "dpi": 600,
            },
            "human_readable": {"enabled": False},
        }
        barcodes = {5: (_make_barcode_image(), "1101000000005")}
        process_document(
            input_path=sample_simplex_pdf,
            page_range=(5, 5),
            side_a_barcodes=barcodes,
            embed_config=embed_config,
            output_path=output,
        )
        reader = PdfReader(str(output))
        assert len(reader.pages) == 1


class TestMergePdfs:
    def test_merges_multiple_pdfs(self, sample_duplex_pdf, sample_simplex_pdf, tmp_dir):
        output = tmp_dir / "merged.pdf"
        merge_pdfs([sample_duplex_pdf, sample_simplex_pdf], output)
        reader = PdfReader(str(output))
        assert len(reader.pages) == 30

    def test_merge_single_pdf(self, sample_duplex_pdf, tmp_dir):
        """Merging a single PDF returns a copy with the same page count."""
        output = tmp_dir / "single_merge.pdf"
        merge_pdfs([sample_duplex_pdf], output)
        reader = PdfReader(str(output))
        assert len(reader.pages) == 20

    def test_merge_three_pdfs(self, sample_duplex_pdf, sample_simplex_pdf, sample_multisheet_pdf, tmp_dir):
        """Merging three PDFs returns total pages of all three."""
        output = tmp_dir / "three_merge.pdf"
        merge_pdfs([sample_duplex_pdf, sample_simplex_pdf, sample_multisheet_pdf], output)
        reader = PdfReader(str(output))
        assert len(reader.pages) == 54  # 20 + 10 + 24

    def test_merge_creates_file(self, sample_simplex_pdf, tmp_dir):
        """Output path is created even if it doesn't exist yet."""
        output = tmp_dir / "subdir" / "merged.pdf"
        output.parent.mkdir(parents=True, exist_ok=True)
        merge_pdfs([sample_simplex_pdf], output)
        assert output.exists()
