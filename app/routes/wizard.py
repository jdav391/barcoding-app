from datetime import date, date as date_type

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.enums import ImportMethod, JobMode, JobStatus, OutputMode, SessionStatus
from app.models import BatchImport, Job, Preset, Template
from app.models import Session as SessionModel
from app.schemas import WizardState
from app.templating import templates

router = APIRouter(tags=["wizard"])

WIZARD_STEP_TEMPLATES = {
    1: "wizard/step1_name.html",
    2: "wizard/step2_batch.html",
    3: "wizard/step3_source.html",
    4: "wizard/step4_preset.html",
    5: "wizard/step5_review.html",
}


def _make_state(current_step: int, **kwargs) -> WizardState:
    try:
        return WizardState(current_step=current_step, **kwargs)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _save_wizard_state(db, session_id: str, state: WizardState):
    session_obj = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()
    if session_obj and session_obj.status == SessionStatus.DRAFT:
        session_obj.wizard_state = state.model_dump()
        db.commit()


def _build_step_context(step: int, state: WizardState, db) -> dict:
    ctx = {
        "name": state.name,
        "session_id": state.session_id,
        "date": state.date,
        "output_mode": state.output_mode,
        "batch_data": state.batch_data,
        "source_path": state.source_path,
        "source_paths": state.source_paths,
        "mode": state.mode,
        "preset_id": state.preset_id,
        "template_id": state.template_id,
        "preset_assignments": state.preset_assignments,
    }

    if step >= 4:
        ctx["presets"] = db.query(Preset).order_by(Preset.name).all()
        ctx["templates"] = db.query(Template).order_by(Template.name).all()
        paths = [p.model_dump() for p in state.parse_source_paths()]
        ctx["is_multi"] = len(paths) > 1
        ctx["pdf_files"] = paths
        ctx["preset_assignments_dict"] = state.parse_preset_assignments()

    if step >= 5:
        paths = [p.model_dump() for p in state.parse_source_paths()]
        assignments = state.parse_preset_assignments()
        jobs_preview = []
        for p in paths:
            apid = assignments.get(p["path"], state.preset_id)
            preset = db.get(Preset, apid) if state.mode == "PRESET" and apid else None
            tmpl = db.get(Template, state.template_id) if state.mode == "TEMPLATE" and state.template_id else None
            jobs_preview.append({
                "source_path": p["path"],
                "source_name": p["name"],
                "page_count": p.get("page_count"),
                "preset": preset,
                "template": tmpl,
                "preset_id": apid if state.mode == "PRESET" else 0,
                "template_id": state.template_id if state.mode == "TEMPLATE" else 0,
            })
        ctx["jobs_preview"] = jobs_preview

    return ctx


@router.get("/jobs/new")
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


@router.post("/jobs/wizard/step2")
def wizard_step2(
    request: Request,
    name: str = Form(...),
    session_id: str = Form(...),
    date: str = Form(...),
    output_mode: str = Form("COMBINED"),
    db: Session = Depends(get_db),
):
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

    state = _make_state(2, name=name, session_id=session_id, date=date, output_mode=output_mode)
    session_obj.wizard_state = state.model_dump()
    db.commit()

    return templates.TemplateResponse(
        request, "wizard/step2_batch.html",
        {"name": name, "session_id": session_id, "date": date, "output_mode": output_mode},
    )


@router.post("/jobs/wizard/step3")
def wizard_step3(
    request: Request,
    name: str = Form(...),
    session_id: str = Form(...),
    date: str = Form(...),
    batch_data: str = Form("[]"),
    output_mode: str = Form("COMBINED"),
    db: Session = Depends(get_db),
):
    state = _make_state(3, name=name, session_id=session_id, date=date,
                        output_mode=output_mode, batch_data=batch_data)
    _save_wizard_state(db, session_id, state)
    return templates.TemplateResponse(
        request, "wizard/step3_source.html",
        {"name": name, "session_id": session_id, "date": date,
         "batch_data": batch_data, "output_mode": output_mode},
    )


@router.post("/jobs/wizard/step4")
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
    state = _make_state(4, name=name, session_id=session_id, date=date,
                        output_mode=output_mode, batch_data=batch_data,
                        source_path=source_path, source_paths=source_paths or "[]")
    _save_wizard_state(db, session_id, state)

    presets = db.query(Preset).order_by(Preset.name).all()
    templates_list = db.query(Template).order_by(Template.name).all()
    paths = [p.model_dump() for p in state.parse_source_paths()]

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


@router.post("/jobs/wizard/step5")
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
    state = _make_state(5, name=name, session_id=session_id, date=date,
                        output_mode=output_mode, batch_data=batch_data,
                        source_path=source_path, source_paths=source_paths or "[]",
                        mode=mode, preset_id=preset_id, template_id=template_id,
                        preset_assignments=preset_assignments)
    _save_wizard_state(db, session_id, state)

    paths = [p.model_dump() for p in state.parse_source_paths()]
    assignments = state.parse_preset_assignments()

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


@router.post("/jobs/wizard/run")
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
    state = _make_state(5, name=name, session_id=session_id, date=date,
                        output_mode=output_mode, batch_data=batch_data,
                        source_path=source_path, source_paths=source_paths,
                        mode=mode, preset_id=preset_id, template_id=template_id,
                        preset_assignments=preset_assignments)

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

    paths = [p.model_dump() for p in state.parse_source_paths()]
    assignments = state.parse_preset_assignments()
    batch_items = state.parse_batch_data()

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


@router.post("/wizard/{session_id}/goto/{target_step}")
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
    state = _make_state(target_step, name=name, session_id=session_id, date=date,
                        output_mode=output_mode, batch_data=batch_data,
                        source_path=source_path, source_paths=source_paths,
                        mode=mode, preset_id=preset_id, template_id=template_id,
                        preset_assignments=preset_assignments)
    _save_wizard_state(db, session_id, state)
    ctx = _build_step_context(target_step, state, db)
    return templates.TemplateResponse(request, WIZARD_STEP_TEMPLATES[target_step], ctx)


@router.get("/wizard/{session_id}/resume")
def wizard_resume(request: Request, session_id: str, db: Session = Depends(get_db)):
    session_obj = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()
    if not session_obj:
        raise HTTPException(status_code=404)

    raw = session_obj.wizard_state or {
        "current_step": 1, "name": session_obj.name,
        "session_id": session_id, "date": str(session_obj.date),
        "output_mode": session_obj.output_mode.value,
    }
    state = WizardState(**raw)
    step = state.current_step
    ctx = _build_step_context(step, state, db)
    ctx["step_template"] = WIZARD_STEP_TEMPLATES[step]
    return templates.TemplateResponse(request, "wizard/page.html", ctx)


@router.post("/wizard/save-and-exit")
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
    if not session_id or not name:
        return RedirectResponse("/", status_code=303)

    state = _make_state(current_step, name=name, session_id=session_id, date=date,
                        output_mode=output_mode, batch_data=batch_data,
                        source_path=source_path, source_paths=source_paths,
                        mode=mode, preset_id=preset_id, template_id=template_id,
                        preset_assignments=preset_assignments)

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

    session_obj.wizard_state = state.model_dump()
    db.commit()
    return RedirectResponse("/", status_code=303)
