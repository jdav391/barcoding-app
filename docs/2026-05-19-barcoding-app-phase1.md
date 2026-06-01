# Barcoding App Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local web application that generates and embeds 2D DataMatrix barcodes into large multi-page PDFs for intelligent inserting machines, using manual preset mode with fixed parameters.

**Architecture:** FastAPI serves REST endpoints and Jinja2/HTMX pages. SQLite via SQLAlchemy stores presets, jobs, batch imports, and a rolling sequence counter. Services handle barcode generation (pylibdmtx), PDF splitting/embedding (pypdf + reportlab), email/CSV parsing, and verification reporting. One job per source PDF, processing pipeline: Split -> Generate -> Embed -> Merge -> Verify.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, SQLAlchemy, Jinja2, HTMX, pypdf, reportlab, pylibdmtx, Pillow, Pico CSS

**Spec:** `docs/superpowers/specs/2026-05-19-barcoding-app-phase1-design.md`

---

## File Structure

```
barcoding-app/
├── pyproject.toml
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, startup, mount routes
│   ├── config.py            # Pydantic settings
│   ├── enums.py             # Shared enums
│   ├── database.py          # SQLAlchemy engine, session, Base
│   ├── models.py            # ORM models
│   ├── schemas.py           # Pydantic request/response models
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── presets.py       # Preset CRUD endpoints
│   │   ├── jobs.py          # Job CRUD, run, resume, WebSocket
│   │   ├── batch_import.py  # Paste/CSV/manual import endpoints
│   │   └── files.py         # Server-side file browser API
│   ├── services/
│   │   ├── __init__.py
│   │   ├── barcode.py       # Barcode string + DataMatrix image
│   │   ├── pdf_splitter.py  # Split large PDF into doc sets
│   │   ├── pdf_writer.py    # Embed barcode + text, merge PDFs
│   │   ├── batch_import.py  # Parse email text, CSV
│   │   ├── sequence.py      # Rolling SequenceCounter
│   │   ├── reporter.py      # Verification report
│   │   └── job.py           # Orchestration pipeline
│   ├── templates/
│   │   ├── base.html
│   │   ├── home.html
│   │   ├── presets/
│   │   │   ├── list.html
│   │   │   └── form.html
│   │   ├── wizard/
│   │   │   ├── layout.html
│   │   │   ├── step1_name.html
│   │   │   ├── step2_batch.html
│   │   │   ├── step3_source.html
│   │   │   ├── step4_preset.html
│   │   │   └── step5_review.html
│   │   ├── partials/
│   │   │   ├── file_browser.html
│   │   │   ├── batch_preview.html
│   │   │   └── progress.html
│   │   └── report.html
│   └── static/
│       ├── css/
│       │   └── style.css
│       └── js/
│           └── app.js
└── tests/
    ├── __init__.py
    ├── conftest.py          # Shared fixtures: test DB, sample PDFs
    ├── test_barcode.py
    ├── test_batch_import.py
    ├── test_pdf_splitter.py
    ├── test_pdf_writer.py
    ├── test_sequence.py
    ├── test_reporter.py
    ├── test_integration.py
    └── test_routes/
        ├── __init__.py
        ├── conftest.py      # TestClient fixture
        ├── test_presets.py
        ├── test_files.py
        └── test_jobs.py
```

---

### Task 1: Project Scaffolding + Database

**Files:**
- Create: `barcoding-app/pyproject.toml`
- Create: `barcoding-app/app/__init__.py`
- Create: `barcoding-app/app/config.py`
- Create: `barcoding-app/app/enums.py`
- Create: `barcoding-app/app/database.py`
- Create: `barcoding-app/app/models.py`
- Create: `barcoding-app/app/schemas.py`
- Create: `barcoding-app/app/main.py`
- Create: `barcoding-app/app/routes/__init__.py`
- Create: `barcoding-app/app/services/__init__.py`
- Create: `barcoding-app/tests/__init__.py`
- Create: `barcoding-app/tests/conftest.py`

- [ ] **Step 1: Create project directory and pyproject.toml**

```bash
mkdir -p /Volumes/NVME4TB/Users/joeldavidson/projects/barcoding-app
```

```toml
# pyproject.toml
[project]
name = "barcoding-app"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "sqlalchemy>=2.0.0",
    "jinja2>=3.1.0",
    "python-multipart>=0.0.9",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "pypdf>=4.0.0",
    "reportlab>=4.0.0",
    "pylibdmtx>=0.1.10",
    "Pillow>=10.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "httpx>=0.27.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create config.py**

```python
# app/config.py
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Barcoding App"
    database_url: str = "sqlite:///./barcoding.db"
    host: str = "127.0.0.1"
    port: int = 8000
    allowed_browse_roots: list[str] = []
    default_module_size_mm: float = 0.50
    default_quiet_zone_mm: float = 6.5
    default_dpi: int = 600
    overflow_threshold: int = 6

    model_config = {"env_prefix": "BARCODE_"}


settings = Settings()
```

- [ ] **Step 3: Create enums.py**

```python
# app/enums.py
import enum


class PageFormat(str, enum.Enum):
    DUPLEX = "DUPLEX"
    SIMPLEX = "SIMPLEX"


class FeedDirection(str, enum.Enum):
    ASCENDING = "ASCENDING"
    DESCENDING = "DESCENDING"


class IdSource(str, enum.Enum):
    SEQUENTIAL = "SEQUENTIAL"
    DOCUMENT_EXTRACT = "DOCUMENT_EXTRACT"


class JobStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PROCESSING = "PROCESSING"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"
    ERROR = "ERROR"


class VerificationStatus(str, enum.Enum):
    OK = "OK"
    MISMATCH = "MISMATCH"
    ERROR = "ERROR"


class ImportMethod(str, enum.Enum):
    MANUAL = "MANUAL"
    PASTE = "PASTE"
    CSV = "CSV"
```

- [ ] **Step 4: Create database.py**

```python
# app/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(
    settings.database_url, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
```

- [ ] **Step 5: Create models.py**

```python
# app/models.py
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import relationship

from app.database import Base
from app.enums import (
    FeedDirection,
    IdSource,
    ImportMethod,
    JobStatus,
    PageFormat,
    VerificationStatus,
)

DEFAULT_EMBED_CONFIG = {
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


class SequenceCounter(Base):
    __tablename__ = "sequence_counters"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False, default="global")
    last_value = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Preset(Base):
    __tablename__ = "presets"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    sheets_per_doc = Column(Integer, nullable=False)
    page_format = Column(
        SAEnum(PageFormat), nullable=False, default=PageFormat.DUPLEX
    )
    has_insert = Column(Boolean, nullable=False, default=False)
    has_divert = Column(Boolean, nullable=False, default=False)
    divert_overflow = Column(Boolean, nullable=False, default=False)
    feed_direction = Column(
        SAEnum(FeedDirection), nullable=False, default=FeedDirection.ASCENDING
    )
    id_source = Column(
        SAEnum(IdSource), nullable=False, default=IdSource.SEQUENTIAL
    )
    embed_config = Column(JSON, nullable=False, default=DEFAULT_EMBED_CONFIG)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    jobs = relationship("Job", back_populates="preset")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    session_id = Column(String, nullable=False)
    date = Column(Date, nullable=False, default=date.today)
    source_path = Column(String, nullable=False)
    preset_id = Column(Integer, ForeignKey("presets.id"), nullable=False)
    status = Column(SAEnum(JobStatus), nullable=False, default=JobStatus.DRAFT)
    last_processed_index = Column(Integer, nullable=True)
    total_doc_sets = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    preset = relationship("Preset", back_populates="jobs")
    result = relationship("JobResult", back_populates="job", uselist=False)
    batch_imports = relationship("BatchImport", back_populates="job")


class JobResult(Base):
    __tablename__ = "job_results"

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    total_barcodes = Column(Integer, nullable=False, default=0)
    total_documents = Column(Integer, nullable=False, default=0)
    total_sheets = Column(Integer, nullable=False, default=0)
    overflow_docs = Column(Integer, nullable=False, default=0)
    diverts_triggered = Column(Integer, nullable=False, default=0)
    insert_count = Column(Integer, nullable=False, default=0)
    verification = Column(
        SAEnum(VerificationStatus), nullable=False, default=VerificationStatus.OK
    )
    report_path = Column(String, nullable=True)
    output_dir = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("Job", back_populates="result")


class BatchImport(Base):
    __tablename__ = "batch_imports"

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    batch_id = Column(String, nullable=False)
    source_filename = Column(String, nullable=True)
    expected_letters = Column(Integer, nullable=False)
    expected_sheets = Column(Integer, nullable=False)
    sheets_per_doc = Column(Integer, nullable=True)
    print_type = Column(String, nullable=True)
    has_insert = Column(Boolean, nullable=False, default=False)
    insert_description = Column(String, nullable=True)
    import_method = Column(SAEnum(ImportMethod), nullable=False)
    raw_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("Job", back_populates="batch_imports")
```

- [ ] **Step 6: Create schemas.py**

```python
# app/schemas.py
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.enums import (
    FeedDirection,
    IdSource,
    ImportMethod,
    JobStatus,
    PageFormat,
    VerificationStatus,
)
from app.models import DEFAULT_EMBED_CONFIG


class BarcodeEmbedConfig(BaseModel):
    anchor: str = "bottom-right"
    x_offset_pt: float = 36
    y_offset_pt: float = 36
    module_size_mm: float = 0.50
    quiet_zone_mm: float = 6.5
    dpi: int = 600


class HumanReadableConfig(BaseModel):
    enabled: bool = True
    anchor: str = "bottom-left"
    x_offset_pt: float = 36
    y_offset_pt: float = 36
    rotation: int = 90
    font_name: str = "Courier"
    font_size: int = 8


class EmbedConfig(BaseModel):
    barcode: BarcodeEmbedConfig = BarcodeEmbedConfig()
    human_readable: HumanReadableConfig = HumanReadableConfig()


class PresetCreate(BaseModel):
    name: str
    sheets_per_doc: int = Field(ge=1, le=9)
    page_format: PageFormat = PageFormat.DUPLEX
    has_insert: bool = False
    has_divert: bool = False
    divert_overflow: bool = False
    feed_direction: FeedDirection = FeedDirection.ASCENDING
    id_source: IdSource = IdSource.SEQUENTIAL
    embed_config: EmbedConfig = EmbedConfig()


class PresetResponse(BaseModel):
    id: int
    name: str
    sheets_per_doc: int
    page_format: PageFormat
    has_insert: bool
    has_divert: bool
    divert_overflow: bool
    feed_direction: FeedDirection
    id_source: IdSource
    embed_config: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobCreate(BaseModel):
    name: str
    session_id: str
    date: date = Field(default_factory=date.today)
    source_path: str
    preset_id: int


class JobResponse(BaseModel):
    id: int
    name: str
    session_id: str
    date: date
    source_path: str
    preset_id: int
    status: JobStatus
    last_processed_index: int | None
    total_doc_sets: int | None
    created_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class BatchImportData(BaseModel):
    batch_id: str
    source_filename: str | None = None
    expected_letters: int
    expected_sheets: int
    sheets_per_doc: int | None = None
    print_type: str | None = None
    has_insert: bool = False
    insert_description: str | None = None


class BatchImportCreate(BaseModel):
    job_id: int
    import_method: ImportMethod
    raw_text: str | None = None
    data: list[BatchImportData]


class JobResultResponse(BaseModel):
    total_barcodes: int
    total_documents: int
    total_sheets: int
    overflow_docs: int
    diverts_triggered: int
    insert_count: int
    verification: VerificationStatus
    report_path: str | None
    output_dir: str | None

    model_config = {"from_attributes": True}


