from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON, Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import relationship

from app.database import Base
from app.enums import (
    FeedDirection, IdSource, ImportMethod, JobMode, JobStatus, MatchType, OutputMode,
    PageFormat, RegionRole, SessionStatus, VerificationStatus,
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
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class Session(Base):
    __tablename__ = "sessions"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    session_id = Column(String, unique=True, nullable=False)
    date = Column(Date, nullable=False, default=date.today)
    output_mode = Column(SAEnum(OutputMode), nullable=False, default=OutputMode.COMBINED)
    status = Column(SAEnum(SessionStatus), nullable=False, default=SessionStatus.DRAFT)
    wizard_state = Column(JSON, nullable=True)
    compiled_output_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    jobs = relationship("Job", back_populates="session", foreign_keys="Job.session_fk")


class Preset(Base):
    __tablename__ = "presets"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    sheets_per_doc = Column(Integer, nullable=False)
    page_format = Column(SAEnum(PageFormat), nullable=False, default=PageFormat.DUPLEX)
    has_insert = Column(Boolean, nullable=False, default=False)
    has_divert = Column(Boolean, nullable=False, default=False)
    divert_overflow = Column(Boolean, nullable=False, default=False)
    feed_direction = Column(SAEnum(FeedDirection), nullable=False, default=FeedDirection.ASCENDING)
    id_source = Column(SAEnum(IdSource), nullable=False, default=IdSource.SEQUENTIAL)
    embed_config = Column(JSON, nullable=False, default=DEFAULT_EMBED_CONFIG)
    auto_email_enabled = Column(Boolean, nullable=False, default=False)
    email_recipients = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    jobs = relationship("Job", back_populates="preset")


class Template(Base):
    __tablename__ = "templates"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    page_format = Column(SAEnum(PageFormat), nullable=False, default=PageFormat.DUPLEX)
    has_insert = Column(Boolean, nullable=False, default=False)
    feed_direction = Column(SAEnum(FeedDirection), nullable=False, default=FeedDirection.ASCENDING)
    embed_config = Column(JSON, nullable=False, default=DEFAULT_EMBED_CONFIG)
    sample_pdf_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    regions = relationship("Region", back_populates="template", cascade="all, delete-orphan")
    jobs = relationship("Job", back_populates="template")


class Region(Base):
    __tablename__ = "regions"
    id = Column(Integer, primary_key=True)
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=False)
    name = Column(String, nullable=False)
    role = Column(SAEnum(RegionRole), nullable=False)
    page = Column(Integer, nullable=False, default=1)
    x = Column(Float, nullable=False)
    y = Column(Float, nullable=False)
    width = Column(Float, nullable=False)
    height = Column(Float, nullable=False)
    match_type = Column(SAEnum(MatchType), nullable=False, default=MatchType.EXACT)
    match_pattern = Column(String, nullable=True)
    priority = Column(Integer, nullable=False, default=0)
    template = relationship("Template", back_populates="regions")


class Job(Base):
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    session_id = Column(String, nullable=False)
    date = Column(Date, nullable=False, default=date.today)
    source_path = Column(String, nullable=False)
    error_message = Column(String, nullable=True)
    session_fk = Column(Integer, ForeignKey("sessions.id"), nullable=True)
    session = relationship("Session", back_populates="jobs")
    preset_id = Column(Integer, ForeignKey("presets.id"), nullable=True)
    template_id = Column(Integer, ForeignKey("templates.id"), nullable=True)
    mode = Column(SAEnum(JobMode), nullable=False, default=JobMode.PRESET)
    status = Column(SAEnum(JobStatus), nullable=False, default=JobStatus.DRAFT)
    last_processed_index = Column(Integer, nullable=True)
    total_doc_sets = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    completed_at = Column(DateTime, nullable=True)
    preset = relationship("Preset", back_populates="jobs")
    template = relationship("Template", back_populates="jobs")
    result = relationship("JobResult", back_populates="job", uselist=False)
    batch_imports = relationship("BatchImport", back_populates="job")
    mail_pieces = relationship("MailPiece", back_populates="job")


class MailPiece(Base):
    """One row per processed document set — the per-piece accountability record.

    Job totals and the machine-ready merge order are rebuilt from these rows,
    so they stay correct across resumed runs.
    """
    __tablename__ = "mail_pieces"
    __table_args__ = (UniqueConstraint("job_id", "doc_index", name="uq_mailpiece_job_doc"),)
    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    doc_index = Column(Integer, nullable=False)
    unique_id = Column(Integer, nullable=False)
    sheet_count = Column(Integer, nullable=False)
    start_page = Column(Integer, nullable=False)
    end_page = Column(Integer, nullable=False)
    is_overflow = Column(Boolean, nullable=False, default=False)
    has_insert = Column(Boolean, nullable=False, default=False)
    divert = Column(Boolean, nullable=False, default=False)
    barcodes = Column(JSON, nullable=False, default=list)
    output_path = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    job = relationship("Job", back_populates="mail_pieces")


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
    verification = Column(SAEnum(VerificationStatus), nullable=False, default=VerificationStatus.OK)
    report_path = Column(String, nullable=True)
    output_dir = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
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
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    job = relationship("Job", back_populates="batch_imports")
