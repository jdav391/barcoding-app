from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.models import DEFAULT_EMBED_CONFIG, Template


def get_template(db: Session, template_id: int) -> Template | None:
    return db.get(Template, template_id)


def list_templates(db: Session) -> list[Template]:
    return db.query(Template).order_by(Template.name).all()


def create_template(db: Session, data: dict) -> Template:
    template = Template(
        name=data["name"],
        description=data.get("description"),
        page_format=data.get("page_format", "DUPLEX"),
        has_insert=data.get("has_insert", False),
        insert_count=data.get("insert_count", 0),
        feed_direction=data.get("feed_direction", "ASCENDING"),
        embed_config=data.get("embed_config") or DEFAULT_EMBED_CONFIG,
        input_dir=data.get("input_dir"),
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def update_template(db: Session, template_id: int, data: dict) -> Template | None:
    template = db.get(Template, template_id)
    if not template:
        return None
    for key in ("name", "description", "page_format", "has_insert", "insert_count", "feed_direction", "input_dir"):
        if key in data:
            setattr(template, key, data[key])
    if "embed_config" in data and data["embed_config"] is not None:
        template.embed_config = data["embed_config"]
    db.commit()
    db.refresh(template)
    return template


def delete_template(db: Session, template_id: int) -> bool:
    template = db.get(Template, template_id)
    if not template:
        return False
    # Delete stored sample PDF if exists
    if template.sample_pdf_path:
        sample_path = Path(template.sample_pdf_path)
        if sample_path.exists():
            sample_path.unlink()
    db.delete(template)
    db.commit()
    return True