class FileEntry(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int | None = None
    page_count: int | None = None
```

- [ ] **Step 7: Create main.py with FastAPI shell**

```python
# app/main.py
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database import create_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    yield


app = FastAPI(title="Barcoding App", lifespan=lifespan)

static_dir = Path(__file__).parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
```

- [ ] **Step 8: Create empty __init__.py files and package markers**

```python
# app/__init__.py — empty
# app/routes/__init__.py — empty
# app/services/__init__.py — empty
# tests/__init__.py — empty
```

- [ ] **Step 9: Create tests/conftest.py with database fixture**

```python
# tests/conftest.py
import os
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
```

- [ ] **Step 10: Create virtual environment and install dependencies**

```bash
cd /Volumes/NVME4TB/Users/joeldavidson/projects/barcoding-app
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

On macOS, pylibdmtx needs libdmtx:

```bash
brew install libdmtx
```

- [ ] **Step 11: Initialize git and verify setup**

```bash
cd /Volumes/NVME4TB/Users/joeldavidson/projects/barcoding-app
git init
echo ".venv/\n__pycache__/\n*.db\n*.pyc\n.pytest_cache/" > .gitignore
python -c "from app.database import create_tables; create_tables(); print('DB OK')"
pytest --co -q
```

Expected: `DB OK` and pytest discovers 0 tests (no test files yet).

- [ ] **Step 12: Commit**

```bash
git add pyproject.toml .gitignore app/ tests/
git commit -m "feat: project scaffolding with FastAPI, SQLAlchemy models, and config"
```

---

### Task 2: BarcodeService — String Generation (TDD)

**Files:**
- Create: `app/services/barcode.py`
- Create: `tests/test_barcode.py`

- [ ] **Step 1: Write failing tests for barcode string generation**

```python
# tests/test_barcode.py
from app.services.barcode import generate_barcode_string, validate_barcode_string


class TestGenerateBarcodeString:
    def test_standard_13_char(self):
        result = generate_barcode_string(
            unique_id=158404144,
            sheet_number=3,
            set_count=7,
            has_insert=False,
            is_end_of_group=False,
        )
        assert result == "0307158404144"
        assert len(result) == 13

    def test_end_of_group(self):
        result = generate_barcode_string(
            unique_id=158404144,
            sheet_number=7,
            set_count=7,
            has_insert=False,
            is_end_of_group=True,
        )
        assert result == "1707158404144"

    def test_with_insert(self):
        result = generate_barcode_string(
            unique_id=158404144,
            sheet_number=1,
            set_count=1,
            has_insert=True,
            is_end_of_group=True,
        )
        assert result == "1111158404144"

    def test_unique_id_zero_padded(self):
        result = generate_barcode_string(
            unique_id=42,
            sheet_number=1,
            set_count=1,
            has_insert=False,
            is_end_of_group=True,
        )
        assert result == "1101000000042"

    def test_unique_id_truncated_to_9_digits(self):
        result = generate_barcode_string(
            unique_id=1234567890,
            sheet_number=1,
            set_count=1,
            has_insert=False,
            is_end_of_group=True,
        )
        assert result == "1101234567890"
        assert len(result) == 13

    def test_with_divert_14_char(self):
        result = generate_barcode_string(
            unique_id=158404144,
            sheet_number=3,
            set_count=7,
            has_insert=False,
            is_end_of_group=False,
            divert=True,
        )
        assert result == "03071158404144"
        assert len(result) == 14

    def test_divert_false_14_char(self):
        result = generate_barcode_string(
            unique_id=158404144,
            sheet_number=3,
            set_count=7,
            has_insert=False,
            is_end_of_group=False,
            divert=False,
        )
        assert result == "03070158404144"
        assert len(result) == 14

    def test_single_sheet_is_eog(self):
        result = generate_barcode_string(
            unique_id=1,
            sheet_number=1,
            set_count=1,
            has_insert=False,
            is_end_of_group=True,
        )
        assert result == "1101000000001"


class TestValidateBarcodeString:
    def test_valid_13_char(self):
        assert validate_barcode_string("0307158404144") is True

    def test_valid_14_char(self):
        assert validate_barcode_string("03071158404144") is True

    def test_wrong_length(self):
        assert validate_barcode_string("030715840414") is False
        assert validate_barcode_string("030715840414400") is False

    def test_non_numeric(self):
        assert validate_barcode_string("030715840414A") is False

    def test_invalid_eog(self):
        assert validate_barcode_string("2307158404144") is False

    def test_invalid_sheet_zero(self):
        assert validate_barcode_string("0007158404144") is False

    def test_invalid_insert(self):
        assert validate_barcode_string("0327158404144") is False

    def test_invalid_set_count_zero(self):
        assert validate_barcode_string("0300158404144") is False

    def test_invalid_divert_in_14_char(self):
        assert validate_barcode_string("03072158404144") is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Volumes/NVME4TB/Users/joeldavidson/projects/barcoding-app
pytest tests/test_barcode.py -v
```

Expected: All tests FAIL with `ImportError` (module not found).

- [ ] **Step 3: Implement barcode string generation**

```python
# app/services/barcode.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SheetBarcode:
    doc_index: int
    sheet_number: int
    barcode_string: str
    is_overflow: bool
    page_index: int


def generate_barcode_string(
    unique_id: int,
    sheet_number: int,
    set_count: int,
    has_insert: bool,
    is_end_of_group: bool,
    divert: bool | None = None,
) -> str:
    eog = "1" if is_end_of_group else "0"
    sheet = str(sheet_number)
    insert = "1" if has_insert else "0"
    count = str(set_count)
    uid = str(unique_id).zfill(9)[-9:]

    if divert is not None:
        div = "1" if divert else "0"
        return f"{eog}{sheet}{insert}{count}{div}{uid}"
    return f"{eog}{sheet}{insert}{count}{uid}"


def validate_barcode_string(barcode_string: str) -> bool:
    if len(barcode_string) not in (13, 14):
        return False
    if not barcode_string.isdigit():
        return False
    if barcode_string[0] not in ("0", "1"):
        return False
    if not 1 <= int(barcode_string[1]) <= 9:
        return False
    if barcode_string[2] not in ("0", "1"):
        return False
    if not 1 <= int(barcode_string[3]) <= 9:
        return False
    if len(barcode_string) == 14 and barcode_string[4] not in ("0", "1"):
        return False
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_barcode.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/barcode.py tests/test_barcode.py
git commit -m "feat: barcode string generation and validation with TDD"
```

---

### Task 3: BarcodeService — Image Generation (TDD)

**Files:**
- Modify: `app/services/barcode.py`
- Modify: `tests/test_barcode.py`

- [ ] **Step 1: Write failing test for image generation**

Add to `tests/test_barcode.py`:

```python
from PIL import Image

from app.services.barcode import generate_barcode_image


class TestGenerateBarcodeImage:
    def test_generates_pil_image(self):
        img = generate_barcode_image("0307158404144")
        assert isinstance(img, Image.Image)

    def test_default_dimensions_600dpi(self):
        img = generate_barcode_image("0307158404144", module_size_mm=0.50, quiet_zone_mm=6.5, dpi=600)
        module_px = round(0.50 * 600 / 25.4)  # ~12
        symbol_px = 18 * module_px
        quiet_px = round(6.5 * 600 / 25.4)  # ~154
        total_px = symbol_px + 2 * quiet_px
        assert img.width == total_px
        assert img.height == total_px

    def test_black_on_white(self):
        img = generate_barcode_image("0307158404144").convert("L")
        corners = [img.getpixel((0, 0)), img.getpixel((img.width - 1, 0))]
        assert all(c > 200 for c in corners), "Quiet zone corners should be white"

    def test_14_char_barcode(self):
        img = generate_barcode_image("03071158404144")
        assert isinstance(img, Image.Image)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_barcode.py::TestGenerateBarcodeImage -v
```

Expected: FAIL with `ImportError` (generate_barcode_image not found).

- [ ] **Step 3: Implement image generation**

Add to `app/services/barcode.py`:

```python
from PIL import Image
from pylibdmtx.pylibdmtx import encode as dmtx_encode


def generate_barcode_image(
    barcode_string: str,
    module_size_mm: float = 0.50,
    quiet_zone_mm: float = 6.5,
    dpi: int = 600,
) -> Image.Image:
    pixels_per_mm = dpi / 25.4
    module_px = round(module_size_mm * pixels_per_mm)
    quiet_zone_px = round(quiet_zone_mm * pixels_per_mm)

    encoded = dmtx_encode(barcode_string.encode("ascii"), size="18x18")
    raw = Image.frombytes("RGB", (encoded.width, encoded.height), encoded.pixels)

    symbol_px = 18 * module_px
    scaled = raw.resize((symbol_px, symbol_px), Image.NEAREST)

    total_px = symbol_px + 2 * quiet_zone_px
    final = Image.new("RGB", (total_px, total_px), "white")
    final.paste(scaled, (quiet_zone_px, quiet_zone_px))

    return final
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_barcode.py -v
```

Expected: All tests PASS. If pylibdmtx fails, verify libdmtx is installed (`brew install libdmtx` on macOS).

- [ ] **Step 5: Commit**

```bash
git add app/services/barcode.py tests/test_barcode.py
git commit -m "feat: DataMatrix barcode image generation via pylibdmtx"
```

---

### Task 4: BatchImportService (TDD)

**Files:**
- Create: `app/services/batch_import.py`
- Create: `tests/test_batch_import.py`

- [ ] **Step 1: Write failing tests for email text parsing**

```python
# tests/test_batch_import.py
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

    def test_derives_sheets_per_doc_when_absent(self):
        text = "Sent file: LetterBatch798096.pdf, Letters: 342, Total Sheets: 342, Print type: Single sided black and white"
        results = parse_email_text(text)
        assert results[0].sheets_per_doc is None


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_batch_import.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement batch import service**

```python
# app/services/batch_import.py
from __future__ import annotations

import csv
import re
from io import StringIO
from typing import IO

from app.schemas import BatchImportData

EMAIL_PATTERN = re.compile(
    r"Sent file:\s*(?P<filename>\S+\.pdf)"
    r",\s*Letters:\s*(?P<letters>\d+)"
    r",\s*Total Sheets:\s*(?P<sheets>\d+)"
    r"(?:,\s*(?P<spe>\d+)\s*sheets? per envelope)?"
    r",\s*Print type:\s*(?P<print_type>[^,]+?)"
    r"(?:,\s*Insert:\s*(?P<insert>.+))?"
    r"\s*$",
    re.MULTILINE,
)


def parse_email_text(text: str) -> list[BatchImportData]:
    results = []
    for m in EMAIL_PATTERN.finditer(text):
        filename = m.group("filename")
        batch_id = filename.rsplit(".", 1)[0]
        spe = m.group("spe")
        insert_desc = m.group("insert")
        results.append(
            BatchImportData(
                batch_id=batch_id,
                source_filename=filename,
                expected_letters=int(m.group("letters")),
                expected_sheets=int(m.group("sheets")),
                sheets_per_doc=int(spe) if spe else None,
                print_type=m.group("print_type").strip(),
                has_insert=insert_desc is not None,
                insert_description=insert_desc.strip() if insert_desc else None,
            )
        )
    return results


def parse_csv(file: IO[str]) -> list[BatchImportData]:
    reader = csv.DictReader(file)
    results = []
    for row in reader:
        if not row.get("batch_id"):
            continue
        insert_val = row.get("has_insert", "false").strip().lower()
        results.append(
            BatchImportData(
                batch_id=row["batch_id"],
                source_filename=row.get("source_filename") or None,
                expected_letters=int(row["expected_letters"]),
                expected_sheets=int(row["expected_sheets"]),
                sheets_per_doc=int(row["sheets_per_doc"]) if row.get("sheets_per_doc") else None,
                print_type=row.get("print_type") or None,
                has_insert=insert_val in ("true", "1", "yes"),
                insert_description=row.get("insert_description") or None,
            )
        )
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_batch_import.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/batch_import.py tests/test_batch_import.py
git commit -m "feat: batch import service with email text and CSV parsing"
```

---

### Task 5: PDFSplitterService (TDD)

**Files:**
- Create: `app/services/pdf_splitter.py`
- Create: `tests/test_pdf_splitter.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_pdf_splitter.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_pdf_splitter.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement PDF splitter**

```python
# app/services/pdf_splitter.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader

from app.enums import PageFormat


@dataclass
class DocSet:
    index: int
    start_page: int
    end_page: int
    sheet_count: int
    side_a_pages: list[int] = field(default_factory=list)


@dataclass
class ValidationResult:
    valid: bool
    total_pages: int = 0
    doc_sets: int = 0
    pages_per_set: int = 0
    error: str | None = None


def validate_page_count(
    pdf_path: Path, sheets_per_doc: int, page_format: PageFormat
) -> ValidationResult:
    reader = PdfReader(str(pdf_path))
    total_pages = len(reader.pages)
    pages_per_sheet = 2 if page_format == PageFormat.DUPLEX else 1
    pages_per_set = sheets_per_doc * pages_per_sheet

    if total_pages == 0:
        return ValidationResult(valid=False, total_pages=0, error="PDF has 0 pages")

    if total_pages % pages_per_set != 0:
        return ValidationResult(
            valid=False,
            total_pages=total_pages,
            pages_per_set=pages_per_set,
            error=(
                f"PDF has {total_pages} pages which does not divide evenly by "
                f"{pages_per_set} pages per set ({sheets_per_doc} sheets x "
                f"{pages_per_sheet} pages/sheet)"
            ),
        )

    return ValidationResult(
        valid=True,
        total_pages=total_pages,
        doc_sets=total_pages // pages_per_set,
        pages_per_set=pages_per_set,
    )


def split_by_preset(
    pdf_path: Path, sheets_per_doc: int, page_format: PageFormat
) -> list[DocSet]:
    reader = PdfReader(str(pdf_path))
    total_pages = len(reader.pages)
    pages_per_sheet = 2 if page_format == PageFormat.DUPLEX else 1
    pages_per_set = sheets_per_doc * pages_per_sheet

    doc_sets = []
    for i in range(0, total_pages, pages_per_set):
        start = i
        end = i + pages_per_set - 1

        if page_format == PageFormat.DUPLEX:
            side_a = [i + s * 2 for s in range(sheets_per_doc)]
        else:
            side_a = list(range(i, i + sheets_per_doc))

        doc_sets.append(
            DocSet(
                index=len(doc_sets),
                start_page=start,
                end_page=end,
                sheet_count=sheets_per_doc,
                side_a_pages=side_a,
            )
        )

    return doc_sets
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_pdf_splitter.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/pdf_splitter.py tests/test_pdf_splitter.py
git commit -m "feat: PDF splitter service for duplex and simplex document sets"
```

---

### Task 6: PDFWriterService (TDD)

**Files:**
- Create: `app/services/pdf_writer.py`
- Create: `tests/test_pdf_writer.py`

- [ ] **Step 1: Write failing tests for barcode embedding and PDF merging**

```python
# tests/test_pdf_writer.py
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

from app.services.pdf_writer import embed_barcode_on_page, merge_pdfs, process_document


def _make_barcode_image(size=100):
    img = Image.new("RGB", (size, size), "black")
    return img


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
        img = _make_barcode_image()
        embed_barcode_on_page(
            pdf_path=sample_duplex_pdf,
            page_index=0,
            barcode_image=img,
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
        img = _make_barcode_image()
        embed_barcode_on_page(
            pdf_path=sample_duplex_pdf,
            page_index=0,
            barcode_image=img,
            barcode_text="0307158404144",
            embed_config=embed_config,
            output_path=output,
        )
        assert output.exists()


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


class TestMergePdfs:
    def test_merges_multiple_pdfs(self, sample_duplex_pdf, sample_simplex_pdf, tmp_dir):
        output = tmp_dir / "merged.pdf"
        merge_pdfs([sample_duplex_pdf, sample_simplex_pdf], output)
        reader = PdfReader(str(output))
        assert len(reader.pages) == 30
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_pdf_writer.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement PDF writer service**

```python
# app/services/pdf_writer.py
from __future__ import annotations

import io
import tempfile
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


def _barcode_position(page_width: float, page_height: float, img_width_pt: float, img_height_pt: float, config: dict) -> tuple[float, float]:
    anchor = config.get("anchor", "bottom-right")
    x_off = config.get("x_offset_pt", 36)
    y_off = config.get("y_offset_pt", 36)

    if anchor == "bottom-right":
        x = page_width - x_off - img_width_pt
        y = y_off
    elif anchor == "bottom-left":
        x = x_off
        y = y_off
    elif anchor == "top-right":
        x = page_width - x_off - img_width_pt
        y = page_height - y_off - img_height_pt
    elif anchor == "top-left":
        x = x_off
        y = page_height - y_off - img_height_pt
    else:
        x = page_width - x_off - img_width_pt
        y = y_off

    return x, y


def _create_overlay(
    page_width: float,
    page_height: float,
    barcode_image: Image.Image,
    barcode_text: str | None,
    embed_config: dict,
) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_width, page_height))

    bc_config = embed_config["barcode"]
    dpi = bc_config.get("dpi", 600)
    img_width_pt = barcode_image.width * 72.0 / dpi
    img_height_pt = barcode_image.height * 72.0 / dpi

    x, y = _barcode_position(page_width, page_height, img_width_pt, img_height_pt, bc_config)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        barcode_image.save(tmp, format="PNG")
        tmp_path = tmp.name

    c.drawImage(tmp_path, x, y, width=img_width_pt, height=img_height_pt)
    Path(tmp_path).unlink(missing_ok=True)

    hr_config = embed_config.get("human_readable", {})
    if hr_config.get("enabled") and barcode_text:
        hr_x, hr_y = _barcode_position(
            page_width, page_height,
            0, 0,
            hr_config,
        )
        c.saveState()
        c.translate(hr_x, hr_y)
        c.rotate(hr_config.get("rotation", 0))
        c.setFont(hr_config.get("font_name", "Courier"), hr_config.get("font_size", 8))
        c.drawString(0, 0, barcode_text)
        c.restoreState()

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()


