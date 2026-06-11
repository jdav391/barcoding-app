import json
import shutil
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.database import create_tables, get_db
from app.enums import FeedDirection, IdSource, OutputMode, PageFormat, SessionStatus
from app.models import Job, Preset, Template
from app.models import Session as SessionModel
from app.templating import templates


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    watcher = None
    from app.config import settings as app_settings
    if app_settings.watch_enabled:
        from app.services.watcher import Watcher
        watcher = Watcher()
        watcher.start()
    yield
    if watcher:
        watcher.stop()


app = FastAPI(title="Braze Codes", lifespan=lifespan)

static_dir = Path(__file__).parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def _form_bool(val: str) -> bool:
    return val.lower() in ("true", "on", "1", "yes")


from app.routes.presets import router as presets_router
from app.routes.files import router as files_router
from app.routes.batch_import import router as batch_import_router
from app.routes.jobs import router as jobs_router
from app.routes.templates import router as templates_router
from app.routes.sessions import router as sessions_router
from app.routes.wizard import router as wizard_router

app.include_router(presets_router)
app.include_router(files_router)
app.include_router(batch_import_router)
app.include_router(jobs_router)
app.include_router(templates_router)
app.include_router(sessions_router)
app.include_router(wizard_router)


@app.get("/")
def home_page(request: Request, db: Session = Depends(get_db)):
    draft_sessions = db.query(SessionModel).filter(
        SessionModel.status == SessionStatus.DRAFT
    ).order_by(SessionModel.created_at.desc()).all()
    active_sessions = db.query(SessionModel).filter(
        SessionModel.status != SessionStatus.DRAFT
    ).order_by(SessionModel.created_at.desc()).all()
    orphan_jobs = db.query(Job).filter(Job.session_fk.is_(None)).order_by(Job.created_at.desc()).all()
    return templates.TemplateResponse(request, "home.html", {
        "draft_sessions": draft_sessions,
        "sessions": active_sessions,
        "orphan_jobs": orphan_jobs,
    })


@app.get("/sessions/{session_id}")
def session_dashboard(request: Request, session_id: str, db: Session = Depends(get_db)):
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404)

    stats = {
        "total_documents": sum(j.result.total_documents for j in session.jobs if j.result),
        "total_sheets": sum(j.result.total_sheets for j in session.jobs if j.result),
        "total_barcodes": sum(j.result.total_barcodes for j in session.jobs if j.result),
    }
    has_completed = any(j.status.value == "COMPLETE" for j in session.jobs)

    return templates.TemplateResponse(request, "sessions/dashboard.html", {
        "session": session,
        "stats": stats,
        "has_completed": has_completed,
    })


@app.get("/presets")
def presets_page(request: Request, db: Session = Depends(get_db)):
    presets = db.query(Preset).order_by(Preset.name).all()
    return templates.TemplateResponse(request, "presets/list.html", {"presets": presets})


@app.get("/presets/new")
def new_preset_page(request: Request):
    return templates.TemplateResponse(request, "presets/form.html", {"preset": None})


@app.get("/presets/{preset_id}/edit")
def edit_preset_page(request: Request, preset_id: int, db: Session = Depends(get_db)):
    preset = db.get(Preset, preset_id)
    if not preset:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(request, "presets/form.html", {"preset": preset})


# ---------------------------------------------------------------------------
# Template page routes
# ---------------------------------------------------------------------------


@app.get("/templates")
def templates_page(request: Request, db: Session = Depends(get_db)):
    template_list = db.query(Template).order_by(Template.name).all()
    return templates.TemplateResponse(request, "templates/list.html", {"templates": template_list})


@app.get("/templates/new")
def new_template_page(request: Request):
    return templates.TemplateResponse(request, "templates/form.html", {"template": None})


