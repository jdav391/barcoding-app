import shutil
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import create_tables, get_db
from app.enums import FeedDirection, IdSource, OutputMode, PageFormat, SessionStatus
from app.models import Job, Preset, Template
from app.models import Session as SessionModel


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    yield


app = FastAPI(title="BrazeBars", lifespan=lifespan)

static_dir = Path(__file__).parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
import os
templates.env.filters["basename"] = lambda p: os.path.basename(p) if p else ""

import json as json_mod

WIZARD_STEP_TEMPLATES = {
    1: "wizard/step1_name.html",
    2: "wizard/step2_batch.html",
    3: "wizard/step3_source.html",
    4: "wizard/step4_preset.html",
    5: "wizard/step5_review.html",
}


def _parse_source_paths(source_paths: str, source_path: str) -> list[dict]:
    if source_paths and source_paths != "[]":
        return json_mod.loads(source_paths)
    if source_path:
        name = source_path.rsplit("/", 1)[-1] if "/" in source_path else source_path
        return [{"path": source_path, "name": name}]
    return []


def _save_wizard_state(db, session_id: str, state: dict):
    session_obj = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()
    if session_obj and session_obj.status == SessionStatus.DRAFT:
        session_obj.wizard_state = state
        db.commit()


def _build_step_context(step: int, state: dict, db) -> dict:
    ctx = {
        "name": state.get("name", ""),
        "session_id": state.get("session_id", ""),
        "date": state.get("date", ""),
        "output_mode": state.get("output_mode", "COMBINED"),
        "batch_data": state.get("batch_data", "[]"),
        "source_path": state.get("source_path", ""),
        "source_paths": state.get("source_paths", "[]"),
        "mode": state.get("mode", "PRESET"),
        "preset_id": int(state.get("preset_id", 0) or 0),
        "template_id": int(state.get("template_id", 0) or 0),
        "preset_assignments": state.get("preset_assignments", ""),
    }

    if step >= 4:
        ctx["presets"] = db.query(Preset).order_by(Preset.name).all()
        ctx["templates"] = db.query(Template).order_by(Template.name).all()
        paths = _parse_source_paths(ctx["source_paths"], ctx["source_path"])
        ctx["is_multi"] = len(paths) > 1
        ctx["pdf_files"] = paths
        if ctx["preset_assignments"]:
            ctx["preset_assignments_dict"] = json_mod.loads(ctx["preset_assignments"])
        else:
            ctx["preset_assignments_dict"] = {}

    if step >= 5:
        paths = _parse_source_paths(ctx["source_paths"], ctx["source_path"])
        assignments = ctx.get("preset_assignments_dict", {})
        if not assignments and ctx["preset_assignments"]:
            assignments = json_mod.loads(ctx["preset_assignments"])
        mode = ctx["mode"]
        preset_id = ctx["preset_id"]
        template_id = ctx["template_id"]
        jobs_preview = []
        for p in paths:
            apid = assignments.get(p["path"], preset_id)
            preset = db.get(Preset, apid) if mode == "PRESET" and apid else None
            tmpl = db.get(Template, template_id) if mode == "TEMPLATE" and template_id else None
            jobs_preview.append({
                "source_path": p["path"],
                "source_name": p["name"],
                "page_count": p.get("page_count"),
                "preset": preset,
                "template": tmpl,
                "preset_id": apid if mode == "PRESET" else 0,
                "template_id": template_id if mode == "TEMPLATE" else 0,
            })
        ctx["jobs_preview"] = jobs_preview

    return ctx


from app.routes.presets import router as presets_router
from app.routes.files import router as files_router
from app.routes.batch_import import router as batch_import_router
from app.routes.jobs import router as jobs_router
from app.routes.templates import router as templates_router
from app.routes.sessions import router as sessions_router

app.include_router(presets_router)
app.include_router(files_router)
app.include_router(batch_import_router)
app.include_router(jobs_router)
app.include_router(templates_router)
app.include_router(sessions_router)


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
    has_insert: str = Form("false"),
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
    template = Template(
        name=name,
        description=description or None,
        page_format=PageFormat(page_format),
        feed_direction=FeedDirection(feed_direction),
        has_insert=_form_bool(has_insert),
        embed_config=embed_config,
    )
    db.add(template)
    db.commit()
    db.refresh(template)

    if sample_pdf and sample_pdf.filename:
        upload_dir = Path("static/uploads/templates") / str(template.id)
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