def embed_barcode_on_page(
    pdf_path: Path,
    page_index: int,
    barcode_image: Image.Image,
    barcode_text: str,
    embed_config: dict,
    output_path: Path,
) -> None:
    reader = PdfReader(str(pdf_path))
    page = reader.pages[page_index]
    media = page.mediabox
    page_width = float(media.width)
    page_height = float(media.height)

    overlay_bytes = _create_overlay(page_width, page_height, barcode_image, barcode_text, embed_config)
    overlay_reader = PdfReader(io.BytesIO(overlay_bytes))

    page.merge_page(overlay_reader.pages[0])

    writer = PdfWriter()
    writer.add_page(page)
    with open(output_path, "wb") as f:
        writer.write(f)


def process_document(
    input_path: Path,
    page_range: tuple[int, int],
    side_a_barcodes: dict[int, tuple[Image.Image, str]],
    embed_config: dict,
    output_path: Path,
) -> None:
    reader = PdfReader(str(input_path))
    writer = PdfWriter()

    start, end = page_range
    for page_idx in range(start, end + 1):
        page = reader.pages[page_idx]

        if page_idx in side_a_barcodes:
            barcode_img, barcode_text = side_a_barcodes[page_idx]
            media = page.mediabox
            page_width = float(media.width)
            page_height = float(media.height)

            overlay_bytes = _create_overlay(
                page_width, page_height, barcode_img, barcode_text, embed_config
            )
            overlay_reader = PdfReader(io.BytesIO(overlay_bytes))
            page.merge_page(overlay_reader.pages[0])

        writer.add_page(page)

    with open(output_path, "wb") as f:
        writer.write(f)


def merge_pdfs(pdf_paths: list[Path], output_path: Path) -> None:
    writer = PdfWriter()
    for path in pdf_paths:
        reader = PdfReader(str(path))
        for page in reader.pages:
            writer.add_page(page)
    with open(output_path, "wb") as f:
        writer.write(f)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_pdf_writer.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/pdf_writer.py tests/test_pdf_writer.py
git commit -m "feat: PDF writer service — barcode embedding, page extraction, and PDF merging"
```

---

### Task 7: SequenceService (TDD)

**Files:**
- Create: `app/services/sequence.py`
- Create: `tests/test_sequence.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sequence.py
from app.services.sequence import claim_range, get_current_value, reset_counter
from app.models import SequenceCounter


class TestClaimRange:
    def test_first_claim_starts_at_1(self, db_session):
        start, end = claim_range(db_session, count=10)
        assert start == 1
        assert end == 10

    def test_second_claim_continues(self, db_session):
        claim_range(db_session, count=10)
        start, end = claim_range(db_session, count=5)
        assert start == 11
        assert end == 15

    def test_claim_single(self, db_session):
        start, end = claim_range(db_session, count=1)
        assert start == 1
        assert end == 1

    def test_named_counter(self, db_session):
        start1, _ = claim_range(db_session, count=5, counter_name="batch_a")
        start2, _ = claim_range(db_session, count=5, counter_name="batch_b")
        assert start1 == 1
        assert start2 == 1

    def test_persists_across_calls(self, db_session):
        claim_range(db_session, count=100)
        value = get_current_value(db_session)
        assert value == 100


class TestResetCounter:
    def test_reset_to_zero(self, db_session):
        claim_range(db_session, count=50)
        reset_counter(db_session)
        start, end = claim_range(db_session, count=1)
        assert start == 1

    def test_overflow_detection(self, db_session):
        counter = SequenceCounter(name="global", last_value=999_999_998)
        db_session.add(counter)
        db_session.commit()
        start, end = claim_range(db_session, count=1)
        assert start == 999_999_999
        assert end == 999_999_999
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_sequence.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement sequence service**

```python
# app/services/sequence.py
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import SequenceCounter


def claim_range(
    db: Session, count: int, counter_name: str = "global"
) -> tuple[int, int]:
    counter = db.query(SequenceCounter).filter_by(name=counter_name).first()
    if counter is None:
        counter = SequenceCounter(name=counter_name, last_value=0)
        db.add(counter)
        db.flush()

    start = counter.last_value + 1
    end = counter.last_value + count
    counter.last_value = end
    db.commit()
    return start, end


def get_current_value(db: Session, counter_name: str = "global") -> int:
    counter = db.query(SequenceCounter).filter_by(name=counter_name).first()
    return counter.last_value if counter else 0


def reset_counter(db: Session, counter_name: str = "global") -> None:
    counter = db.query(SequenceCounter).filter_by(name=counter_name).first()
    if counter:
        counter.last_value = 0
        db.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_sequence.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/sequence.py tests/test_sequence.py
git commit -m "feat: sequence counter service for rolling unique IDs"
```

---

### Task 8: ReporterService (TDD)

**Files:**
- Create: `app/services/reporter.py`
- Create: `tests/test_reporter.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_reporter.py
from app.services.reporter import verify_against_imports, generate_report
from app.enums import VerificationStatus


class TestVerifyAgainstImports:
    def test_matching_counts(self):
        actual = {"total_documents": 296, "total_sheets": 592}
        expected = [{"expected_letters": 296, "expected_sheets": 592}]
        result = verify_against_imports(actual, expected)
        assert result.status == VerificationStatus.OK
        assert result.match is True

    def test_letter_mismatch(self):
        actual = {"total_documents": 295, "total_sheets": 592}
        expected = [{"expected_letters": 296, "expected_sheets": 592}]
        result = verify_against_imports(actual, expected)
        assert result.status == VerificationStatus.MISMATCH
        assert result.match is False
        assert "documents" in result.details.lower()

    def test_sheet_mismatch(self):
        actual = {"total_documents": 296, "total_sheets": 590}
        expected = [{"expected_letters": 296, "expected_sheets": 592}]
        result = verify_against_imports(actual, expected)
        assert result.status == VerificationStatus.MISMATCH
        assert "sheets" in result.details.lower()

    def test_multiple_imports_summed(self):
        actual = {"total_documents": 350, "total_sheets": 700}
        expected = [
            {"expected_letters": 200, "expected_sheets": 400},
            {"expected_letters": 150, "expected_sheets": 300},
        ]
        result = verify_against_imports(actual, expected)
        assert result.status == VerificationStatus.OK

    def test_no_imports_skips_verification(self):
        actual = {"total_documents": 100, "total_sheets": 200}
        result = verify_against_imports(actual, [])
        assert result.status == VerificationStatus.OK
        assert result.match is True


class TestGenerateReport:
    def test_report_structure(self):
        job_info = {"name": "Daily Letters", "session_id": "20260519-001", "date": "2026-05-19"}
        totals = {
            "total_documents": 296,
            "total_sheets": 592,
            "total_barcodes": 592,
            "inserts_triggered": 0,
            "diverts_triggered": 0,
            "overflow_documents": 0,
        }
        imports = [{"expected_letters": 296, "expected_sheets": 592}]
        report = generate_report(job_info, totals, imports)
        assert report["job"] == "Daily Letters"
        assert report["session_id"] == "20260519-001"
        assert report["status"] == "OK"
        assert report["totals"]["documents_processed"] == 296
        assert report["verification"]["match"] is True
        assert report["verification"]["verdict"] == "OK"

    def test_report_with_overflow(self):
        job_info = {"name": "Test", "session_id": "001", "date": "2026-05-19"}
        totals = {
            "total_documents": 10,
            "total_sheets": 50,
            "total_barcodes": 50,
            "inserts_triggered": 0,
            "diverts_triggered": 2,
            "overflow_documents": 2,
        }
        overflow = [{"doc_index": 5, "sheets": 8}, {"doc_index": 9, "sheets": 7}]
        report = generate_report(job_info, totals, [], overflow_detail=overflow)
        assert report["totals"]["overflow_documents"] == 2
        assert len(report["overflow_detail"]) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_reporter.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement reporter service**

```python
# app/services/reporter.py
from __future__ import annotations

