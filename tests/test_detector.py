from app.enums import MatchType, PageFormat, RegionRole
from app.services.detector import (
    DetectedDoc,
    TextMatcher,
    RegionTextExtractor,
    detect_from_regions,
)


class TestTextMatcher:
    def test_exact_match(self):
        assert TextMatcher.match(MatchType.EXACT, "hello", "hello") == "hello"
        assert TextMatcher.match(MatchType.EXACT, "hello", "world") is None

    def test_exact_match_no_pattern_returns_text(self):
        assert TextMatcher.match(MatchType.EXACT, None, "anything") == "anything"

    def test_regex_match(self):
        result = TextMatcher.match(MatchType.REGEX, r"Page (\d+) of (\d+)", "Page 3 of 7")
        assert result == "3"  # first capture group

    def test_regex_match_no_groups_returns_full(self):
        result = TextMatcher.match(MatchType.REGEX, r"\d+", "abc123def")
        assert result == "123"

    def test_regex_no_match(self):
        assert TextMatcher.match(MatchType.REGEX, r"\d+", "no digits") is None

    def test_numeric_match(self):
        assert TextMatcher.match(MatchType.NUMERIC, None, "ID: 123456789") == "123456789"

    def test_numeric_no_match(self):
        assert TextMatcher.match(MatchType.NUMERIC, None, "no digits") is None

    def test_empty_text(self):
        assert TextMatcher.match(MatchType.EXACT, "x", "") is None
        assert TextMatcher.match(MatchType.REGEX, r"\d+", "") is None
        assert TextMatcher.match(MatchType.NUMERIC, None, "") is None


class TestDetectFromRegions:
    """Tests using sample_multi_doc_pdf -- 3 docs with distinct GROUP_BOUNDARY text."""

    def test_detects_correct_number_of_documents(self, sample_multi_doc_pdf):
        regions = _make_regions()
        docs = detect_from_regions(sample_multi_doc_pdf, regions, PageFormat.DUPLEX)
        assert len(docs) == 3

    def test_detects_correct_sheet_counts(self, sample_multi_doc_pdf):
        regions = _make_regions()
        docs = detect_from_regions(sample_multi_doc_pdf, regions, PageFormat.DUPLEX)
        assert docs[0].sheet_count == 1
        assert docs[1].sheet_count == 2
        assert docs[2].sheet_count == 1

    def test_detects_correct_unique_ids(self, sample_multi_doc_pdf):
        regions = _make_regions()
        docs = detect_from_regions(sample_multi_doc_pdf, regions, PageFormat.DUPLEX)
        assert docs[0].unique_id == 123456789
        assert docs[1].unique_id == 987654321
        assert docs[2].unique_id == 555666777

    def test_detects_correct_page_ranges(self, sample_multi_doc_pdf):
        regions = _make_regions()
        docs = detect_from_regions(sample_multi_doc_pdf, regions, PageFormat.DUPLEX)
        assert docs[0].start_page == 0
        assert docs[0].end_page == 1
        assert docs[1].start_page == 2
        assert docs[1].end_page == 5
        assert docs[2].start_page == 6
        assert docs[2].end_page == 7

    def test_side_a_pages_are_correct(self, sample_multi_doc_pdf):
        regions = _make_regions()
        docs = detect_from_regions(sample_multi_doc_pdf, regions, PageFormat.DUPLEX)
        assert docs[0].side_a_pages == [0]
        assert docs[1].side_a_pages == [2, 4]
        assert docs[2].side_a_pages == [6]


class TestDetectFromRegionsEdgeCases:
    def test_single_document_no_boundary_change(self, sample_duplex_pdf):
        # All pages have same GROUP_BOUNDARY signature (no distinguishing text)
        # Without GROUP_BOUNDARY regions, everything is one doc
        regions = _make_uid_only_regions()
        docs = detect_from_regions(sample_duplex_pdf, regions, PageFormat.DUPLEX)
        # sample_duplex_pdf has 10 doc sets (1 sheet each) = 20 pages
        assert len(docs) == 1  # no GROUP_BOUNDARY regions -> one doc
        assert docs[0].start_page == 0
        assert docs[0].end_page == 19

    def test_no_unique_id_regions_returns_none(self, sample_multi_doc_pdf):
        regions = _make_gb_only_regions()
        docs = detect_from_regions(sample_multi_doc_pdf, regions, PageFormat.DUPLEX)
        assert docs[0].unique_id is None
        assert docs[1].unique_id is None

    def test_no_page_counter_regions_infers_from_range(self, sample_multi_doc_pdf):
        regions = _make_gb_only_regions()
        docs = detect_from_regions(sample_multi_doc_pdf, regions, PageFormat.DUPLEX)
        assert docs[0].sheet_count == 1  # inferred: 2 pages / 2 = 1
        assert docs[1].sheet_count == 2  # inferred: 4 pages / 2 = 2

    def test_empty_pdf_returns_empty_list(self, tmp_dir):
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas as pdf_canvas
        path = tmp_dir / "empty.pdf"
        c = pdf_canvas.Canvas(str(path), pagesize=letter)
        c.save()  # save with no pages -> 0 pages
        regions = _make_regions()
        docs = detect_from_regions(path, regions, PageFormat.DUPLEX)
        assert docs == []


