import datetime as dt
import json

from pydantic import BaseModel, Field
from app.enums import (
    FeedDirection, IdSource, ImportMethod, JobMode, JobStatus, MatchType, OutputMode,
    PageFormat, RegionRole, VerificationStatus,
)


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


class RegionCreate(BaseModel):
    name: str
    role: RegionRole
    page: int = 1
    x: float
    y: float
    width: float
    height: float
    match_type: MatchType = MatchType.EXACT
    match_pattern: str | None = None
    priority: int = 0


class RegionResponse(BaseModel):
    id: int
    template_id: int
    name: str
    role: RegionRole
    page: int
    x: float
    y: float
    width: float
    height: float
    match_type: MatchType
    match_pattern: str | None = None
    priority: int
    model_config = {"from_attributes": True}


class TemplateCreate(BaseModel):
    name: str
    description: str | None = None
    page_format: PageFormat = PageFormat.DUPLEX
    has_insert: bool = False
    feed_direction: FeedDirection = FeedDirection.ASCENDING
    embed_config: EmbedConfig = EmbedConfig()


class TemplateResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    page_format: PageFormat
    has_insert: bool
    feed_direction: FeedDirection
    embed_config: dict
    sample_pdf_path: str | None = None
    regions: list[RegionResponse] = []
    created_at: dt.datetime
    updated_at: dt.datetime
    model_config = {"from_attributes": True}


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
    auto_email_enabled: bool = False
    email_recipients: str | None = None


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
    auto_email_enabled: bool
    email_recipients: str | None
    created_at: dt.datetime
    updated_at: dt.datetime
    model_config = {"from_attributes": True}


class JobCreate(BaseModel):
    name: str
    session_id: str
    date: dt.date = Field(default_factory=dt.date.today)
    source_path: str
    preset_id: int | None = None
    template_id: int | None = None
    mode: JobMode = JobMode.PRESET


class JobResponse(BaseModel):
    id: int
    name: str
    session_id: str
    date: dt.date
    source_path: str
    preset_id: int | None
    template_id: int | None = None
    mode: JobMode
    status: JobStatus
    last_processed_index: int | None
    total_doc_sets: int | None
    created_at: dt.datetime
    completed_at: dt.datetime | None
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


class SourceFile(BaseModel):
    path: str
    name: str
    page_count: int | None = None


class WizardState(BaseModel):
    current_step: int = Field(ge=1, le=5)
    name: str = ""
    session_id: str = ""
    date: str = ""
    output_mode: str = "COMBINED"
    batch_data: str = "[]"
    source_path: str = ""
    source_paths: str = "[]"
    mode: str = "PRESET"
    preset_id: int = 0
    template_id: int = 0
    preset_assignments: str = ""

    def parse_batch_data(self) -> list[dict]:
        try:
            return json.loads(self.batch_data)
        except (json.JSONDecodeError, TypeError):
            return []

    def parse_source_paths(self) -> list[SourceFile]:
        if self.source_paths and self.source_paths != "[]":
            try:
                return [SourceFile(**p) for p in json.loads(self.source_paths)]
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        if self.source_path:
            name = self.source_path.rsplit("/", 1)[-1] if "/" in self.source_path else self.source_path
            return [SourceFile(path=self.source_path, name=name)]
        return []

    def parse_preset_assignments(self) -> dict[str, int]:
        if self.preset_assignments:
            try:
                return json.loads(self.preset_assignments)
            except (json.JSONDecodeError, TypeError):
                pass
        return {}


class SessionCreate(BaseModel):
    name: str
    session_id: str
    date: dt.date = Field(default_factory=dt.date.today)
    output_mode: OutputMode = OutputMode.COMBINED


class SessionResponse(BaseModel):
    id: int
    name: str
    session_id: str
    date: dt.date
    output_mode: OutputMode
    compiled_output_path: str | None = None
    created_at: dt.datetime
    model_config = {"from_attributes": True}