from dataclasses import dataclass

from app.enums import VerificationStatus


@dataclass
class VerificationResult:
    status: VerificationStatus
    match: bool
    details: str = ""


def verify_against_imports(
    actual: dict, expected_imports: list[dict]
) -> VerificationResult:
    if not expected_imports:
        return VerificationResult(status=VerificationStatus.OK, match=True)

    total_expected_letters = sum(e["expected_letters"] for e in expected_imports)
    total_expected_sheets = sum(e["expected_sheets"] for e in expected_imports)

    mismatches = []
    if actual["total_documents"] != total_expected_letters:
        mismatches.append(
            f"Documents: expected {total_expected_letters}, got {actual['total_documents']}"
        )
    if actual["total_sheets"] != total_expected_sheets:
        mismatches.append(
            f"Sheets: expected {total_expected_sheets}, got {actual['total_sheets']}"
        )

    if mismatches:
        return VerificationResult(
            status=VerificationStatus.MISMATCH,
            match=False,
            details="; ".join(mismatches),
        )

    return VerificationResult(status=VerificationStatus.OK, match=True)


def generate_report(
    job_info: dict,
    totals: dict,
    imports: list[dict],
    overflow_detail: list[dict] | None = None,
    warnings: list[str] | None = None,
) -> dict:
    verification = verify_against_imports(
        {"total_documents": totals["total_documents"], "total_sheets": totals["total_sheets"]},
        imports,
    )

    total_expected_letters = sum(e["expected_letters"] for e in imports) if imports else None
    total_expected_sheets = sum(e["expected_sheets"] for e in imports) if imports else None

    return {
        "job": job_info["name"],
        "session_id": job_info["session_id"],
        "date": job_info["date"],
        "status": verification.status.value,
        "totals": {
            "documents_processed": totals["total_documents"],
            "total_sheets": totals["total_sheets"],
            "total_barcodes": totals["total_barcodes"],
            "inserts_triggered": totals["inserts_triggered"],
            "diverts_triggered": totals["diverts_triggered"],
            "overflow_documents": totals["overflow_documents"],
        },
        "verification": {
            "expected_letters": total_expected_letters,
            "actual_documents": totals["total_documents"],
            "expected_sheets": total_expected_sheets,
            "actual_sheets": totals["total_sheets"],
            "match": verification.match,
            "verdict": verification.status.value,
            "details": verification.details or None,
        },
        "overflow_detail": overflow_detail or [],
        "warnings": warnings or [],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_reporter.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/reporter.py tests/test_reporter.py
git commit -m "feat: reporter service with verification and report generation"
```

---

### Task 9: Preset CRUD API (TDD)

**Files:**
- Create: `app/routes/presets.py`
- Modify: `app/main.py` (register router)
- Create: `tests/test_routes/__init__.py`
- Create: `tests/test_routes/conftest.py`
- Create: `tests/test_routes/test_presets.py`

- [ ] **Step 1: Create route test fixtures**

```python
# tests/test_routes/__init__.py — empty

# tests/test_routes/conftest.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Write failing preset API tests**

```python
# tests/test_routes/test_presets.py

VALID_PRESET = {
    "name": "Daily Single Sheet",
    "sheets_per_doc": 1,
    "page_format": "DUPLEX",
    "has_insert": False,
    "has_divert": False,
    "divert_overflow": False,
    "feed_direction": "ASCENDING",
    "id_source": "SEQUENTIAL",
    "embed_config": {
        "barcode": {
            "anchor": "bottom-right",
            "x_offset_pt": 36,
            "y_offset_pt": 36,
            "module_size_mm": 0.50,
            "quiet_zone_mm": 6.5,
            "dpi": 600,
        },
        "human_readable": {"enabled": False},
    },
}


class TestPresetCRUD:
    def test_create_preset(self, client):
        resp = client.post("/api/presets", json=VALID_PRESET)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Daily Single Sheet"
        assert data["id"] is not None

    def test_list_presets(self, client):
        client.post("/api/presets", json=VALID_PRESET)
        resp = client.get("/api/presets")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_get_preset(self, client):
        create = client.post("/api/presets", json=VALID_PRESET)
        pid = create.json()["id"]
        resp = client.get(f"/api/presets/{pid}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Daily Single Sheet"

    def test_update_preset(self, client):
        create = client.post("/api/presets", json=VALID_PRESET)
        pid = create.json()["id"]
        updated = {**VALID_PRESET, "name": "Updated Name", "has_insert": True}
        resp = client.put(f"/api/presets/{pid}", json=updated)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Name"
        assert resp.json()["has_insert"] is True

    def test_delete_preset(self, client):
        create = client.post("/api/presets", json=VALID_PRESET)
        pid = create.json()["id"]
        resp = client.delete(f"/api/presets/{pid}")
        assert resp.status_code == 204
        resp = client.get(f"/api/presets/{pid}")
        assert resp.status_code == 404

    def test_get_nonexistent_returns_404(self, client):
        resp = client.get("/api/presets/999")
        assert resp.status_code == 404

    def test_invalid_sheets_per_doc(self, client):
        bad = {**VALID_PRESET, "sheets_per_doc": 0}
        resp = client.post("/api/presets", json=bad)
        assert resp.status_code == 422
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_routes/test_presets.py -v
```

Expected: FAIL (route not registered).

- [ ] **Step 4: Implement preset routes**

```python
# app/routes/presets.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Preset
from app.schemas import PresetCreate, PresetResponse

router = APIRouter(prefix="/api/presets", tags=["presets"])


@router.post("", status_code=201, response_model=PresetResponse)
def create_preset(data: PresetCreate, db: Session = Depends(get_db)):
    preset = Preset(
        name=data.name,
        sheets_per_doc=data.sheets_per_doc,
        page_format=data.page_format,
        has_insert=data.has_insert,
        has_divert=data.has_divert,
        divert_overflow=data.divert_overflow,
        feed_direction=data.feed_direction,
        id_source=data.id_source,
        embed_config=data.embed_config.model_dump(),
    )
    db.add(preset)
    db.commit()
    db.refresh(preset)
    return preset


@router.get("", response_model=list[PresetResponse])
def list_presets(db: Session = Depends(get_db)):
    return db.query(Preset).order_by(Preset.name).all()


@router.get("/{preset_id}", response_model=PresetResponse)
def get_preset(preset_id: int, db: Session = Depends(get_db)):
    preset = db.get(Preset, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    return preset


@router.put("/{preset_id}", response_model=PresetResponse)
def update_preset(preset_id: int, data: PresetCreate, db: Session = Depends(get_db)):
    preset = db.get(Preset, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    for field, value in data.model_dump().items():
        if field == "embed_config":
            setattr(preset, field, value)
        else:
            setattr(preset, field, value)
    db.commit()
    db.refresh(preset)
    return preset


@router.delete("/{preset_id}", status_code=204)
def delete_preset(preset_id: int, db: Session = Depends(get_db)):
    preset = db.get(Preset, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    db.delete(preset)
    db.commit()
```

- [ ] **Step 5: Register router in main.py**

Add to `app/main.py` after `templates = ...`:

```python
from app.routes.presets import router as presets_router

app.include_router(presets_router)
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_routes/test_presets.py -v
```

Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add app/routes/presets.py tests/test_routes/ app/main.py
git commit -m "feat: preset CRUD API with full test coverage"
```

---

### Task 10: File Browser + Batch Import APIs

**Files:**
- Create: `app/routes/files.py`
- Create: `app/routes/batch_import.py`
- Create: `tests/test_routes/test_files.py`
- Modify: `app/main.py` (register routers)

- [ ] **Step 1: Write failing file browser tests**

```python
# tests/test_routes/test_files.py
import os


class TestFileBrowser:
    def test_list_directory(self, client, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "test.pdf").write_bytes(b"%PDF-1.4 fake")
        (tmp_path / "test.txt").write_text("hello")

        resp = client.get("/api/files/browse", params={"path": str(tmp_path)})
        assert resp.status_code == 200
        entries = resp.json()
        names = {e["name"] for e in entries}
        assert "sub" in names
        assert "test.pdf" in names
        assert "test.txt" not in names  # only PDFs and directories

    def test_directory_entry_is_dir(self, client, tmp_path):
        (tmp_path / "sub").mkdir()
        resp = client.get("/api/files/browse", params={"path": str(tmp_path)})
        sub = next(e for e in resp.json() if e["name"] == "sub")
        assert sub["is_dir"] is True

    def test_nonexistent_path(self, client):
        resp = client.get("/api/files/browse", params={"path": "/nonexistent/path"})
        assert resp.status_code == 404

    def test_pdf_page_count(self, client, sample_duplex_pdf):
        resp = client.get("/api/files/info", params={"path": str(sample_duplex_pdf)})
        assert resp.status_code == 200
        assert resp.json()["page_count"] == 20
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_routes/test_files.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement file browser routes**

```python
# app/routes/files.py
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pypdf import PdfReader

from app.schemas import FileEntry

router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("/browse", response_model=list[FileEntry])
def browse_directory(path: str = Query(...)):
    dir_path = Path(path)
    if not dir_path.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if not dir_path.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    entries = []
    for item in sorted(dir_path.iterdir()):
        if item.name.startswith("."):
            continue
        if item.is_dir():
            entries.append(FileEntry(name=item.name, path=str(item), is_dir=True))
        elif item.suffix.lower() == ".pdf":
            entries.append(
                FileEntry(
                    name=item.name,
                    path=str(item),
                    is_dir=False,
                    size=item.stat().st_size,
                )
            )
    return entries


@router.get("/info")
def file_info(path: str = Query(...)):
    file_path = Path(path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if file_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Not a PDF file")

    reader = PdfReader(str(file_path))
    return {
        "name": file_path.name,
        "path": str(file_path),
        "size": file_path.stat().st_size,
        "page_count": len(reader.pages),
    }
```

- [ ] **Step 4: Implement batch import routes**

```python
# app/routes/batch_import.py
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.enums import ImportMethod
from app.models import BatchImport as BatchImportModel
from app.schemas import BatchImportCreate, BatchImportData
from app.services.batch_import import parse_csv, parse_email_text

router = APIRouter(prefix="/api/batch-import", tags=["batch-import"])


@router.post("/parse-email")
def parse_email(body: dict):
    results = parse_email_text(body.get("text", ""))
    return [r.model_dump() for r in results]


@router.post("/parse-csv")
async def parse_csv_upload(file: UploadFile = File(...)):
    import io
    content = (await file.read()).decode("utf-8")
    results = parse_csv(io.StringIO(content))
    return [r.model_dump() for r in results]


@router.post("/save")
def save_batch_imports(data: BatchImportCreate, db: Session = Depends(get_db)):
    records = []
    for item in data.data:
        record = BatchImportModel(
            job_id=data.job_id,
            batch_id=item.batch_id,
            source_filename=item.source_filename,
            expected_letters=item.expected_letters,
            expected_sheets=item.expected_sheets,
            sheets_per_doc=item.sheets_per_doc,
            print_type=item.print_type,
            has_insert=item.has_insert,
            insert_description=item.insert_description,
            import_method=data.import_method,
            raw_text=data.raw_text,
        )
        db.add(record)
        records.append(record)
    db.commit()
    return {"saved": len(records)}
```

- [ ] **Step 5: Register routers in main.py**

Add to `app/main.py`:

```python
from app.routes.files import router as files_router
from app.routes.batch_import import router as batch_import_router

app.include_router(files_router)
app.include_router(batch_import_router)
```

- [ ] **Step 6: Run all tests**

```bash
pytest tests/test_routes/ -v
```

Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add app/routes/files.py app/routes/batch_import.py tests/test_routes/test_files.py app/main.py
git commit -m "feat: file browser and batch import API routes"
```

---

### Task 11: JobService Orchestration Pipeline + Job API

**Files:**
- Create: `app/services/job.py`
- Create: `app/routes/jobs.py`
- Create: `tests/test_integration.py`
- Modify: `app/main.py` (register router)

- [ ] **Step 1: Implement the job orchestration service**

```python
# app/services/job.py
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session

from app.config import settings
from app.enums import FeedDirection, JobStatus, PageFormat, VerificationStatus
from app.models import Job, JobResult, Preset
from app.services.barcode import (
    SheetBarcode,
    generate_barcode_image,
    generate_barcode_string,
)
from app.services.pdf_splitter import split_by_preset, validate_page_count
from app.services.pdf_writer import merge_pdfs, process_document
from app.services.reporter import generate_report
from app.services.sequence import claim_range


def run_job(
    db: Session,
    job: Job,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> JobResult:
    preset: Preset = job.preset
    source = Path(job.source_path)

    def report_progress(current: int, total: int, msg: str = ""):
        if progress_callback:
            progress_callback(current, total, msg)

    validation = validate_page_count(source, preset.sheets_per_doc, preset.page_format)
    if not validation.valid:
        job.status = JobStatus.ERROR
        db.commit()
        raise ValueError(validation.error)

    job.total_doc_sets = validation.doc_sets
    job.status = JobStatus.PROCESSING
    db.commit()

    doc_sets = split_by_preset(source, preset.sheets_per_doc, preset.page_format)

    start_index = (job.last_processed_index or -1) + 1
    doc_sets_to_process = doc_sets[start_index:]

    id_start, _ = claim_range(db, count=len(doc_sets_to_process))

    output_dir = source.parent / f"{job.name}_{job.session_id}_{job.date.isoformat()}"
    machine_dir = output_dir / "machine_ready"
    overflow_dir = output_dir / "manual_overflow"
    machine_dir.mkdir(parents=True, exist_ok=True)
    overflow_dir.mkdir(parents=True, exist_ok=True)

    embed_config = preset.embed_config
    overflow_threshold = settings.overflow_threshold

    total_barcodes = 0
    total_sheets = 0
    overflow_count = 0
    diverts_triggered = 0
    insert_count = 0
    overflow_detail = []
    machine_ready_paths = []

    for i, ds in enumerate(doc_sets_to_process):
        unique_id = id_start + i
        is_overflow = ds.sheet_count > overflow_threshold
        barcodes_for_doc: dict[int, tuple] = {}

        for sheet_idx in range(ds.sheet_count):
            sheet_num = sheet_idx + 1

            if preset.feed_direction == FeedDirection.ASCENDING:
                is_eog = sheet_num == ds.sheet_count
            else:
                is_eog = sheet_num == 1

            divert = None
            if preset.has_divert:
                divert = is_overflow and preset.divert_overflow

            barcode_str = generate_barcode_string(
                unique_id=unique_id,
                sheet_number=sheet_num,
                set_count=ds.sheet_count,
                has_insert=preset.has_insert,
                is_end_of_group=is_eog,
                divert=divert,
            )

            bc_conf = embed_config.get("barcode", {})
            barcode_img = generate_barcode_image(
                barcode_str,
                module_size_mm=bc_conf.get("module_size_mm", 0.50),
                quiet_zone_mm=bc_conf.get("quiet_zone_mm", 6.5),
                dpi=bc_conf.get("dpi", 600),
            )

            page_index = ds.side_a_pages[sheet_idx]
            barcodes_for_doc[page_index] = (barcode_img, barcode_str)

            total_barcodes += 1
            total_sheets += 1
            if preset.has_insert:
                insert_count += 1
            if divert:
                diverts_triggered += 1

        if is_overflow:
            out_subdir = overflow_dir
            overflow_count += 1
            overflow_detail.append({"doc_index": ds.index, "sheets": ds.sheet_count, "unique_id": unique_id})
        else:
            out_subdir = machine_dir

        out_file = out_subdir / f"doc_{ds.index:06d}.pdf"
        process_document(
            input_path=source,
            page_range=(ds.start_page, ds.end_page),
            side_a_barcodes=barcodes_for_doc,
            embed_config=embed_config,
            output_path=out_file,
        )

        if not is_overflow:
            machine_ready_paths.append(out_file)

        job.last_processed_index = start_index + i
        db.commit()
        report_progress(i + 1, len(doc_sets_to_process), f"Processed doc set {ds.index + 1}")

    combined_path = output_dir / "combined_output.pdf"
    if machine_ready_paths:
        merge_pdfs(machine_ready_paths, combined_path)

    imports = [
        {
            "expected_letters": bi.expected_letters,
            "expected_sheets": bi.expected_sheets,
        }
        for bi in job.batch_imports
    ]

    totals = {
        "total_documents": len(doc_sets),
        "total_sheets": total_sheets,
        "total_barcodes": total_barcodes,
        "inserts_triggered": insert_count,
        "diverts_triggered": diverts_triggered,
        "overflow_documents": overflow_count,
    }

    report = generate_report(
        job_info={"name": job.name, "session_id": job.session_id, "date": job.date.isoformat()},
        totals=totals,
        imports=imports,
        overflow_detail=overflow_detail,
    )

    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2))

    verification = VerificationStatus(report["verification"]["verdict"])

    result = JobResult(
        job_id=job.id,
        total_barcodes=total_barcodes,
        total_documents=len(doc_sets),
        total_sheets=total_sheets,
        overflow_docs=overflow_count,
        diverts_triggered=diverts_triggered,
        insert_count=insert_count,
        verification=verification,
        report_path=str(report_path),
        output_dir=str(output_dir),
    )
    db.add(result)

    job.status = JobStatus.COMPLETE
    job.completed_at = datetime.utcnow()
    db.commit()

    return result
