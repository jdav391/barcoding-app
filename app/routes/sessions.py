from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.database import get_db
from app.models import Session
from app.schemas import SessionCreate, SessionResponse
from app.services.session import compile_session

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", status_code=201, response_model=SessionResponse)
def create_session(data: SessionCreate, db: DBSession = Depends(get_db)):
    session = Session(
        name=data.name,
        session_id=data.session_id,
        date=data.date,
        output_mode=data.output_mode,
    )
    db.add(session)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Session ID already exists")
    db.refresh(session)
    return session


@router.get("", response_model=list[SessionResponse])
def list_sessions(db: DBSession = Depends(get_db)):
    return db.query(Session).order_by(Session.created_at.desc()).all()


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(session_id: str, db: DBSession = Depends(get_db)):
    session = db.query(Session).filter(Session.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post("/{session_id}/compile")
def compile_session_route(session_id: str, db: DBSession = Depends(get_db)):
    session = db.query(Session).filter(Session.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    base_dir = str(Path(settings.uploads_dir) / "sessions")
    try:
        result = compile_session(db, session, base_output_dir=base_dir)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result


@router.get("/{session_id}/download")
def download_compiled(session_id: str, db: DBSession = Depends(get_db)):
    session = db.query(Session).filter(Session.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.compiled_output_path:
        raise HTTPException(status_code=404, detail="Session has not been compiled yet")
    compiled_path = Path(session.compiled_output_path)
    if not compiled_path.exists():
        raise HTTPException(status_code=404, detail="Compiled PDF file not found")
    filename = f"{session.name}_{session.session_id}_compiled.pdf"
    return FileResponse(
        path=str(compiled_path),
        media_type="application/pdf",
        filename=filename,
    )
