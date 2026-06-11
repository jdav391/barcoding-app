"""PDF writer service — barcode embedding, page extraction, and PDF merging.

Barcodes are drawn as vector rectangles (white quiet zone + black modules)
directly into the overlay PDF. Vector output guarantees crisp module edges at
any RIP resolution and removes the raster/DPI coupling entirely: the printed
module size is exactly module_size_mm regardless of the print pipeline.
"""
from __future__ import annotations

import io
from pathlib import Path

from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.pdfgen import canvas as rl_canvas

from app.services.barcode import DM_MODULES, dmtx_module_matrix

MM_TO_PT = 72.0 / 25.4


def barcode_footprint_pt(barcode_config: dict) -> float:
    """Edge length in points of the stamped square (symbol + quiet zone)."""
    module_size_mm: float = barcode_config.get("module_size_mm", 0.50)
    quiet_zone_mm: float = barcode_config.get("quiet_zone_mm", 6.5)
    return (DM_MODULES * module_size_mm + 2 * quiet_zone_mm) * MM_TO_PT


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


def _draw_barcode_vector(
    c: rl_canvas.Canvas,
    barcode_text: str,
    x: float,
    y: float,
    barcode_cfg: dict,
) -> None:
    """Draw quiet zone + Data Matrix modules as filled vector rects at (x, y)."""
    module_pt = barcode_cfg.get("module_size_mm", 0.50) * MM_TO_PT
    quiet_pt = barcode_cfg.get("quiet_zone_mm", 6.5) * MM_TO_PT
    footprint = DM_MODULES * module_pt + 2 * quiet_pt

    matrix = dmtx_module_matrix(barcode_text)

    c.saveState()
    # Quiet zone: opaque white so underlying content cannot reduce contrast
    c.setFillColorRGB(1, 1, 1)
    c.rect(x, y, footprint, footprint, fill=1, stroke=0)

    c.setFillColorRGB(0, 0, 0)
    sym_x = x + quiet_pt
    sym_y = y + quiet_pt
    for row, cells in enumerate(matrix):
        # matrix row 0 is the top of the symbol; PDF y grows upward
        cell_y = sym_y + (DM_MODULES - 1 - row) * module_pt
        for col, dark in enumerate(cells):
            if dark:
                c.rect(sym_x + col * module_pt, cell_y, module_pt, module_pt,
                       fill=1, stroke=0)
    c.restoreState()


def _build_overlay(
    page_width_pt: float,
    page_height_pt: float,
    barcode_text: str,
    embed_config: dict,
) -> bytes:
    """Create an in-memory overlay PDF with the barcode (and optional text)."""
    barcode_cfg: dict = embed_config["barcode"]
    hr_cfg: dict = embed_config.get("human_readable", {})

    footprint = barcode_footprint_pt(barcode_cfg)

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(page_width_pt, page_height_pt))

    x_img, y_img = _anchor_xy(
        anchor=barcode_cfg["anchor"],
        x_offset_pt=barcode_cfg.get("x_offset_pt", 0),
        y_offset_pt=barcode_cfg.get("y_offset_pt", 0),
        img_width_pt=footprint,
        img_height_pt=footprint,
        page_width_pt=page_width_pt,
        page_height_pt=page_height_pt,
    )
    _draw_barcode_vector(c, barcode_text, x_img, y_img, barcode_cfg)

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


def _stamp_page(writer: PdfWriter, embed_config: dict, barcode_text: str) -> None:
    """Overlay a barcode onto the last page added to *writer*.

    Handles two real-world print-stream quirks:
    - /Rotate: rotation is baked into the content first so the barcode lands
      at the intended physical position on the printed sheet.
    - MediaBox origin: overlays are built in a (0,0)-origin space and shifted
      to the page's actual lower-left corner.
    """
    page = writer.pages[-1]

    if page.rotation:
        page.transfer_rotation_to_content()

    box = page.mediabox
    page_w = float(box.width)
    page_h = float(box.height)
    origin_x = float(box.left)
    origin_y = float(box.bottom)

    overlay_bytes = _build_overlay(page_w, page_h, barcode_text, embed_config)
    overlay_page = PdfReader(io.BytesIO(overlay_bytes)).pages[0]

    if origin_x or origin_y:
        page.merge_transformed_page(
            overlay_page, Transformation().translate(origin_x, origin_y)
        )
    else:
        page.merge_page(overlay_page)


def _as_reader(source: Path | str | PdfReader) -> PdfReader:
    """Accept a path or an already-open PdfReader (one parse per job)."""
    if isinstance(source, PdfReader):
        return source
    return PdfReader(str(source))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def embed_barcode_on_page(
    pdf_path: Path | str | PdfReader,
    page_index: int,
    barcode_text: str,
    embed_config: dict,
    output_path: Path | str,
) -> None:
    """Extract one page from *pdf_path* at *page_index*, overlay a barcode, write to *output_path*.

    Args:
        pdf_path: Source PDF path or an open PdfReader.
        page_index: 0-indexed page to extract.
        barcode_text: Barcode payload string (also rendered as human-readable
            text when human_readable.enabled is True).
        embed_config: Positioning/appearance config dict.
        output_path: Destination file path for the single-page output PDF.
    """
    reader = _as_reader(pdf_path)

    writer = PdfWriter()
    writer.add_page(reader.pages[page_index])
    _stamp_page(writer, embed_config, barcode_text)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        writer.write(f)


def process_document(
    input_path: Path | str | PdfReader,
    page_range: tuple[int, int],
    side_a_barcodes: dict[int, str],
    embed_config: dict,
    output_path: Path | str,
) -> None:
    """Extract a range of pages from *input_path*, embed barcodes on specified pages, write to *output_path*.

    Args:
        input_path: Source PDF path or an open PdfReader (pass a shared reader
            when processing many doc sets from one file).
        page_range: ``(start, end)`` — both are inclusive, 0-indexed.
        side_a_barcodes: Mapping of {global_page_index: barcode_string}.
            Only pages whose global index appears in this dict get a barcode overlay.
        embed_config: Positioning/appearance config dict.
        output_path: Destination file path for the multi-page output PDF.
    """
    reader = _as_reader(input_path)
    start, end = page_range
    writer = PdfWriter()

    for global_idx in range(start, end + 1):
        writer.add_page(reader.pages[global_idx])
        if global_idx in side_a_barcodes:
            _stamp_page(writer, embed_config, side_a_barcodes[global_idx])

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
        writer.append(str(path))

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        writer.write(f)