```

- [ ] **Step 2: Implement job routes**

```python
# app/routes/jobs.py
import asyncio
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, WebSocket
from sqlalchemy.orm import Session

from app.database import get_db
from app.enums import JobStatus
from app.models import Job
from app.schemas import JobCreate, JobResponse
from app.services.job import run_job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("", status_code=201, response_model=JobResponse)
def create_job(data: JobCreate, db: Session = Depends(get_db)):
    job = Job(
        name=data.name,
        session_id=data.session_id,
        date=data.date,
        source_path=data.source_path,
        preset_id=data.preset_id,
        status=JobStatus.DRAFT,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.get("", response_model=list[JobResponse])
def list_jobs(db: Session = Depends(get_db)):
    return db.query(Job).order_by(Job.created_at.desc()).all()


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/{job_id}/run")
def start_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in (JobStatus.DRAFT, JobStatus.PARTIAL):
        raise HTTPException(status_code=400, detail=f"Job cannot be run from status {job.status}")

    try:
        result = run_job(db, job)
        return {
            "status": "complete",
            "verification": result.verification.value,
            "output_dir": result.output_dir,
            "report_path": result.report_path,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{job_id}/report")
def get_report(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job or not job.result:
        raise HTTPException(status_code=404, detail="Report not found")
    report_path = job.result.report_path
    if not report_path:
        raise HTTPException(status_code=404, detail="Report file not found")
    with open(report_path) as f:
        return json.load(f)


@router.websocket("/{job_id}/ws")
async def job_progress(websocket: WebSocket, job_id: int):
    await websocket.accept()
    db = next(get_db())
    job = db.get(Job, job_id)
    if not job:
        await websocket.close(code=4004)
        return

    def on_progress(current: int, total: int, msg: str):
        asyncio.get_event_loop().call_soon_threadsafe(
            asyncio.ensure_future,
            websocket.send_json({"current": current, "total": total, "message": msg}),
        )

    try:
        result = run_job(db, job, progress_callback=on_progress)
        await websocket.send_json({
            "current": result.total_documents,
            "total": result.total_documents,
            "message": "Complete",
            "status": "complete",
            "verification": result.verification.value,
        })
    except Exception as e:
        await websocket.send_json({"status": "error", "message": str(e)})
    finally:
        await websocket.close()
        db.close()
```

- [ ] **Step 3: Register router in main.py**

Add to `app/main.py`:

```python
from app.routes.jobs import router as jobs_router

app.include_router(jobs_router)
```

- [ ] **Step 4: Write integration test**

```python
# tests/test_integration.py
import json
from pathlib import Path

from app.enums import FeedDirection, IdSource, JobStatus, PageFormat
from app.models import BatchImport, Job, Preset
from app.enums import ImportMethod
from app.services.job import run_job


class TestEndToEndPipeline:
    def test_single_sheet_duplex_job(self, db_session, sample_duplex_pdf, tmp_dir):
        preset = Preset(
            name="Test Single Sheet",
            sheets_per_doc=1,
            page_format=PageFormat.DUPLEX,
            has_insert=False,
            has_divert=False,
            divert_overflow=False,
            feed_direction=FeedDirection.ASCENDING,
            id_source=IdSource.SEQUENTIAL,
            embed_config={
                "barcode": {
                    "anchor": "bottom-right",
                    "x_offset_pt": 36,
                    "y_offset_pt": 36,
                    "module_size_mm": 0.50,
                    "quiet_zone_mm": 6.5,
                    "dpi": 600,
                },
                "human_readable": {"enabled": False},
            },
        )
        db_session.add(preset)
        db_session.commit()

        job = Job(
            name="Test Job",
            session_id="TEST-001",
            source_path=str(sample_duplex_pdf),
            preset_id=preset.id,
            status=JobStatus.DRAFT,
        )
        db_session.add(job)
        db_session.commit()

        batch = BatchImport(
            job_id=job.id,
            batch_id="TestBatch",
            expected_letters=10,
            expected_sheets=10,
            import_method=ImportMethod.MANUAL,
        )
        db_session.add(batch)
        db_session.commit()

        result = run_job(db_session, job)

        assert job.status == JobStatus.COMPLETE
        assert result.total_documents == 10
        assert result.total_sheets == 10
        assert result.total_barcodes == 10
        assert result.overflow_docs == 0

        output_dir = Path(result.output_dir)
        assert (output_dir / "machine_ready").exists()
        assert (output_dir / "combined_output.pdf").exists()
        assert (output_dir / "report.json").exists()

        report = json.loads((output_dir / "report.json").read_text())
        assert report["status"] == "OK"
        assert report["verification"]["match"] is True

        machine_files = list((output_dir / "machine_ready").glob("*.pdf"))
        assert len(machine_files) == 10

    def test_multisheet_with_overflow(self, db_session, tmp_dir):
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        pdf_path = tmp_dir / "overflow_test.pdf"
        c = canvas.Canvas(str(pdf_path), pagesize=letter)
        for i in range(84):
            c.drawString(72, 700, f"Page {i + 1}")
            c.showPage()
        c.save()

        preset = Preset(
            name="Test Overflow",
            sheets_per_doc=7,
            page_format=PageFormat.DUPLEX,
            has_insert=False,
            has_divert=True,
            divert_overflow=True,
            feed_direction=FeedDirection.ASCENDING,
            id_source=IdSource.SEQUENTIAL,
            embed_config={
                "barcode": {
                    "anchor": "bottom-right",
                    "x_offset_pt": 36,
                    "y_offset_pt": 36,
                    "module_size_mm": 0.50,
                    "quiet_zone_mm": 6.5,
                    "dpi": 600,
                },
                "human_readable": {"enabled": False},
            },
        )
        db_session.add(preset)
        db_session.commit()

        job = Job(
            name="Overflow Test",
            session_id="TEST-002",
            source_path=str(pdf_path),
            preset_id=preset.id,
            status=JobStatus.DRAFT,
        )
        db_session.add(job)
        db_session.commit()

        result = run_job(db_session, job)

        assert result.total_documents == 6
        assert result.overflow_docs == 6
        assert result.diverts_triggered > 0

        output_dir = Path(result.output_dir)
        overflow_files = list((output_dir / "manual_overflow").glob("*.pdf"))
        assert len(overflow_files) == 6
```

- [ ] **Step 5: Run all tests**

```bash
pytest tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add app/services/job.py app/routes/jobs.py tests/test_integration.py app/main.py
git commit -m "feat: job orchestration pipeline with end-to-end integration test"
```

---

### Task 12: Base Templates + Home Page + Preset UI

**Files:**
- Create: `app/templates/base.html`
- Create: `app/templates/home.html`
- Create: `app/templates/presets/list.html`
- Create: `app/templates/presets/form.html`
- Create: `app/static/css/style.css`
- Create: `app/static/js/app.js`
- Modify: `app/main.py` (add HTML page routes)
- Modify: `app/routes/presets.py` (add HTML routes)

- [ ] **Step 1: Create base.html**

```html
<!-- app/templates/base.html -->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Barcoding App{% endblock %}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
    <link rel="stylesheet" href="/static/css/style.css">
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
</head>
<body>
    <nav class="container">
        <ul>
            <li><strong>Barcoding App</strong></li>
        </ul>
        <ul>
            <li><a href="/">Jobs</a></li>
            <li><a href="/presets">Presets</a></li>
        </ul>
    </nav>
    <main class="container">
        {% block content %}{% endblock %}
    </main>
    <script src="/static/js/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create home.html**

```html
<!-- app/templates/home.html -->
{% extends "base.html" %}
{% block title %}Jobs — Barcoding App{% endblock %}
{% block content %}
<hgroup>
    <h1>Jobs</h1>
    <p>Processing history</p>
</hgroup>
<a href="/jobs/new" role="button">New Job</a>
<table>
    <thead>
        <tr>
            <th>Name</th>
            <th>Session ID</th>
            <th>Date</th>
            <th>Status</th>
            <th>Documents</th>
            <th></th>
        </tr>
    </thead>
    <tbody>
        {% for job in jobs %}
        <tr>
            <td>{{ job.name }}</td>
            <td>{{ job.session_id }}</td>
            <td>{{ job.date }}</td>
            <td>
                {% if job.status.value == "COMPLETE" %}
                <ins>{{ job.status.value }}</ins>
                {% elif job.status.value == "ERROR" %}
                <del>{{ job.status.value }}</del>
                {% else %}
                {{ job.status.value }}
                {% endif %}
            </td>
            <td>{{ job.result.total_documents if job.result else "—" }}</td>
            <td>
                {% if job.result %}
                <a href="/jobs/{{ job.id }}/report">Report</a>
                {% endif %}
                {% if job.status.value in ["DRAFT", "PARTIAL"] %}
                <a href="/jobs/{{ job.id }}/run">Run</a>
                {% endif %}
            </td>
        </tr>
        {% else %}
        <tr><td colspan="6">No jobs yet. Click "New Job" to get started.</td></tr>
        {% endfor %}
    </tbody>
</table>
{% endblock %}
```

- [ ] **Step 3: Create presets/list.html and presets/form.html**

```html
<!-- app/templates/presets/list.html -->
{% extends "base.html" %}
{% block title %}Presets — Barcoding App{% endblock %}
{% block content %}
<hgroup>
    <h1>Presets</h1>
    <p>Saved barcode configurations</p>
</hgroup>
<a href="/presets/new" role="button">New Preset</a>
<div class="grid">
    {% for preset in presets %}
    <article>
        <header>{{ preset.name }}</header>
        <p>{{ preset.sheets_per_doc }} sheet(s), {{ preset.page_format.value }}, {{ preset.feed_direction.value }}</p>
        <p>Insert: {{ "Yes" if preset.has_insert else "No" }} | Divert: {{ "Yes" if preset.has_divert else "No" }}</p>
        <footer>
            <a href="/presets/{{ preset.id }}/edit">Edit</a>
            <a href="#" hx-delete="/api/presets/{{ preset.id }}" hx-confirm="Delete this preset?" hx-target="closest article" hx-swap="outerHTML">Delete</a>
        </footer>
    </article>
    {% else %}
    <p>No presets yet. Create one to get started.</p>
    {% endfor %}
</div>
{% endblock %}
```

```html
<!-- app/templates/presets/form.html -->
{% extends "base.html" %}
{% block title %}{{ "Edit" if preset else "New" }} Preset — Barcoding App{% endblock %}
{% block content %}
<h1>{{ "Edit" if preset else "New" }} Preset</h1>
<form method="post" action="/presets{{ '/' ~ preset.id if preset else '' }}">
    <label for="name">Name
        <input type="text" id="name" name="name" value="{{ preset.name if preset else '' }}" required>
    </label>
    <label for="sheets_per_doc">Sheets per Document
        <input type="number" id="sheets_per_doc" name="sheets_per_doc" min="1" max="9" value="{{ preset.sheets_per_doc if preset else 1 }}" required>
    </label>
    <fieldset>
        <legend>Page Format</legend>
        <label><input type="radio" name="page_format" value="DUPLEX" {{ 'checked' if not preset or preset.page_format.value == 'DUPLEX' }}> Duplex</label>
        <label><input type="radio" name="page_format" value="SIMPLEX" {{ 'checked' if preset and preset.page_format.value == 'SIMPLEX' }}> Simplex</label>
    </fieldset>
    <fieldset>
        <legend>Feed Direction</legend>
        <label><input type="radio" name="feed_direction" value="ASCENDING" {{ 'checked' if not preset or preset.feed_direction.value == 'ASCENDING' }}> Ascending (first-to-last)</label>
        <label><input type="radio" name="feed_direction" value="DESCENDING" {{ 'checked' if preset and preset.feed_direction.value == 'DESCENDING' }}> Descending (last-to-first)</label>
    </fieldset>
    <label><input type="checkbox" name="has_insert" {{ 'checked' if preset and preset.has_insert }}> Additional insert</label>
    <label><input type="checkbox" name="has_divert" {{ 'checked' if preset and preset.has_divert }}> Enable divert character (14-char barcode)</label>
    <label><input type="checkbox" name="divert_overflow" {{ 'checked' if preset and preset.divert_overflow }}> Auto-divert overflow documents</label>
    <details>
        <summary>Barcode Placement</summary>
        <label for="bc_anchor">Barcode Anchor
            <select id="bc_anchor" name="bc_anchor">
                <option value="bottom-right" {{ 'selected' if not preset or preset.embed_config.get('barcode', {}).get('anchor') == 'bottom-right' }}>Bottom Right</option>
                <option value="bottom-left" {{ 'selected' if preset and preset.embed_config.get('barcode', {}).get('anchor') == 'bottom-left' }}>Bottom Left</option>
                <option value="top-right" {{ 'selected' if preset and preset.embed_config.get('barcode', {}).get('anchor') == 'top-right' }}>Top Right</option>
                <option value="top-left" {{ 'selected' if preset and preset.embed_config.get('barcode', {}).get('anchor') == 'top-left' }}>Top Left</option>
            </select>
        </label>
        <label for="bc_x_offset">X Offset (pt) <input type="number" id="bc_x_offset" name="bc_x_offset" value="{{ preset.embed_config.get('barcode', {}).get('x_offset_pt', 36) if preset else 36 }}"></label>
        <label for="bc_y_offset">Y Offset (pt) <input type="number" id="bc_y_offset" name="bc_y_offset" value="{{ preset.embed_config.get('barcode', {}).get('y_offset_pt', 36) if preset else 36 }}"></label>
        <label><input type="checkbox" name="hr_enabled" {{ 'checked' if not preset or preset.embed_config.get('human_readable', {}).get('enabled', True) }}> Show human-readable text</label>
    </details>
    <button type="submit">{{ "Update" if preset else "Create" }} Preset</button>
</form>
{% endblock %}
```

- [ ] **Step 4: Create static files**

```css
/* app/static/css/style.css */
[data-status="COMPLETE"] { color: var(--pico-ins-color); }
[data-status="ERROR"] { color: var(--pico-del-color); }
[data-status="PARTIAL"] { color: var(--pico-mark-background-color); }

.wizard-steps { display: flex; gap: 1rem; margin-bottom: 2rem; }
.wizard-steps .step { padding: 0.5rem 1rem; border-radius: var(--pico-border-radius); background: var(--pico-muted-border-color); }
.wizard-steps .step.active { background: var(--pico-primary); color: var(--pico-primary-inverse); }
.wizard-steps .step.done { background: var(--pico-ins-color); color: white; }

.file-browser { max-height: 400px; overflow-y: auto; border: 1px solid var(--pico-muted-border-color); border-radius: var(--pico-border-radius); padding: 0.5rem; }
.file-browser .entry { padding: 0.25rem 0.5rem; cursor: pointer; display: flex; align-items: center; gap: 0.5rem; }
.file-browser .entry:hover { background: var(--pico-muted-border-color); }

.progress-bar { width: 100%; height: 1.5rem; background: var(--pico-muted-border-color); border-radius: var(--pico-border-radius); overflow: hidden; }
.progress-bar .fill { height: 100%; background: var(--pico-primary); transition: width 0.3s; }
```

```javascript
// app/static/js/app.js
document.addEventListener("DOMContentLoaded", function() {
    document.body.addEventListener("htmx:afterSwap", function(evt) {
        if (evt.detail.target.id === "wizard-content") {
            updateWizardSteps();
        }
    });
});

function updateWizardSteps() {
    var active = document.querySelector("[data-wizard-step]");
    if (!active) return;
    var step = parseInt(active.dataset.wizardStep);
    document.querySelectorAll(".wizard-steps .step").forEach(function(el) {
        var s = parseInt(el.dataset.step);
        el.classList.toggle("active", s === step);
        el.classList.toggle("done", s < step);
    });
}

function connectJobWebSocket(jobId) {
    var ws = new WebSocket("ws://" + window.location.host + "/api/jobs/" + jobId + "/ws");
    var bar = document.getElementById("progress-fill");
    var msg = document.getElementById("progress-message");

    ws.onmessage = function(event) {
        var data = JSON.parse(event.data);
        if (bar && data.total > 0) {
            bar.style.width = Math.round((data.current / data.total) * 100) + "%";
        }
        if (msg) {
            msg.textContent = data.message || "";
        }
        if (data.status === "complete") {
            window.location.href = "/jobs/" + jobId + "/report";
        }
        if (data.status === "error") {
            if (msg) msg.textContent = "Error: " + data.message;
        }
    };
}
```

- [ ] **Step 5: Add HTML page routes to main.py**

Add to `app/main.py`:

```python
from fastapi import Depends, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Job


@app.get("/")
def home_page(request: Request, db: Session = Depends(get_db)):
    jobs = db.query(Job).order_by(Job.created_at.desc()).all()
    return templates.TemplateResponse("home.html", {"request": request, "jobs": jobs})
```

- [ ] **Step 6: Add HTML preset routes**

Add to `app/routes/presets.py`:

```python
from fastapi import Request, Form
from fastapi.responses import RedirectResponse
from app.main import templates
from app.models import DEFAULT_EMBED_CONFIG


@router.get("/ui/list")
def presets_page(request: Request, db: Session = Depends(get_db)):
    presets = db.query(Preset).order_by(Preset.name).all()
    return templates.TemplateResponse("presets/list.html", {"request": request, "presets": presets})


@router.get("/ui/new")
def new_preset_page(request: Request):
    return templates.TemplateResponse("presets/form.html", {"request": request, "preset": None})


@router.get("/ui/{preset_id}/edit")
def edit_preset_page(request: Request, preset_id: int, db: Session = Depends(get_db)):
    preset = db.get(Preset, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    return templates.TemplateResponse("presets/form.html", {"request": request, "preset": preset})
```

Note: The HTML preset page routes will be mounted at `/presets/...` by updating the prefix or adding a separate router. The clean approach is to add page-level routes in `main.py`:

```python
# Add to app/main.py
from app.models import Preset


@app.get("/presets")
def presets_page(request: Request, db: Session = Depends(get_db)):
    presets = db.query(Preset).order_by(Preset.name).all()
    return templates.TemplateResponse("presets/list.html", {"request": request, "presets": presets})


@app.get("/presets/new")
def new_preset_page(request: Request):
    return templates.TemplateResponse("presets/form.html", {"request": request, "preset": None})


@app.get("/presets/{preset_id}/edit")
def edit_preset_page(request: Request, preset_id: int, db: Session = Depends(get_db)):
    preset = db.get(Preset, preset_id)
    if not preset:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse("presets/form.html", {"request": request, "preset": preset})


@app.post("/presets")
def create_preset_form(
    request: Request,
    name: str = Form(...),
    sheets_per_doc: int = Form(...),
    page_format: str = Form("DUPLEX"),
    feed_direction: str = Form("ASCENDING"),
    has_insert: bool = Form(False),
    has_divert: bool = Form(False),
    divert_overflow: bool = Form(False),
    bc_anchor: str = Form("bottom-right"),
    bc_x_offset: float = Form(36),
    bc_y_offset: float = Form(36),
    hr_enabled: bool = Form(True),
    db: Session = Depends(get_db),
):
    embed_config = {
        "barcode": {
            "anchor": bc_anchor,
            "x_offset_pt": bc_x_offset,
            "y_offset_pt": bc_y_offset,
            "module_size_mm": 0.50,
            "quiet_zone_mm": 6.5,
            "dpi": 600,
        },
        "human_readable": {
            "enabled": hr_enabled,
            "anchor": "bottom-left",
            "x_offset_pt": 36,
            "y_offset_pt": 36,
            "rotation": 90,
            "font_name": "Courier",
            "font_size": 8,
        },
    }
    preset = Preset(
        name=name,
        sheets_per_doc=sheets_per_doc,
        page_format=PageFormat(page_format),
        feed_direction=FeedDirection(feed_direction),
        has_insert=has_insert,
        has_divert=has_divert,
        divert_overflow=divert_overflow,
        id_source=IdSource.SEQUENTIAL,
        embed_config=embed_config,
    )
    db.add(preset)
    db.commit()
    return RedirectResponse("/presets", status_code=303)


@app.post("/presets/{preset_id}")
def update_preset_form(
    preset_id: int,
    name: str = Form(...),
    sheets_per_doc: int = Form(...),
    page_format: str = Form("DUPLEX"),
    feed_direction: str = Form("ASCENDING"),
    has_insert: bool = Form(False),
    has_divert: bool = Form(False),
    divert_overflow: bool = Form(False),
    bc_anchor: str = Form("bottom-right"),
    bc_x_offset: float = Form(36),
    bc_y_offset: float = Form(36),
    hr_enabled: bool = Form(True),
    db: Session = Depends(get_db),
):
    preset = db.get(Preset, preset_id)
    if not preset:
        raise HTTPException(status_code=404)
    preset.name = name
    preset.sheets_per_doc = sheets_per_doc
    preset.page_format = PageFormat(page_format)
    preset.feed_direction = FeedDirection(feed_direction)
    preset.has_insert = has_insert
    preset.has_divert = has_divert
    preset.divert_overflow = divert_overflow
    preset.embed_config = {
        "barcode": {
            "anchor": bc_anchor,
            "x_offset_pt": bc_x_offset,
            "y_offset_pt": bc_y_offset,
            "module_size_mm": 0.50,
            "quiet_zone_mm": 6.5,
            "dpi": 600,
        },
        "human_readable": {
            "enabled": hr_enabled,
            "anchor": "bottom-left",
            "x_offset_pt": 36,
            "y_offset_pt": 36,
            "rotation": 90,
            "font_name": "Courier",
            "font_size": 8,
        },
    }
    db.commit()
    return RedirectResponse("/presets", status_code=303)
```

- [ ] **Step 7: Start the dev server and verify pages load**

```bash
cd /Volumes/NVME4TB/Users/joeldavidson/projects/barcoding-app
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/` — home page with job list should render.
Open `http://127.0.0.1:8000/presets` — preset list should render.
Open `http://127.0.0.1:8000/presets/new` — preset form should render.

- [ ] **Step 8: Commit**

```bash
git add app/templates/ app/static/ app/main.py
git commit -m "feat: base templates, home page, and preset management UI"
```

---

### Task 13: Job Wizard UI

**Files:**
- Create: `app/templates/wizard/layout.html`
- Create: `app/templates/wizard/step1_name.html`
- Create: `app/templates/wizard/step2_batch.html`
- Create: `app/templates/wizard/step3_source.html`
- Create: `app/templates/wizard/step4_preset.html`
- Create: `app/templates/wizard/step5_review.html`
- Create: `app/templates/partials/file_browser.html`
- Create: `app/templates/partials/batch_preview.html`
- Create: `app/templates/partials/progress.html`
- Modify: `app/main.py` (add wizard routes)

- [ ] **Step 1: Create wizard layout**

```html
<!-- app/templates/wizard/layout.html -->
{% extends "base.html" %}
{% block title %}New Job — Barcoding App{% endblock %}
{% block content %}
<h1>New Job</h1>
<div class="wizard-steps">
    <span class="step active" data-step="1">1. Name</span>
    <span class="step" data-step="2">2. Batch Data</span>
    <span class="step" data-step="3">3. Source PDF</span>
    <span class="step" data-step="4">4. Preset</span>
    <span class="step" data-step="5">5. Review</span>
</div>
<div id="wizard-content">
    {% block wizard_step %}{% endblock %}
</div>
{% endblock %}
```

- [ ] **Step 2: Create step 1 — Name & Date**

```html
<!-- app/templates/wizard/step1_name.html -->
{% extends "wizard/layout.html" %}
{% block wizard_step %}
<div data-wizard-step="1">
    <h2>Job Name & Date</h2>
    <form hx-post="/jobs/wizard/step2" hx-target="#wizard-content" hx-swap="innerHTML">
        <label for="name">Job Name
            <input type="text" id="name" name="name" placeholder="Daily Letters" required>
        </label>
        <label for="session_id">Session ID
            <input type="text" id="session_id" name="session_id" placeholder="20260519-001" required>
        </label>
        <label for="date">Date
            <input type="date" id="date" name="date" value="{{ today }}">
        </label>
        <button type="submit">Next</button>
    </form>
</div>
{% endblock %}
```

- [ ] **Step 3: Create step 2 — Batch Data Import**

```html
<!-- app/templates/wizard/step2_batch.html -->
<div data-wizard-step="2">
    <h2>Import Batch Data</h2>
    <input type="hidden" id="wiz-name" value="{{ name }}">
    <input type="hidden" id="wiz-session-id" value="{{ session_id }}">
    <input type="hidden" id="wiz-date" value="{{ date }}">

    <details open>
        <summary>Paste Email Text</summary>
        <form hx-post="/api/batch-import/parse-email" hx-target="#batch-preview" hx-swap="innerHTML"
              hx-headers='{"Content-Type": "application/json"}'
              hx-vals='js:{text: document.getElementById("email-text").value}'
              hx-ext="json-enc">
            <textarea id="email-text" name="text" rows="5" placeholder="Paste email lines here..."></textarea>
            <button type="submit" class="secondary">Parse</button>
        </form>
    </details>

    <details>
        <summary>Upload CSV</summary>
        <form hx-post="/api/batch-import/parse-csv" hx-target="#batch-preview" hx-swap="innerHTML" hx-encoding="multipart/form-data">
            <input type="file" name="file" accept=".csv">
            <button type="submit" class="secondary">Parse CSV</button>
        </form>
    </details>

    <details>
        <summary>Manual Entry</summary>
        <form id="manual-form">
            <label>Batch ID <input type="text" name="batch_id" required></label>
            <label>Expected Letters <input type="number" name="expected_letters" required></label>
            <label>Expected Sheets <input type="number" name="expected_sheets" required></label>
            <label>Sheets per Doc <input type="number" name="sheets_per_doc"></label>
            <label>Print Type <input type="text" name="print_type" placeholder="Double sided color"></label>
            <label><input type="checkbox" name="has_insert"> Has Insert</label>
            <button type="button" onclick="addManualEntry()">Add Entry</button>
        </form>
    </details>

    <h3>Parsed Data</h3>
    <div id="batch-preview">
        <p>No batch data imported yet.</p>
    </div>

    <form hx-post="/jobs/wizard/step3" hx-target="#wizard-content" hx-swap="innerHTML">
        <input type="hidden" name="name" value="{{ name }}">
        <input type="hidden" name="session_id" value="{{ session_id }}">
        <input type="hidden" name="date" value="{{ date }}">
        <input type="hidden" id="batch-data-json" name="batch_data" value="[]">
        <button type="submit">Next</button>
    </form>
</div>
```

- [ ] **Step 4: Create step 3 — Source PDF Selection**

```html
<!-- app/templates/wizard/step3_source.html -->
<div data-wizard-step="3">
    <h2>Select Source PDF</h2>
    <input type="hidden" id="wiz-name" value="{{ name }}">
    <input type="hidden" id="wiz-session-id" value="{{ session_id }}">
    <input type="hidden" id="wiz-date" value="{{ date }}">
    <input type="hidden" id="wiz-batch-data" value="{{ batch_data }}">

    <label for="browse-path">Directory Path
        <input type="text" id="browse-path" value="{{ default_path or '' }}" placeholder="/path/to/documents">
        <button type="button" class="secondary" hx-get="/api/files/browse" hx-target="#file-list" hx-swap="innerHTML"
                hx-include="#browse-path" hx-vals='js:{"path": document.getElementById("browse-path").value}'>Browse</button>
    </label>

    <div id="file-list" class="file-browser">
        <p>Enter a directory path and click Browse.</p>
    </div>

    <p id="selected-file-info"></p>

    <form hx-post="/jobs/wizard/step4" hx-target="#wizard-content" hx-swap="innerHTML">
        <input type="hidden" name="name" value="{{ name }}">
        <input type="hidden" name="session_id" value="{{ session_id }}">
        <input type="hidden" name="date" value="{{ date }}">
        <input type="hidden" name="batch_data" value="{{ batch_data }}">
        <input type="hidden" id="source-path" name="source_path" value="">
        <button type="submit" id="btn-next-source" disabled>Next</button>
    </form>
</div>
```

- [ ] **Step 5: Create partials for file browser**

```html
<!-- app/templates/partials/file_browser.html -->
{% if parent_path %}
<div class="entry" onclick="browseTo('{{ parent_path }}')">..</div>
{% endif %}
{% for entry in entries %}
{% if entry.is_dir %}
<div class="entry" onclick="browseTo('{{ entry.path }}')">📁 {{ entry.name }}</div>
{% else %}
<div class="entry" onclick="selectPdf('{{ entry.path }}', {{ entry.page_count or 0 }})">📄 {{ entry.name }}{% if entry.page_count %} ({{ entry.page_count }} pages){% endif %}</div>
{% endif %}
{% endfor %}
```

```html
<!-- app/templates/partials/batch_preview.html -->
<table>
    <thead>
        <tr><th>Batch ID</th><th>Letters</th><th>Sheets</th><th>Sheets/Doc</th><th>Print Type</th><th>Insert</th></tr>
    </thead>
    <tbody>
        {% for item in items %}
        <tr>
            <td>{{ item.batch_id }}</td>
            <td>{{ item.expected_letters }}</td>
            <td>{{ item.expected_sheets }}</td>
            <td>{{ item.sheets_per_doc or "—" }}</td>
            <td>{{ item.print_type or "—" }}</td>
            <td>{{ "Yes" if item.has_insert else "No" }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
```

```html
<!-- app/templates/partials/progress.html -->
<div data-wizard-step="5">
    <h2>Processing...</h2>
    <div class="progress-bar">
        <div class="fill" id="progress-fill" style="width: 0%"></div>
    </div>
    <p id="progress-message">Starting...</p>
    <script>connectJobWebSocket({{ job_id }});</script>
</div>
```

- [ ] **Step 6: Create step 4 — Preset Selection**

```html
<!-- app/templates/wizard/step4_preset.html -->
<div data-wizard-step="4">
    <h2>Select Preset</h2>
    <form hx-post="/jobs/wizard/step5" hx-target="#wizard-content" hx-swap="innerHTML">
        <input type="hidden" name="name" value="{{ name }}">
        <input type="hidden" name="session_id" value="{{ session_id }}">
        <input type="hidden" name="date" value="{{ date }}">
        <input type="hidden" name="batch_data" value="{{ batch_data }}">
        <input type="hidden" name="source_path" value="{{ source_path }}">

        {% if presets %}
        <fieldset>
            {% for preset in presets %}
            <label>
                <input type="radio" name="preset_id" value="{{ preset.id }}" {{ 'checked' if loop.first }}>
                <strong>{{ preset.name }}</strong> — {{ preset.sheets_per_doc }} sheet(s), {{ preset.page_format.value }}, {{ preset.feed_direction.value }}
                {% if preset.has_insert %} + Insert{% endif %}
                {% if preset.has_divert %} + Divert{% endif %}
            </label>
            {% endfor %}
        </fieldset>
        {% else %}
        <p>No presets found. <a href="/presets/new" target="_blank">Create one</a> first, then refresh this page.</p>
        {% endif %}

        <button type="submit" {{ 'disabled' if not presets }}>Next</button>
    </form>
</div>
```

- [ ] **Step 7: Create step 5 — Review & Run**

```html
<!-- app/templates/wizard/step5_review.html -->
<div data-wizard-step="5">
    <h2>Review & Run</h2>
    <table>
        <tr><th>Job Name</th><td>{{ name }}</td></tr>
        <tr><th>Session ID</th><td>{{ session_id }}</td></tr>
        <tr><th>Date</th><td>{{ date }}</td></tr>
        <tr><th>Source PDF</th><td>{{ source_path }} ({{ page_count }} pages)</td></tr>
        <tr><th>Preset</th><td>{{ preset.name }} — {{ preset.sheets_per_doc }} sheet(s), {{ preset.page_format.value }}</td></tr>
        <tr><th>Expected Doc Sets</th><td>{{ expected_doc_sets }}</td></tr>
        <tr><th>Batch Data</th><td>{{ batch_count }} import(s)</td></tr>
    </table>

    {% if validation_error %}
    <p role="alert">{{ validation_error }}</p>
    {% else %}
    <form hx-post="/jobs/wizard/run" hx-target="#wizard-content" hx-swap="innerHTML">
        <input type="hidden" name="name" value="{{ name }}">
        <input type="hidden" name="session_id" value="{{ session_id }}">
        <input type="hidden" name="date" value="{{ date }}">
        <input type="hidden" name="source_path" value="{{ source_path }}">
        <input type="hidden" name="preset_id" value="{{ preset.id }}">
        <input type="hidden" name="batch_data" value="{{ batch_data_json }}">
        <button type="submit">Run Job</button>
    </form>
    {% endif %}
</div>
```

- [ ] **Step 8: Add wizard routes to main.py**

```python
# Add to app/main.py
from datetime import date as date_type
from fastapi import Form
from fastapi.responses import HTMLResponse
import json

from app.enums import PageFormat, FeedDirection, IdSource, ImportMethod
from app.models import Preset, Job, BatchImport as BatchImportModel
from app.services.pdf_splitter import validate_page_count
from app.services.job import run_job


@app.get("/jobs/new")
def new_job_page(request: Request):
    return templates.TemplateResponse("wizard/step1_name.html", {
        "request": request,
        "today": date_type.today().isoformat(),
    })


@app.post("/jobs/wizard/step2")
def wizard_step2(request: Request, name: str = Form(...), session_id: str = Form(...), date: str = Form(...)):
    return templates.TemplateResponse("wizard/step2_batch.html", {
        "request": request, "name": name, "session_id": session_id, "date": date,
    })


@app.post("/jobs/wizard/step3")
def wizard_step3(request: Request, name: str = Form(...), session_id: str = Form(...), date: str = Form(...), batch_data: str = Form("[]")):
    return templates.TemplateResponse("wizard/step3_source.html", {
        "request": request, "name": name, "session_id": session_id, "date": date,
        "batch_data": batch_data, "default_path": "",
    })


@app.post("/jobs/wizard/step4")
def wizard_step4(request: Request, name: str = Form(...), session_id: str = Form(...), date: str = Form(...),
                 batch_data: str = Form("[]"), source_path: str = Form(...), db: Session = Depends(get_db)):
    presets = db.query(Preset).order_by(Preset.name).all()
    return templates.TemplateResponse("wizard/step4_preset.html", {
        "request": request, "name": name, "session_id": session_id, "date": date,
        "batch_data": batch_data, "source_path": source_path, "presets": presets,
    })


@app.post("/jobs/wizard/step5")
def wizard_step5(request: Request, name: str = Form(...), session_id: str = Form(...), date: str = Form(...),
                 batch_data: str = Form("[]"), source_path: str = Form(...), preset_id: int = Form(...),
                 db: Session = Depends(get_db)):
    preset = db.get(Preset, preset_id)
    from pathlib import Path
    validation = validate_page_count(Path(source_path), preset.sheets_per_doc, preset.page_format)
    from pypdf import PdfReader
    page_count = len(PdfReader(source_path).pages)
    batch_list = json.loads(batch_data) if batch_data != "[]" else []

    return templates.TemplateResponse("wizard/step5_review.html", {
        "request": request, "name": name, "session_id": session_id, "date": date,
        "source_path": source_path, "preset": preset, "page_count": page_count,
        "expected_doc_sets": validation.doc_sets if validation.valid else "N/A",
        "validation_error": validation.error if not validation.valid else None,
        "batch_data_json": batch_data, "batch_count": len(batch_list),
    })


@app.post("/jobs/wizard/run")
def wizard_run(request: Request, name: str = Form(...), session_id: str = Form(...), date: str = Form(...),
               source_path: str = Form(...), preset_id: int = Form(...), batch_data: str = Form("[]"),
               db: Session = Depends(get_db)):
    job = Job(
        name=name, session_id=session_id, date=date_type.fromisoformat(date),
        source_path=source_path, preset_id=preset_id, status=JobStatus.DRAFT,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    batch_list = json.loads(batch_data) if batch_data != "[]" else []
    for item in batch_list:
        record = BatchImportModel(
            job_id=job.id, batch_id=item.get("batch_id", ""),
            expected_letters=item.get("expected_letters", 0),
            expected_sheets=item.get("expected_sheets", 0),
            sheets_per_doc=item.get("sheets_per_doc"),
            print_type=item.get("print_type"),
            has_insert=item.get("has_insert", False),
            insert_description=item.get("insert_description"),
            import_method=ImportMethod.PASTE,
        )
        db.add(record)
    db.commit()

    return templates.TemplateResponse("partials/progress.html", {
        "request": request, "job_id": job.id,
    })
```

- [ ] **Step 9: Start dev server, test the full wizard flow**

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Navigate through: Home -> New Job -> Name -> Batch Data -> Source PDF -> Preset -> Review -> Run.

- [ ] **Step 10: Commit**

```bash
git add app/templates/wizard/ app/templates/partials/ app/main.py app/static/
git commit -m "feat: job wizard UI with 5-step HTMX flow"
```

---

### Task 14: Job Report Page + Final Integration Test

**Files:**
- Create: `app/templates/report.html`
- Modify: `app/main.py` (add report route)
- Modify: `tests/test_integration.py` (add route-level integration test)

- [ ] **Step 1: Create report.html**

```html
<!-- app/templates/report.html -->
{% extends "base.html" %}
{% block title %}Report — {{ job.name }}{% endblock %}
{% block content %}
<hgroup>
    <h1>{{ job.name }}</h1>
    <p>Session: {{ job.session_id }} | Date: {{ job.date }}</p>
</hgroup>

{% if report %}
<article>
    <header>
        {% if report.status == "OK" %}
        <ins>VERIFIED — OK</ins>
        {% else %}
        <del>{{ report.status }}{% if report.verification.details %} — {{ report.verification.details }}{% endif %}</del>
        {% endif %}
    </header>

    <table>
        <tr><th>Documents Processed</th><td>{{ report.totals.documents_processed }}</td></tr>
        <tr><th>Total Sheets</th><td>{{ report.totals.total_sheets }}</td></tr>
        <tr><th>Total Barcodes</th><td>{{ report.totals.total_barcodes }}</td></tr>
        <tr><th>Inserts Triggered</th><td>{{ report.totals.inserts_triggered }}</td></tr>
        <tr><th>Diverts Triggered</th><td>{{ report.totals.diverts_triggered }}</td></tr>
        <tr><th>Overflow Documents</th><td>{{ report.totals.overflow_documents }}</td></tr>
    </table>

    {% if report.verification.expected_letters is not none %}
    <h3>Verification</h3>
    <table>
        <tr><th></th><th>Expected</th><th>Actual</th></tr>
        <tr><td>Documents</td><td>{{ report.verification.expected_letters }}</td><td>{{ report.verification.actual_documents }}</td></tr>
        <tr><td>Sheets</td><td>{{ report.verification.expected_sheets }}</td><td>{{ report.verification.actual_sheets }}</td></tr>
    </table>
    {% endif %}

    {% if report.overflow_detail %}
    <h3>Overflow Documents</h3>
    <table>
        <thead><tr><th>Doc Index</th><th>Sheets</th><th>Unique ID</th></tr></thead>
        <tbody>
            {% for item in report.overflow_detail %}
            <tr><td>{{ item.doc_index }}</td><td>{{ item.sheets }}</td><td>{{ item.unique_id }}</td></tr>
            {% endfor %}
        </tbody>
    </table>
    {% endif %}

    {% if report.warnings %}
    <h3>Warnings</h3>
    <ul>{% for w in report.warnings %}<li>{{ w }}</li>{% endfor %}</ul>
    {% endif %}
</article>

{% if result and result.output_dir %}
<p>Output directory: <code>{{ result.output_dir }}</code></p>
{% endif %}
{% endif %}

<a href="/" role="button" class="secondary">Back to Jobs</a>
{% endblock %}
```

- [ ] **Step 2: Add report page route to main.py**

```python
# Add to app/main.py

@app.get("/jobs/{job_id}/report")
def job_report_page(request: Request, job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404)
    report = None
    if job.result and job.result.report_path:
        from pathlib import Path
        report_file = Path(job.result.report_path)
        if report_file.exists():
            report = json.loads(report_file.read_text())
    return templates.TemplateResponse("report.html", {
        "request": request, "job": job, "report": report, "result": job.result,
    })
```

- [ ] **Step 3: Add route-level integration test**

Add to `tests/test_integration.py`:

```python
class TestRouteIntegration:
    def test_full_wizard_via_api(self, client, sample_duplex_pdf):
        preset_data = {
            "name": "API Test Preset",
            "sheets_per_doc": 1,
            "page_format": "DUPLEX",
            "has_insert": False,
            "has_divert": False,
            "divert_overflow": False,
            "feed_direction": "ASCENDING",
            "id_source": "SEQUENTIAL",
            "embed_config": {
                "barcode": {"anchor": "bottom-right", "x_offset_pt": 36, "y_offset_pt": 36, "module_size_mm": 0.50, "quiet_zone_mm": 6.5, "dpi": 600},
                "human_readable": {"enabled": False},
            },
        }
        preset_resp = client.post("/api/presets", json=preset_data)
        assert preset_resp.status_code == 201
        preset_id = preset_resp.json()["id"]

        job_data = {
            "name": "API Integration Test",
            "session_id": "API-TEST-001",
            "date": "2026-05-19",
            "source_path": str(sample_duplex_pdf),
            "preset_id": preset_id,
        }
        job_resp = client.post("/api/jobs", json=job_data)
        assert job_resp.status_code == 201
        job_id = job_resp.json()["id"]

        run_resp = client.post(f"/api/jobs/{job_id}/run")
        assert run_resp.status_code == 200
        assert run_resp.json()["status"] == "complete"
        assert run_resp.json()["verification"] == "OK"

        report_resp = client.get(f"/api/jobs/{job_id}/report")
        assert report_resp.status_code == 200
        assert report_resp.json()["status"] == "OK"
```

- [ ] **Step 4: Run the full test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: All tests PASS.

- [ ] **Step 5: Start the app and test the complete workflow manually**

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

1. Create a preset at `/presets/new`
2. Start a new job at `/jobs/new`
3. Walk through all 5 wizard steps
4. Verify the report page shows correct data
5. Check the output directory contains `machine_ready/`, `combined_output.pdf`, and `report.json`

- [ ] **Step 6: Commit**

```bash
git add app/templates/report.html app/main.py tests/test_integration.py
git commit -m "feat: job report page and end-to-end route integration test"
```

- [ ] **Step 7: Final commit — tag Phase 1 complete**

```bash
pytest tests/ -v
git tag v0.1.0-phase1
```
