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
        auto_email_enabled=data.auto_email_enabled,
        email_recipients=data.email_recipients,
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
