from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from app.enums import PageFormat


@dataclass
class DocSet:
    index: int
    start_page: int       # 0-indexed
    end_page: int         # 0-indexed, inclusive
    sheet_count: int
    side_a_pages: list[int]  # 0-indexed page indices


@dataclass
class ValidationResult:
    valid: bool
    total_pages: int = 0
    doc_sets: int = 0
    pages_per_set: int = 0
    error: str | None = None


def _pages_per_set(sheets_per_doc: int, page_format: PageFormat) -> int:
    """Return the number of PDF pages that make up one document set."""
    if page_format == PageFormat.DUPLEX:
        return sheets_per_doc * 2
    else:  # SIMPLEX
        return sheets_per_doc * 1


def validate_page_count(
    pdf_path: Path | str,
    sheets_per_doc: int,
    page_format: PageFormat,
) -> ValidationResult:
    """Check whether the PDF page count divides evenly into document sets.

    Returns a ValidationResult with valid=True when the total page count is an
    exact multiple of the computed pages-per-set value.
    """
    reader = PdfReader(str(pdf_path))
    total_pages = len(reader.pages)
    pps = _pages_per_set(sheets_per_doc, page_format)

    if total_pages % pps != 0:
        return ValidationResult(
            valid=False,
            total_pages=total_pages,
            pages_per_set=pps,
            error=(
                f"PDF has {total_pages} pages, which is not evenly divisible "
                f"by {pps} pages per set ({sheets_per_doc} sheet(s), {page_format.value})"
            ),
        )

    num_sets = total_pages // pps
    return ValidationResult(
        valid=True,
        total_pages=total_pages,
        doc_sets=num_sets,
        pages_per_set=pps,
    )


def split_by_preset(
    pdf_path: Path | str,
    sheets_per_doc: int,
    page_format: PageFormat,
) -> list[DocSet]:
    """Split a PDF into DocSet objects according to the given preset.

    Raises ValueError if the page count does not divide evenly.
    """
    validation = validate_page_count(pdf_path, sheets_per_doc, page_format)
    if not validation.valid:
        raise ValueError(validation.error)

    pps = validation.pages_per_set
    doc_sets: list[DocSet] = []

    for i in range(validation.doc_sets):
        start = i * pps
        end = start + pps - 1  # inclusive

        if page_format == PageFormat.DUPLEX:
            # Side-A pages are even-indexed within the set (0-indexed globally)
            side_a_pages = [start + (sheet * 2) for sheet in range(sheets_per_doc)]
        else:  # SIMPLEX — every page is a side-A page
            side_a_pages = list(range(start, end + 1))

        doc_sets.append(
            DocSet(
                index=i,
                start_page=start,
                end_page=end,
                sheet_count=sheets_per_doc,
                side_a_pages=side_a_pages,
            )
        )

    return doc_sets
