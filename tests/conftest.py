import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas as pdf_canvas


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def sample_duplex_pdf(tmp_dir):
    """Create a 20-page duplex PDF (10 doc sets of 1 sheet each)."""
    path = tmp_dir / "sample_duplex.pdf"
    c = pdf_canvas.Canvas(str(path), pagesize=letter)
    for i in range(20):
        page_num = i + 1
        side = "A" if page_num % 2 == 1 else "B"
        doc_set = (i // 2) + 1
        c.drawString(72, 700, f"Document Set {doc_set} - Side {side} (Page {page_num})")
        c.showPage()
    c.save()
    return path


@pytest.fixture
def sample_simplex_pdf(tmp_dir):
    """Create a 10-page simplex PDF (10 doc sets of 1 sheet each)."""
    path = tmp_dir / "sample_simplex.pdf"
    c = pdf_canvas.Canvas(str(path), pagesize=letter)
    for i in range(10):
        c.drawString(72, 700, f"Document Set {i + 1} - Page {i + 1}")
        c.showPage()
    c.save()
    return path


@pytest.fixture
def sample_multisheet_pdf(tmp_dir):
    """Create a 24-page duplex PDF (4 doc sets of 3 sheets each)."""
    path = tmp_dir / "sample_multisheet.pdf"
    c = pdf_canvas.Canvas(str(path), pagesize=letter)
    for doc in range(4):
        for sheet in range(3):
            for side in ["A", "B"]:
                page = doc * 6 + sheet * 2 + (0 if side == "A" else 1) + 1
                c.drawString(72, 700, f"Doc {doc + 1}, Sheet {sheet + 1}, Side {side} (Page {page})")
                c.showPage()
    c.save()
    return path


@pytest.fixture
def sample_multi_doc_pdf(tmp_dir):
    """8-page duplex PDF: 3 docs with distinguishable GROUP_BOUNDARY text.

    Doc 1: 1 sheet (pages 0-1). Side A text: "Account: 1001\nPage 1 of 1\nID: 123456789"
    Doc 2: 2 sheets (pages 2-5). Side A text: "Account: 1002\nPage 1 of 2\nID: 987654321"
                                  Side A text: "Account: 1002\nPage 2 of 2"
    Doc 3: 1 sheet (pages 6-7). Side A text: "Account: 1003\nPage 1 of 1\nID: 555666777"
    """
    path = tmp_dir / "sample_multi_doc.pdf"
    c = pdf_canvas.Canvas(str(path), pagesize=letter)

    # Doc 1: 1 sheet
    c.drawString(72, 700, "Account: 1001")
    c.drawString(72, 680, "Page 1 of 1")
    c.drawString(72, 660, "ID: 123456789")
    c.showPage()  # page 0 (side A)
    c.drawString(72, 700, "Side B - Doc 1")
    c.showPage()  # page 1 (side B)

    # Doc 2: 2 sheets
    c.drawString(72, 700, "Account: 1002")
    c.drawString(72, 680, "Page 1 of 2")
    c.drawString(72, 660, "ID: 987654321")
    c.showPage()  # page 2 (side A)
    c.drawString(72, 700, "Side B - Doc 2 Sheet 1")
    c.showPage()  # page 3 (side B)
    c.drawString(72, 700, "Account: 1002")
    c.drawString(72, 680, "Page 2 of 2")
    c.showPage()  # page 4 (side A)
    c.drawString(72, 700, "Side B - Doc 2 Sheet 2")
    c.showPage()  # page 5 (side B)

    # Doc 3: 1 sheet
    c.drawString(72, 700, "Account: 1003")
    c.drawString(72, 680, "Page 1 of 1")
    c.drawString(72, 660, "ID: 555666777")
    c.showPage()  # page 6 (side A)
    c.drawString(72, 700, "Side B - Doc 3")
    c.showPage()  # page 7 (side B)

    c.save()
    return path


@pytest.fixture
def sample_first_page_only_pdf(tmp_dir):
    """10-page duplex PDF: 3 docs with GROUP_BOUNDARY text ONLY on the first side-A page.

    Simulates real documents where identifying markers (file number, address, etc.)
    appear only on page 1. Continuation pages are blank in the region area.

    Doc 1: 2 sheets (pages 0-3).  Marker on page 0 only.
    Doc 2: 1 sheet  (pages 4-5).  Marker on page 4 only.
    Doc 3: 2 sheets (pages 6-9).  Marker on page 6 only.
    """
    path = tmp_dir / "sample_first_page_only.pdf"
    c = pdf_canvas.Canvas(str(path), pagesize=letter)

    # Doc 1: 2 sheets — marker only on first side-A page
    c.drawString(72, 700, "File Number: A-1001")
    c.showPage()  # page 0 (side A, has marker)
    c.drawString(72, 700, "Continuation page - no marker")
    c.showPage()  # page 1 (side B)
    # Second sheet — no marker on either side
    c.showPage()  # page 2 (side A, blank)
    c.showPage()  # page 3 (side B, blank)

    # Doc 2: 1 sheet — marker only on first page
    c.drawString(72, 700, "File Number: B-2002")
    c.showPage()  # page 4 (side A, has marker)
    c.drawString(72, 700, "Continuation page - no marker")
    c.showPage()  # page 5 (side B)

    # Doc 3: 2 sheets — marker only on first page
    c.drawString(72, 700, "File Number: C-3003")
    c.showPage()  # page 6 (side A, has marker)
    c.drawString(72, 700, "Continuation page - no marker")
    c.showPage()  # page 7 (side B)
    # Second sheet — no marker
    c.showPage()  # page 8 (side A, blank)
    c.showPage()  # page 9 (side B, blank)

    c.save()
    return path
