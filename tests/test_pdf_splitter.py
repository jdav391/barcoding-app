import pytest
from app.services.pdf_splitter import split_by_preset, validate_page_count, DocSet
from app.enums import PageFormat


class TestValidatePageCount:
    def test_duplex_divides_evenly(self, sample_duplex_pdf):
        result = validate_page_count(sample_duplex_pdf, sheets_per_doc=1, page_format=PageFormat.DUPLEX)
        assert result.valid is True
        assert result.total_pages == 20
        assert result.doc_sets == 10

    def test_simplex_divides_evenly(self, sample_simplex_pdf):
        result = validate_page_count(sample_simplex_pdf, sheets_per_doc=1, page_format=PageFormat.SIMPLEX)
        assert result.valid is True
        assert result.total_pages == 10
        assert result.doc_sets == 10

    def test_multisheet_duplex(self, sample_multisheet_pdf):
        result = validate_page_count(sample_multisheet_pdf, sheets_per_doc=3, page_format=PageFormat.DUPLEX)
        assert result.valid is True
        assert result.total_pages == 24
        assert result.doc_sets == 4

    def test_uneven_pages_fails(self, sample_duplex_pdf):
        result = validate_page_count(sample_duplex_pdf, sheets_per_doc=3, page_format=PageFormat.DUPLEX)
        assert result.valid is False
        assert "20" in result.error
        assert "6" in result.error


class TestSplitByPreset:
    def test_duplex_single_sheet(self, sample_duplex_pdf):
        doc_sets = split_by_preset(sample_duplex_pdf, sheets_per_doc=1, page_format=PageFormat.DUPLEX)
        assert len(doc_sets) == 10
        assert doc_sets[0].start_page == 0
        assert doc_sets[0].end_page == 1
        assert doc_sets[0].sheet_count == 1
        assert doc_sets[0].side_a_pages == [0]

    def test_duplex_multi_sheet(self, sample_multisheet_pdf):
        doc_sets = split_by_preset(sample_multisheet_pdf, sheets_per_doc=3, page_format=PageFormat.DUPLEX)
        assert len(doc_sets) == 4
        assert doc_sets[0].sheet_count == 3
        assert doc_sets[0].side_a_pages == [0, 2, 4]
        assert doc_sets[0].start_page == 0
        assert doc_sets[0].end_page == 5
        assert doc_sets[1].start_page == 6
        assert doc_sets[1].side_a_pages == [6, 8, 10]

    def test_simplex_single_sheet(self, sample_simplex_pdf):
        doc_sets = split_by_preset(sample_simplex_pdf, sheets_per_doc=1, page_format=PageFormat.SIMPLEX)
        assert len(doc_sets) == 10
        assert doc_sets[0].side_a_pages == [0]
        assert doc_sets[0].start_page == 0
        assert doc_sets[0].end_page == 0

    def test_side_a_pages_are_correct(self, sample_multisheet_pdf):
        doc_sets = split_by_preset(sample_multisheet_pdf, sheets_per_doc=3, page_format=PageFormat.DUPLEX)
        for ds in doc_sets:
            for page_idx in ds.side_a_pages:
                assert page_idx % 2 == 0, f"Side-A page {page_idx} should be even (0-indexed)"
