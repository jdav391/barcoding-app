from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

from app.enums import MatchType, PageFormat, RegionRole


@dataclass
class DetectedDoc:
    """A document set detected from region-based analysis of a PDF."""
    index: int
    start_page: int       # 0-indexed, inclusive
    end_page: int         # 0-indexed, inclusive
    sheet_count: int
    side_a_pages: list[int]   # 0-indexed page indices that get barcodes
    unique_id: int | None = None
    extracted_data: dict = field(default_factory=dict)


@dataclass
class PageExtraction:
    """Text extracted from regions on a single side-A page."""
    page_index: int              # 0-indexed
    regions_text: dict[int, str]  # region_id -> extracted text
    signature: tuple              # composite from GROUP_BOUNDARY regions


class RegionTextExtractor:
    """Extract text from defined regions on a PDF page using pdfplumber."""

    def extract_page_text(
        self,
        pdf_path: str | Path,
        page_index: int,           # 0-indexed
        regions: list,             # list of Region ORM objects
    ) -> dict[int, str]:
        """Return {region_id: extracted_text} for all regions on this page.

        In detection context, all regions apply to the current page being
        processed regardless of their ``page`` attribute. The template's
        ``page`` field is used when referencing the original template PDF,
        not during batch detection.
        """
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[page_index]
            page_h = page.height
            result = {}
            for r in regions:
                try:
                    rx, ry = float(r.x), float(r.y)
                    rw, rh = float(r.width), float(r.height)
                    pdf_bottom = min(ry, ry + rh)
                    pdf_top = max(ry, ry + rh)
                    y0 = page_h - pdf_top
                    y1 = page_h - pdf_bottom
                    cropped = page.crop((
                        rx, y0,
                        rx + abs(rw), y1,
                    ))
                    text = cropped.extract_text() if cropped else ""
                    result[r.id] = (text or "").strip()
                except Exception:
                    result[r.id] = ""
            return result


class TextMatcher:
    """Match extracted text against a pattern based on match type."""

    @staticmethod
    def match(match_type: MatchType, pattern: str | None, text: str) -> str | None:
        """
        Return the matched value, or None if no match.

        - EXACT: text must equal pattern (or if pattern is None, return text as-is)
        - REGEX: apply regex pattern, return first capture group or full match
        - NUMERIC: extract all consecutive digits from text
        """
        if not text:
            return None

        if match_type == MatchType.EXACT:
            if pattern is None:
                return text
            return text if text == pattern else None

        elif match_type == MatchType.REGEX:
            if pattern is None:
                return None
            m = re.search(pattern, text)
            if m is None:
                return None
            # Return first capture group if present, else full match
            try:
                return m.group(1) if m.lastindex else m.group(0)
            except (AttributeError, IndexError):
                return m.group(0)

        elif match_type == MatchType.NUMERIC:
            m = re.search(r'\d+', text)
            return m.group(0) if m else None

        return None