def _form_bool(val: str) -> bool:
    return val.lower() in ("true", "on", "1", "yes")


@app.post("/presets")
def create_preset_form(
    name: str = Form(...),
    sheets_per_doc: int = Form(...),
    page_format: str = Form("DUPLEX"),
    feed_direction: str = Form("ASCENDING"),
    has_insert: str = Form("false"),
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
        has_insert=_form_bool(has_insert),
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
    has_insert: str = Form("false"),
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
    preset = db.get(Preset, preset_id)
    if not preset:
        raise HTTPException(status_code=404)
    preset.name = name
    preset.sheets_per_doc = sheets_per_doc
    preset.page_format = PageFormat(page_format)
    preset.feed_direction = FeedDirection(feed_direction)
    preset.has_insert = _form_bool(has_insert)
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


@app.get("/jobs/new")
def new_job_page(request: Request, db: Session = Depends(get_db)):
    today = date.today()
    today_count = db.query(SessionModel).filter(SessionModel.date == today).count()
    session_id = f"{today.isoformat()}-{today_count + 1:03d}"
    return templates.TemplateResponse(
        request, "wizard/page.html",
        {
            "step_template": "wizard/step1_name.html",
            "name": "", "session_id": session_id,
            "date": today.isoformat(), "output_mode": "COMBINED",
        },
    )


@app.post("/jobs/wizard/step2")
def wizard_step2(
    request: Request,
    name: str = Form(...),
    session_id: str = Form(...),
    date: str = Form(...),
    output_mode: str = Form("COMBINED"),
    db: Session = Depends(get_db),
):
    from datetime import date as date_type
    job_date = date_type.fromisoformat(date)

    session_obj = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()
    if not session_obj:
        session_obj = SessionModel(
            name=name, session_id=session_id, date=job_date,
            output_mode=OutputMode(output_mode), status=SessionStatus.DRAFT,
        )
        db.add(session_obj)
    else:
        session_obj.name = name
        session_obj.output_mode = OutputMode(output_mode)

    session_obj.wizard_state = {
        "current_step": 2, "name": name, "session_id": session_id,
        "date": date, "output_mode": output_mode,
    }
    db.commit()

    return templates.TemplateResponse(
        request, "wizard/step2_batch.html",
        {"name": name, "session_id": session_id, "date": date, "output_mode": output_mode},
    )


@app.post("/jobs/wizard/step3")
def wizard_step3(
    request: Request,
    name: str = Form(...),
    session_id: str = Form(...),
    date: str = Form(...),
    batch_data: str = Form("[]"),
    output_mode: str = Form("COMBINED"),
    db: Session = Depends(get_db),
):
    _save_wizard_state(db, session_id, {
        "current_step": 3, "name": name, "session_id": session_id,
        "date": date, "output_mode": output_mode, "batch_data": batch_data,
    })
    return templates.TemplateResponse(
        request, "wizard/step3_source.html",
        {"name": name, "session_id": session_id, "date": date,
         "batch_data": batch_data, "output_mode": output_mode},
    )


@app.post("/jobs/wizard/step4")
def wizard_step4(
    request: Request,
    name: str = Form(...),
    session_id: str = Form(...),
    date: str = Form(...),
    batch_data: str = Form("[]"),
    source_path: str = Form(""),
    source_paths: str = Form(""),
    output_mode: str = Form("COMBINED"),
    db: Session = Depends(get_db),
):
    _save_wizard_state(db, session_id, {
        "current_step": 4, "name": name, "session_id": session_id,
        "date": date, "output_mode": output_mode, "batch_data": batch_data,
        "source_path": source_path, "source_paths": source_paths or "[]",
    })

    presets = db.query(Preset).order_by(Preset.name).all()
    templates_list = db.query(Template).order_by(Template.name).all()
    paths = _parse_source_paths(source_paths or "[]", source_path)

    return templates.TemplateResponse(
        request, "wizard/step4_preset.html",
        {
            "name": name, "session_id": session_id, "date": date,
            "batch_data": batch_data, "source_path": source_path,
            "source_paths": source_paths or "[]", "output_mode": output_mode,
            "presets": presets, "templates": templates_list,
            "is_multi": len(paths) > 1, "pdf_files": paths,
            "preset_assignments_dict": {},
        },
    )


@app.post("/jobs/wizard/step5")
def wizard_step5(
    request: Request,
    name: str = Form(...),
    session_id: str = Form(...),
    date: str = Form(...),
    batch_data: str = Form("[]"),
    source_path: str = Form(""),
    source_paths: str = Form(""),
    mode: str = Form("PRESET"),
    preset_id: int = Form(0),
    template_id: int = Form(0),
    output_mode: str = Form("COMBINED"),
    preset_assignments: str = Form(""),
    db: Session = Depends(get_db),
):
    _save_wizard_state(db, session_id, {
        "current_step": 5, "name": name, "session_id": session_id,
        "date": date, "output_mode": output_mode, "batch_data": batch_data,
        "source_path": source_path, "source_paths": source_paths or "[]",
        "mode": mode, "preset_id": preset_id, "template_id": template_id,
        "preset_assignments": preset_assignments,
    })

    paths = _parse_source_paths(source_paths or "[]", source_path)
    assignments = json_mod.loads(preset_assignments) if preset_assignments else {}

    jobs_preview = []
    for p in paths:
        assigned_preset_id = assignments.get(p["path"], preset_id)
        preset = db.get(Preset, assigned_preset_id) if mode == "PRESET" and assigned_preset_id else None
        template = db.get(Template, template_id) if mode == "TEMPLATE" and template_id else None
        jobs_preview.append({
            "source_path": p["path"],
            "source_name": p["name"],
            "page_count": p.get("page_count"),
            "preset": preset,
            "template": template,
            "preset_id": assigned_preset_id if mode == "PRESET" else 0,
            "template_id": template_id if mode == "TEMPLATE" else 0,
        })

    return templates.TemplateResponse(
        request, "wizard/step5_review.html",
        {
            "name": name, "session_id": session_id, "date": date,
            "batch_data": batch_data, "source_path": source_path,
            "source_paths": source_paths or "[]", "mode": mode,
            "preset_id": preset_id, "template_id": template_id,
            "output_mode": output_mode, "preset_assignments": preset_assignments,
            "jobs_preview": jobs_preview,
        },
    )


@app.post("/jobs/wizard/run")
def wizard_run(
    request: Request,
    name: str = Form(...),
    session_id: str = Form(...),
    date: str = Form(...),
    batch_data: str = Form("[]"),
    source_path: str = Form(""),
    source_paths: str = Form("[]"),
    mode: str = Form("PRESET"),
    preset_id: int = Form(0),
    template_id: int = Form(0),
    output_mode: str = Form("COMBINED"),
    preset_assignments: str = Form(""),
    db: Session = Depends(get_db),
):
    from app.enums import ImportMethod, JobMode, JobStatus
    from app.models import BatchImport

    from datetime import date as date_type
    job_date = date_type.fromisoformat(date)

    session_obj = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()

    if not session_obj:
        session_obj = SessionModel(
            name=name, session_id=session_id, date=job_date,
            output_mode=OutputMode(output_mode), status=SessionStatus.ACTIVE,
        )
        db.add(session_obj)
        db.commit()
        db.refresh(session_obj)
    else:
        session_obj.status = SessionStatus.ACTIVE
        session_obj.wizard_state = None
        db.commit()

    paths = []
    if source_paths and source_paths != "[]":
        paths = json_mod.loads(source_paths)
    elif source_path:
        paths = [{"path": source_path, "name": source_path.rsplit("/", 1)[-1] if "/" in source_path else source_path}]

    assignments = {}
    if preset_assignments:
        assignments = json_mod.loads(preset_assignments)

    batch_items = json_mod.loads(batch_data)

    job_ids = []
    for p in paths:
        assigned_preset_id = assignments.get(p["path"], preset_id)
        job = Job(
            name=name,
            session_id=session_id,
            session_fk=session_obj.id,
            date=job_date,
            source_path=p["path"],
            mode=JobMode(mode),
            preset_id=assigned_preset_id if mode == "PRESET" else None,
            template_id=template_id if mode == "TEMPLATE" else None,
            status=JobStatus.DRAFT,
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        for item in batch_items:
            bi = BatchImport(
                job_id=job.id,
                batch_id=item.get("batch_id", "manual"),
                expected_letters=item.get("expected_letters", 0),
                expected_sheets=item.get("expected_sheets", 0),
                sheets_per_doc=item.get("sheets_per_doc"),
                print_type=item.get("print_type"),
                has_insert=item.get("has_insert", False),
                insert_description=item.get("insert_description"),
                import_method=ImportMethod.MANUAL,
                raw_text=batch_data,
            )
            db.add(bi)
        db.commit()
        job_ids.append(job.id)

    return templates.TemplateResponse(
        request, "partials/progress.html",
        {
            "job_ids": job_ids,
            "session_id": session_id,
            "output_mode": output_mode,
            "total_jobs": len(job_ids),
        },
    )


@app.post("/wizard/{session_id}/goto/{target_step}")
def wizard_goto_step(
    request: Request,
    session_id: str,
    target_step: int,
    name: str = Form(""),
    date: str = Form(""),
    output_mode: str = Form("COMBINED"),
    batch_data: str = Form("[]"),
    source_path: str = Form(""),
    source_paths: str = Form("[]"),
    mode: str = Form("PRESET"),
    preset_id: int = Form(0),
    template_id: int = Form(0),
    preset_assignments: str = Form(""),
    db: Session = Depends(get_db),
):
    if target_step < 1 or target_step > 5:
        raise HTTPException(status_code=400, detail="Invalid step")

    state = {
        "current_step": target_step, "name": name, "session_id": session_id,
        "date": date, "output_mode": output_mode, "batch_data": batch_data,
        "source_path": source_path, "source_paths": source_paths,
        "mode": mode, "preset_id": preset_id, "template_id": template_id,
        "preset_assignments": preset_assignments,
    }
    _save_wizard_state(db, session_id, state)
    ctx = _build_step_context(target_step, state, db)
    return templates.TemplateResponse(request, WIZARD_STEP_TEMPLATES[target_step], ctx)


@app.get("/wizard/{session_id}/resume")
def wizard_resume(request: Request, session_id: str, db: Session = Depends(get_db)):
    session_obj = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()
    if not session_obj:
        raise HTTPException(status_code=404)

    state = session_obj.wizard_state or {"current_step": 1, "name": session_obj.name,
        "session_id": session_id, "date": str(session_obj.date), "output_mode": session_obj.output_mode.value}
    step = state.get("current_step", 1)
    ctx = _build_step_context(step, state, db)
    ctx["step_template"] = WIZARD_STEP_TEMPLATES[step]
    return templates.TemplateResponse(request, "wizard/page.html", ctx)


@app.post("/wizard/save-and-exit")
def wizard_save_and_exit(
    request: Request,
    current_step: int = Form(1),
    name: str = Form(""),
    session_id: str = Form(""),
    date: str = Form(""),
    output_mode: str = Form("COMBINED"),
    batch_data: str = Form("[]"),
    source_path: str = Form(""),
    source_paths: str = Form("[]"),
    mode: str = Form("PRESET"),
    preset_id: int = Form(0),
    template_id: int = Form(0),
    preset_assignments: str = Form(""),
    db: Session = Depends(get_db),
):
    from datetime import date as date_type

    if not session_id or not name:
        return RedirectResponse("/", status_code=303)

    job_date = date_type.fromisoformat(date) if date else date_type.today()
    session_obj = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()

    if not session_obj:
        session_obj = SessionModel(
            name=name, session_id=session_id, date=job_date,
            output_mode=OutputMode(output_mode), status=SessionStatus.DRAFT,
        )
        db.add(session_obj)

    session_obj.wizard_state = {
        "current_step": current_step, "name": name, "session_id": session_id,
        "date": date, "output_mode": output_mode, "batch_data": batch_data,
        "source_path": source_path, "source_paths": source_paths,
        "mode": mode, "preset_id": preset_id, "template_id": template_id,
        "preset_assignments": preset_assignments,
    }
    db.commit()
    return RedirectResponse("/", status_code=303)


@app.get("/jobs/{job_id}/report")
def job_report_page(request: Request, job_id: int, db: Session = Depends(get_db)):
    import json
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
