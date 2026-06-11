"""Clear-zone inspection — detect page content under the barcode footprint.

The barcode overlay (symbol + white quiet zone) is stamped on top of the page,
so anything underneath is obliterated in print and can also break the
inserter camera's read window. This module inspects the source pages before
stamping and reports text or images inside the barcode footprint.
"""
from __future__ import annotations

from pathlib import Path

import pdfplumber

from app.services.pdf_writer import _anchor_xy

# Symbol geometry must mirror barcode.generate_barcode_image (18x18 ECC200).
DM_MODULES = 18


def barcode_footprint_pt(barcode_config: dict) -> float:
    """Return the square footprint (symbol + quiet zone) edge length in points."""
    dpi: float = barcode_config.get("dpi", 600)
    module_size_mm: float = barcode_config.get("module_size_mm", 0.50)
    quiet_zone_mm: float = barcode_config.get("quiet_zone_mm", 6.5)

    pixels_per_mm = dpi / 25.4
    module_px = round(module_size_mm * pixels_per_mm)
    quiet_zone_px = round(quiet_zone_mm * pixels_per_mm)
    total_px = DM_MODULES * module_px + 2 * quiet_zone_px
    return (total_px / dpi) * 72.0


def find_clear_zone_violations(
    pdf_path: Path | str,
    page_indices: list[int],
    embed_config: dict,
) -> list[dict]:
    """Inspect pages for content inside the barcode footprint.

    Returns a list of {"page_index", "chars", "images"} dicts for pages where
    text characters or images fall inside the footprint. Vector strokes are
    not counted to avoid false positives from form borders and backgrounds.
    """
    barcode_cfg: dict = embed_config["barcode"]
    size_pt = barcode_footprint_pt(barcode_cfg)
    violations: list[dict] = []

    with pdfplumber.open(pdf_path) as pdf:
        for idx in sorted(set(page_indices)):
            page = pdf.pages[idx]
            x, y = _anchor_xy(
                anchor=barcode_cfg["anchor"],
                x_offset_pt=barcode_cfg.get("x_offset_pt", 0),
                y_offset_pt=barcode_cfg.get("y_offset_pt", 0),
                img_width_pt=size_pt,
                img_height_pt=size_pt,
                page_width_pt=page.width,
                page_height_pt=page.height,
            )
            # Convert PDF coords (origin bottom-left) to pdfplumber coords
            # (origin top-left), clamped to the page.
            x0 = max(x, 0)
            x1 = min(x + size_pt, page.width)
            top = max(page.height - (y + size_pt), 0)
            bottom = min(page.height - y, page.height)
            if x0 >= x1 or top >= bottom:
                continue

            region = page.crop((x0, top, x1, bottom))
            char_count = len(region.chars)
            image_count = len(region.images)
            if char_count or image_count:
                violations.append({
                    "page_index": idx,
                    "chars": char_count,
                    "images": image_count,
                })

            flush = getattr(page, "flush_cache", None)
            if flush:
                flush()

    return violations