def detect_from_regions(
    pdf_path: str | Path,
    regions: list,             # list of Region ORM objects
    page_format: PageFormat,
) -> list[DetectedDoc]:
    """
    Walk side-A pages of a PDF, extract text from defined regions,
    and detect document boundaries by comparing GROUP_BOUNDARY signatures.

    Algorithm:
    1. Classify regions by role
    2. Determine side-A page indices (even-indexed for DUPLEX, all for SIMPLEX)
    3. Extract text from all regions on each side-A page
    4. Build a "signature" from GROUP_BOUNDARY region texts
    5. Walk pages; when signature changes -> new document boundary
    6. For each detected document, extract sheet_count and unique_id
    """
    # 1. Classify regions by role
    gb_regions = sorted(
        [r for r in regions if r.role == RegionRole.GROUP_BOUNDARY],
        key=lambda r: r.priority,
    )
    pc_regions = sorted(
        [r for r in regions if r.role == RegionRole.PAGE_COUNTER],
        key=lambda r: r.priority,
    )
    uid_regions = sorted(
        [r for r in regions if r.role == RegionRole.UNIQUE_ID],
        key=lambda r: r.priority,
    )

    # 2. Determine side-A pages and total
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)

    if total_pages == 0:
        return []

    if page_format == PageFormat.DUPLEX:
        side_a_indices = [i for i in range(total_pages) if i % 2 == 0]
    else:
        side_a_indices = list(range(total_pages))

    if not side_a_indices:
        return []

    # 3. Extract text from all regions on each side-A page
    extractor = RegionTextExtractor()
    page_extractions: list[PageExtraction] = []

    for page_idx in side_a_indices:
        region_texts = extractor.extract_page_text(pdf_path, page_idx, regions)

        # Build signature from GROUP_BOUNDARY regions
        sig_parts = []
        for r in gb_regions:
            text = region_texts.get(r.id, "")
            matched = TextMatcher.match(r.match_type, r.match_pattern, text)
            sig_parts.append(matched or "")
        signature = tuple(sig_parts)

        page_extractions.append(PageExtraction(
            page_index=page_idx,
            regions_text=region_texts,
            signature=signature,
        ))

    # 4. Detect document boundaries by signature changes
    detected_docs: list[DetectedDoc] = []
    doc_start_ext = page_extractions[0]
    doc_index = 0

    for i in range(1, len(page_extractions)):
        current = page_extractions[i]

        if current.signature != doc_start_ext.signature and any(current.signature):
            # Close the previous document (spans from doc_start_ext to page_extractions[i-1])
            doc = _build_doc(
                index=doc_index,
                start_ext=doc_start_ext,
                end_ext=page_extractions[i - 1],
                pc_regions=pc_regions,
                uid_regions=uid_regions,
                page_format=page_format,
            )
            detected_docs.append(doc)
            doc_index += 1
            doc_start_ext = current

    # Close the last document
    doc = _build_doc(
        index=doc_index,
        start_ext=doc_start_ext,
        end_ext=page_extractions[-1],
        pc_regions=pc_regions,
        uid_regions=uid_regions,
        page_format=page_format,
    )
    detected_docs.append(doc)

    return detected_docs


def _build_doc(
    index: int,
    start_ext: PageExtraction,
    end_ext: PageExtraction,
    pc_regions: list,
    uid_regions: list,
    page_format: PageFormat,
) -> DetectedDoc:
    """Build a DetectedDoc from start and end PageExtractions."""
    start_page = start_ext.page_index

    # For DUPLEX, the document includes the side-B page after each side-A page.
    # Therefore the last physical page is one more than the last side-A page index.
    if page_format == PageFormat.DUPLEX:
        end_page = end_ext.page_index + 1
    else:
        end_page = end_ext.page_index

    # Determine sheet_count
    sheet_count = _extract_sheet_count(start_ext, pc_regions, page_format, start_page, end_page)

    # Compute side-A pages
    if page_format == PageFormat.DUPLEX:
        side_a_pages = list(range(start_page, end_page + 1, 2))
    else:
        side_a_pages = list(range(start_page, end_page + 1))

    # Extract unique_id
    unique_id = _extract_unique_id(start_ext, uid_regions)

    return DetectedDoc(
        index=index,
        start_page=start_page,
        end_page=end_page,
        sheet_count=sheet_count,
        side_a_pages=side_a_pages,
        unique_id=unique_id,
        extracted_data={"start_page": start_page, "end_page": end_page},
    )


def _extract_sheet_count(
    start_ext: PageExtraction,
    pc_regions: list,
    page_format: PageFormat,
    start_page: int,
    end_page: int,
) -> int:
    """Extract sheet count from PAGE_COUNTER regions, or infer from page range."""
    for r in pc_regions:
        text = start_ext.regions_text.get(r.id, "")
        if not text:
            continue
        match_val = TextMatcher.match(r.match_type, r.match_pattern, text)
        if match_val:
            # Try "Page X of Y" or "X of Y" or "X/Y" patterns
            m = re.search(r'(\d+)\s*(?:of|/)\s*(\d+)', match_val, re.IGNORECASE)
            if m:
                return int(m.group(2))
            # Fallback: take the last number found
            nums = re.findall(r'\d+', match_val)
            if len(nums) >= 2:
                return int(nums[-1])

    # Infer from page range
    if page_format == PageFormat.DUPLEX:
        return ((end_page - start_page) // 2) + 1
    else:
        return (end_page - start_page) + 1


def _extract_unique_id(
    start_ext: PageExtraction,
    uid_regions: list,
) -> int | None:
    """Extract a 9-digit unique ID from UNIQUE_ID regions."""
    for r in uid_regions:
        text = start_ext.regions_text.get(r.id, "")
        if not text:
            continue
        match_val = TextMatcher.match(r.match_type, r.match_pattern, text)
        if match_val:
            digits = ''.join(re.findall(r'\d+', match_val))
            if digits:
                # Take last 9 digits, zero-pad if shorter
                uid = int(digits[-9:])
                return uid
    return None