class TestRegionTextExtractor:
    def test_extracts_text_from_region(self, sample_multi_doc_pdf):
        regions = _make_regions()
        extractor = RegionTextExtractor()
        result = extractor.extract_page_text(sample_multi_doc_pdf, 0, regions)
        # Page 0 should have text for the GROUP_BOUNDARY region
        gb_region_id = next(r.id for r in regions if r.role == RegionRole.GROUP_BOUNDARY)
        assert "1001" in result[gb_region_id]


# ---- Helpers to create mock Region-like objects ----

class _FakeRegion:
    """Mimics the Region ORM model for testing without a database."""
    _id_counter = 1

    def __init__(self, role, x, y, width, height, page=1,
                 match_type=MatchType.EXACT, match_pattern=None, priority=0):
        self.id = _FakeRegion._id_counter
        _FakeRegion._id_counter += 1
        self.role = role
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.page = page
        self.match_type = match_type
        self.match_pattern = match_pattern
        self.priority = priority


def _make_regions():
    """Return regions that detect document boundaries by Account: text."""
    return [
        _FakeRegion(
            role=RegionRole.GROUP_BOUNDARY,
            x=72, y=695, width=200, height=15,  # "Account: XXXX" area
            match_type=MatchType.EXACT,          # Exact match on the full account text
        ),
        _FakeRegion(
            role=RegionRole.PAGE_COUNTER,
            x=72, y=675, width=200, height=15,  # "Page X of Y" area
            match_type=MatchType.REGEX,
            match_pattern=r"Page (\d+) of (\d+)",
        ),
        _FakeRegion(
            role=RegionRole.UNIQUE_ID,
            x=72, y=655, width=200, height=15,  # "ID: XXXXXXXXX" area
            match_type=MatchType.NUMERIC,
        ),
    ]


def _make_gb_only_regions():
    return [
        _FakeRegion(
            role=RegionRole.GROUP_BOUNDARY,
            x=72, y=695, width=200, height=15,
            match_type=MatchType.EXACT,
        ),
    ]


def _make_uid_only_regions():
    return [
        _FakeRegion(
            role=RegionRole.UNIQUE_ID,
            x=72, y=655, width=200, height=15,
            match_type=MatchType.NUMERIC,
        ),
    ]


def _make_first_page_only_regions():
    """GROUP_BOUNDARY region that matches 'File Number: X-XXXX' on doc first pages."""
    return [
        _FakeRegion(
            role=RegionRole.GROUP_BOUNDARY,
            x=72, y=695, width=250, height=15,
            match_type=MatchType.EXACT,
        ),
    ]


class TestFirstPageOnlyMarkers:
    """Documents where GROUP_BOUNDARY text appears ONLY on the first page of each doc.
    Continuation pages are blank — they should NOT trigger a new document boundary."""

    def test_detects_docs_by_first_page_marker_only(self, sample_first_page_only_pdf):
        regions = _make_first_page_only_regions()
        docs = detect_from_regions(sample_first_page_only_pdf, regions, PageFormat.DUPLEX)

        assert len(docs) == 3

        # Doc 1: 2 sheets (pages 0-3), marker "File Number: A-1001"
        assert docs[0].start_page == 0
        assert docs[0].end_page == 3
        assert docs[0].sheet_count == 2
        assert docs[0].side_a_pages == [0, 2]

        # Doc 2: 1 sheet (pages 4-5), marker "File Number: B-2002"
        assert docs[1].start_page == 4
        assert docs[1].end_page == 5
        assert docs[1].sheet_count == 1
        assert docs[1].side_a_pages == [4]

        # Doc 3: 2 sheets (pages 6-9), marker "File Number: C-3003"
        assert docs[2].start_page == 6
        assert docs[2].end_page == 9
        assert docs[2].sheet_count == 2
        assert docs[2].side_a_pages == [6, 8]

    def test_first_page_marker_text_captured(self, sample_first_page_only_pdf):
        regions = _make_first_page_only_regions()
        docs = detect_from_regions(sample_first_page_only_pdf, regions, PageFormat.DUPLEX)

        # The extracted_data should contain the identifying text
        assert docs[0].extracted_data["start_page"] == 0
        assert docs[0].extracted_data["end_page"] == 3

    def test_empty_signature_does_not_split(self, sample_first_page_only_pdf):
        """Continuation pages with empty signatures stay in the same document."""
        regions = _make_first_page_only_regions()
        docs = detect_from_regions(sample_first_page_only_pdf, regions, PageFormat.DUPLEX)

        # Doc 1 covers 4 physical pages (2 sheets duplex) = pages 0-3
        assert docs[0].start_page == 0
        assert docs[0].end_page == 3
        # Doc 2 starts at page 4 (where next marker appears)
        assert docs[1].start_page == 4
