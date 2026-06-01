import io
from app.services.batch_import import parse_email_text, parse_csv


class TestParseEmailText:
    def test_basic_double_sided(self):
        text = "Sent file: LetterBatch798236.pdf, Letters: 296, Total Sheets: 592, 2 sheets per envelope, Print type: Double sided color"
        results = parse_email_text(text)
        assert len(results) == 1
        r = results[0]
        assert r.batch_id == "LetterBatch798236"
        assert r.source_filename == "LetterBatch798236.pdf"
        assert r.expected_letters == 296
        assert r.expected_sheets == 592
        assert r.sheets_per_doc == 2
        assert r.print_type == "Double sided color"
        assert r.has_insert is False
        assert r.insert_description is None

    def test_with_insert(self):
        text = "Sent file: LetterBatch798226.pdf, Letters: 3, Total Sheets: 6, 2 sheets per envelope, Print type: Double sided color, Insert: Donation Inserts"
        results = parse_email_text(text)
        assert len(results) == 1
        r = results[0]
        assert r.expected_letters == 3
        assert r.has_insert is True
        assert r.insert_description == "Donation Inserts"

    def test_single_sided(self):
        text = "Sent file: LetterBatch798096.pdf, Letters: 342, Total Sheets: 342, Print type: Single sided black and white"
        results = parse_email_text(text)
        assert len(results) == 1
        r = results[0]
        assert r.expected_letters == 342
        assert r.expected_sheets == 342
        assert r.sheets_per_doc is None
        assert r.print_type == "Single sided black and white"

    def test_multiple_lines(self):
        text = """Sent file: LetterBatch001.pdf, Letters: 100, Total Sheets: 200, 2 sheets per envelope, Print type: Double sided color
Sent file: LetterBatch002.pdf, Letters: 50, Total Sheets: 50, Print type: Single sided black and white"""
        results = parse_email_text(text)
        assert len(results) == 2
        assert results[0].batch_id == "LetterBatch001"
        assert results[1].batch_id == "LetterBatch002"

    def test_empty_text(self):
        assert parse_email_text("") == []

    def test_non_matching_text(self):
        assert parse_email_text("Hello, this is unrelated text.") == []


class TestParseCSV:
    def test_basic_csv(self):
        csv_content = """batch_id,source_filename,expected_letters,expected_sheets,sheets_per_doc,print_type,has_insert,insert_description
LetterBatch001,LetterBatch001.pdf,100,200,2,Double sided color,false,
LetterBatch002,LetterBatch002.pdf,50,50,1,Single sided black and white,true,Donation Inserts"""
        results = parse_csv(io.StringIO(csv_content))
        assert len(results) == 2
        assert results[0].batch_id == "LetterBatch001"
        assert results[0].expected_letters == 100
        assert results[0].has_insert is False
        assert results[1].has_insert is True
        assert results[1].insert_description == "Donation Inserts"

    def test_empty_csv(self):
        csv_content = "batch_id,source_filename,expected_letters,expected_sheets\n"
        results = parse_csv(io.StringIO(csv_content))
        assert results == []
