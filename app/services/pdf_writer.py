"""PDF writer service — barcode embedding, page extraction, and PDF merging."""
from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas as rl_canvas

if TYPE_CHECKING:
    pass


def _compute_image_size_pt(barcode_image: Image.Image, config: dict) -> tuple[float, float]:
    """Return (width_pt, height_pt) for the barcode image based on embed config.

    The config carries dpi so we can convert pixel dimensions to physical units.
    """
    dpi: float = config.get("dpi", 600)
    px_w, px_h = barcode_image.size
    # pixels / dpi → inches → * 72 → points
    width_pt = (px_w / dpi) * 72.0
    height_pt = (px_h / dpi) * 72.0
    return width_pt, height_pt


def _anchor_xy(
    anchor: str,
    x_offset_pt: float,
    y_offset_pt: float,
    img_width_pt: float,
    img_height_pt: float,
    page_width_pt: float,
    page_height_pt: float,
) -> tuple[float, float]:
    """Return (x, y) origin (bottom-left of image) in PDF coordinate space."""
    if anchor == "bottom-right":
        x = page_width_pt - x_offset_pt - img_width_pt
        y = y_offset_pt
    elif anchor == "bottom-left":
        x = x_offset_pt
        y = y_offset_pt
    elif anchor == "top-right":
        x = page_width_pt - x_offset_pt - img_width_pt
        y = page_height_pt - y_offset_pt - img_height_pt
    elif anchor == "top-left":
        x = x_offset_pt
        y = page_height_pt - y_offset_pt - img_height_pt
    else:
        raise ValueError(f"Unknown anchor: {anchor!r}")
    return x, y


def _build_overlay(
    page_width_pt: float,
    page_height_pt: float,
    barcode_image: Image.Image,
    barcode_text: str,
    embed_config: dict,
) -> bytes:
    """Create an in-memory overlay PDF with the barcode (and optional text)."""
    barcode_cfg: dict = embed_config["barcode"]
    hr_cfg: dict = embed_config.get("human_readable", {})

    img_w_pt, img_h_pt = _compute_image_size_pt(barcode_image, barcode_cfg)

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(page_width_pt, page_height_pt))

    # --- barcode image ---
    x_img, y_img = _anchor_xy(
        anchor=barcode_cfg["anchor"],
        x_offset_pt=barcode_cfg.get("x_offset_pt", 0),
        y_offset_pt=barcode_cfg.get("y_offset_pt", 0),
        img_width_pt=img_w_pt,
        img_height_pt=img_h_pt,
        page_width_pt=page_width_pt,
        page_height_pt=page_height_pt,
    )

    # Save barcode image to a temp PNG so reportlab can drawImage from it
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img:
        tmp_img_path = tmp_img.name
        barcode_image.save(tmp_img_path, format="PNG")

    try:
        c.drawImage(tmp_img_path, x_img, y_img, width=img_w_pt, height=img_h_pt, mask="auto")
    finally:
        import os
        os.unlink(tmp_img_path)

    # --- human-readable text ---
    if hr_cfg.get("enabled", False):
        font_name: str = hr_cfg.get("font_name", "Courier")
        font_size: float = hr_cfg.get("font_size", 8)
        rotation: float = hr_cfg.get("rotation", 0)

        # For text sizing, treat it as a zero-height element for anchor calculation
        # (text origin is bottom-left of baseline)
        x_txt, y_txt = _anchor_xy(
            anchor=hr_cfg.get("anchor", "bottom-left"),
            x_offset_pt=hr_cfg.get("x_offset_pt", 0),
            y_offset_pt=hr_cfg.get("y_offset_pt", 0),
            img_width_pt=0,
            img_height_pt=0,
            page_width_pt=page_width_pt,
            page_height_pt=page_height_pt,
        )

        c.saveState()
        c.translate(x_txt, y_txt)
        c.rotate(rotation)
        c.setFont(font_name, font_size)
        c.drawString(0, 0, barcode_text)
        c.restoreState()

    c.save()
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def embed_barcode_on_page(
    pdf_path: Path | str,
    page_index: int,
    barcode_image: Image.Image,
    barcode_text: str,
    embed_config: dict,
    output_path: Path | str,
) -> None:
    """Extract one page from *pdf_path* at *page_index*, overlay a barcode, write to *output_path*.

    Args:
        pdf_path: Source PDF.
        page_index: 0-indexed page to extract.
        barcode_image: PIL Image of the barcode to embed.
        barcode_text: Human-readable barcode string (used when human_readable.enabled is True).
        embed_config: Positioning/appearance config dict.
        output_path: Destination file path for the single-page output PDF.
    """
    reader = PdfReader(str(pdf_path))
    source_page = reader.pages[page_index]

    # Page dimensions in points (pypdf stores as floats)
    page_w = float(source_page.mediabox.width)
    page_h = float(source_page.mediabox.height)

    overlay_bytes = _build_overlay(page_w, page_h, barcode_image, barcode_text, embed_config)

    overlay_reader = PdfReader(io.BytesIO(overlay_bytes))
    overlay_page = overlay_reader.pages[0]

    writer = PdfWriter()
    writer.add_page(source_page)
    writer.pages[-1].merge_page(overlay_page)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        writer.write(f)


def process_document(
    input_path: Path | str,
    page_range: tuple[int, int],
    side_a_barcodes: dict[int, tuple[Image.Image, str]],
    embed_config: dict,
    output_path: Path | str,
) -> None:
    """Extract a range of pages from *input_path*, embed barcodes on specified pages, write to *output_path*.

    Args:
        input_path: Source PDF.
        page_range: ``(start, end)`` — both are inclusive, 0-indexed.
        side_a_barcodes: Mapping of {global_page_index: (barcode_image, barcode_text)}.
            Only pages whose global index appears in this dict get a barcode overlay.
        embed_config: Positioning/appearance config dict.
        output_path: Destination file path for the multi-page output PDF.
    """
    reader = PdfReader(str(input_path))
    start, end = page_range
    writer = PdfWriter()

    for global_idx in range(start, end + 1):
        page = reader.pages[global_idx]

        writer.add_page(page)

        if global_idx in side_a_barcodes:
            barcode_image, barcode_text = side_a_barcodes[global_idx]

            page_w = float(page.mediabox.width)
            page_h = float(page.mediabox.height)

            overlay_bytes = _build_overlay(page_w, page_h, barcode_image, barcode_text, embed_config)
            overlay_reader = PdfReader(io.BytesIO(overlay_bytes))
            overlay_page = overlay_reader.pages[0]
            writer.pages[-1].merge_page(overlay_page)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        writer.write(f)


def merge_pdfs(pdf_paths: list[Path | str], output_path: Path | str) -> None:
    """Merge multiple PDFs into a single file.

    Args:
        pdf_paths: Ordered list of PDF paths to merge.
        output_path: Destination file path for the merged PDF.
    """
    writer = PdfWriter()

    for path in pdf_paths:
        reader = PdfReader(str(path))
        for page in reader.pages:
            writer.add_page(page)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        writer.write(f)