@app.post("/templates")
async def create_template_form(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    page_format: str = Form("DUPLEX"),
    feed_direction: str = Form("ASCENDING"),
    insert_count: int = Form(0),
    input_dir: str = Form(""),
    bc_anchor: str = Form("bottom-right"),
    bc_x_offset: float = Form(36),
    bc_y_offset: float = Form(36),
    sample_pdf: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    embed_config = {
        "barcode": {
            "anchor": bc_anchor,
            "x_offset_pt": bc_x_offset,
            "y_offset_pt": bc_y_offset,
            "module_size_mm": 0.50, "quiet_zone_mm": 6.5, "dpi": 600,
        },
        "human_readable": {
            "enabled": False, "anchor": "bottom-left",
            "x_offset_pt": 36, "y_offset_pt": 36,
            "rotation": 90, "font_name": "Courier", "font_size": 8,
        },
    }
    if not 0 <= insert_count <= 4:
        raise HTTPException(status_code=400, detail="Insert count must be 0-4")
    template = Template(
        name=name,
        description=description or None,
        page_format=PageFormat(page_format),
        feed_direction=FeedDirection(feed_direction),
        has_insert=insert_count > 0,
        insert_count=insert_count,
        input_dir=input_dir.strip() or None,
        embed_config=embed_config,
    )
    db.add(template)
    db.commit()
    db.refresh(template)

    if sample_pdf and sample_pdf.filename:
        from app.config import settings
        upload_dir = Path(settings.uploads_dir) / "templates" / str(template.id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / "sample.pdf"
        with open(file_path, "wb") as f:
            shutil.copyfileobj(sample_pdf.file, f)
        template.sample_pdf_path = str(file_path)
        db.commit()

    return RedirectResponse(f"/templates/{template.id}/edit", status_code=303)


@app.get("/templates/{template_id}/edit")
def edit_template_page(request: Request, template_id: int, db: Session = Depends(get_db)):
    template = db.get(Template, template_id)
    if not template:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(request, "templates/editor.html", {"template": template})


@app.post("/presets")
def create_preset_form(
    name: str = Form(...),
    sheets_per_doc: int = Form(...),
    page_format: str = Form("DUPLEX"),
    feed_direction: str = Form("ASCENDING"),
    insert_count: int = Form(0),
    has_divert: str = Form("false"),
    divert_overflow: str = Form("false"),
    bc_anchor: str = Form("bottom-right"),
    bc_x_offset: float = Form(36),
    bc_y_offset: float = Form(36),
    hr_enabled: str = Form("false"),
    auto_email_enabled: str = Form("false"),
    email_recipients: str = Form(""),
    db: Session = Depends(get_db),
):
    if not 0 <= insert_count <= 4:
        raise HTTPException(status_code=400, detail="Insert count must be 0-4")
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
            "enabled": _form_bool(hr_enabled),
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
        has_insert=insert_count > 0,
        insert_count=insert_count,
        has_divert=_form_bool(has_divert),
        divert_overflow=_form_bool(divert_overflow),
        id_source=IdSource.SEQUENTIAL,
        embed_config=embed_config,
        auto_email_enabled=_form_bool(auto_email_enabled),
        email_recipients=email_recipients.strip() or None,
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
    insert_count: int = Form(0),
    has_divert: str = Form("false"),
    divert_overflow: str = Form("false"),
    bc_anchor: str = Form("bottom-right"),
    bc_x_offset: float = Form(36),
    bc_y_offset: float = Form(36),
    hr_enabled: str = Form("false"),
    auto_email_enabled: str = Form("false"),
    email_recipients: str = Form(""),
    db: Session = Depends(get_db),
):
    if not 0 <= insert_count <= 4:
        raise HTTPException(status_code=400, detail="Insert count must be 0-4")
    preset = db.get(Preset, preset_id)
    if not preset:
        raise HTTPException(status_code=404)
    preset.name = name
    preset.sheets_per_doc = sheets_per_doc
    preset.page_format = PageFormat(page_format)
    preset.feed_direction = FeedDirection(feed_direction)
    preset.has_insert = insert_count > 0
    preset.insert_count = insert_count
    preset.has_divert = _form_bool(has_divert)
    preset.divert_overflow = _form_bool(divert_overflow)
    preset.auto_email_enabled = _form_bool(auto_email_enabled)
    preset.email_recipients = email_recipients.strip() or None
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
            "enabled": _form_bool(hr_enabled),
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


@app.get("/jobs/{job_id}/report")
def job_report_page(request: Request, job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job or not job.result:
        raise HTTPException(status_code=404)
    report = {}
    if job.result.report_path:
        report = json.loads(Path(job.result.report_path).read_text())
    return templates.TemplateResponse(
        request, "report.html",
        {"job": job, "result": job.result, "report": report},
    )
