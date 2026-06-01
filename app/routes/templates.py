import json
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.enums import PageFormat
from app.models import Template, Region
from app.schemas import (
    RegionCreate, RegionResponse,
    TemplateCreate, TemplateResponse,
)
from app.services.detector import detect_from_regions
from app.services.template import (
    create_template, delete_template, get_template, list_templates, update_template,
)

router = APIRouter(prefix="/api/templates", tags=["templates"])


# ---------------------------------------------------------------------------
# Template CRUD
# ---------------------------------------------------------------------------


@router.post("", status_code=201, response_model=TemplateResponse)
def create_template_route(data: TemplateCreate, db: Session = Depends(get_db)):
    template = create_template(db, data.model_dump())
    return template


@router.get("", response_model=list[TemplateResponse])
def list_templates_route(db: Session = Depends(get_db)):
    return list_templates(db)


@router.get("/{template_id}", response_model=TemplateResponse)
def get_template_route(template_id: int, db: Session = Depends(get_db)):
    template = get_template(db, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.put("/{template_id}", response_model=TemplateResponse)
def update_template_route(template_id: int, data: TemplateCreate, db: Session = Depends(get_db)):
    template = update_template(db, template_id, data.model_dump())
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.delete("/{template_id}", status_code=204)
def delete_template_route(template_id: int, db: Session = Depends(get_db)):
    if not delete_template(db, template_id):
        raise HTTPException(status_code=404, detail="Template not found")


# ---------------------------------------------------------------------------
# Region sub-routes
# ---------------------------------------------------------------------------


@router.post("/{template_id}/regions", status_code=201, response_model=RegionResponse)
def create_region(template_id: int, data: RegionCreate, db: Session = Depends(get_db)):
    template = get_template(db, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    region = Region(
        template_id=template_id,
        name=data.name,
        role=data.role,
        page=data.page,
        x=data.x, y=data.y,
        width=data.width, height=data.height,
        match_type=data.match_type,
        match_pattern=data.match_pattern,
        priority=data.priority,
    )
    db.add(region)
    db.commit()
    db.refresh(region)
    return region


@router.put("/{template_id}/regions/{region_id}", response_model=RegionResponse)
def update_region(template_id: int, region_id: int, data: RegionCreate, db: Session = Depends(get_db)):
    region = db.get(Region, region_id)
    if not region or region.template_id != template_id:
        raise HTTPException(status_code=404, detail="Region not found")
    for field in ("name", "role", "page", "x", "y", "width", "height", "match_type", "match_pattern", "priority"):
        setattr(region, field, getattr(data, field))
    db.commit()
    db.refresh(region)
    return region


@router.delete("/{template_id}/regions/{region_id}", status_code=204)
def delete_region(template_id: int, region_id: int, db: Session = Depends(get_db)):
    region = db.get(Region, region_id)
    if not region or region.template_id != template_id:
        raise HTTPException(status_code=404, detail="Region not found")
    db.delete(region)
    db.commit()


# ---------------------------------------------------------------------------
# Save all regions at once (full replace)
# ---------------------------------------------------------------------------


class RegionsSaveRequest(BaseModel):
    regions: list[RegionCreate]


@router.put("/{template_id}/regions", response_model=list[RegionResponse])
def save_regions(template_id: int, data: RegionsSaveRequest, db: Session = Depends(get_db)):
    """Replace all regions for a template with the given list."""
    template = get_template(db, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    # Delete existing regions
    for r in template.regions:
        db.delete(r)
    db.flush()
    # Create new regions
    new_regions = []
    for rd in data.regions:
        region = Region(
            template_id=template_id,
            name=rd.name,
            role=rd.role,
            page=rd.page,
            x=rd.x, y=rd.y,
            width=rd.width, height=rd.height,
            match_type=rd.match_type,
            match_pattern=rd.match_pattern,
            priority=rd.priority,
        )
        db.add(region)
        new_regions.append(region)
    db.commit()
    for r in new_regions:
        db.refresh(r)
    return new_regions


# ---------------------------------------------------------------------------
# Sample PDF upload and serve
# ---------------------------------------------------------------------------


@router.post("/{template_id}/upload-sample")
async def upload_sample(template_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    template = get_template(db, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    upload_dir = Path(settings.uploads_dir) / "templates" / str(template_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / "sample.pdf"
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    template.sample_pdf_path = str(file_path)
    db.commit()
    return {"sample_url": f"/api/templates/{template_id}/sample"}


@router.get("/{template_id}/sample")
def serve_sample(template_id: int, db: Session = Depends(get_db)):
    template = get_template(db, template_id)
    if not template or not template.sample_pdf_path:
        raise HTTPException(status_code=404, detail="Sample PDF not found")
    return FileResponse(template.sample_pdf_path, media_type="application/pdf")


# ---------------------------------------------------------------------------
# Test detection
# ---------------------------------------------------------------------------


class TestDetectRequest(BaseModel):
    page_format: str = "DUPLEX"


@router.post("/{template_id}/test-detect")
def test_detect(
    template_id: int,
    data: TestDetectRequest | None = None,
    debug: bool = False,
    db: Session = Depends(get_db),
):
    """Run detection on the template's sample PDF and return results.

    Set ?debug=true to include per-page extracted text for troubleshooting
    region placement and matching.
    """
    template = get_template(db, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if not template.sample_pdf_path:
        raise HTTPException(status_code=400, detail="No sample PDF uploaded")

    page_format = PageFormat(data.page_format) if data else template.page_format
    regions = template.regions

    result = {
        "docs": [
            {
                "index": d.index,
                "start_page": d.start_page,
                "end_page": d.end_page,
                "sheet_count": d.sheet_count,
                "side_a_pages": d.side_a_pages,
                "unique_id": d.unique_id,
            }
            for d in detect_from_regions(template.sample_pdf_path, regions, page_format)
        ],
    }

    if debug:
        from app.services.detector import RegionTextExtractor, TextMatcher

        import pdfplumber

        extractor = RegionTextExtractor()
        gb_regions = [r for r in regions if r.role.value == "GROUP_BOUNDARY"]
        pc_regions = [r for r in regions if r.role.value == "PAGE_COUNTER"]
        uid_regions = [r for r in regions if r.role.value == "UNIQUE_ID"]

        with pdfplumber.open(template.sample_pdf_path) as pdf:
            total_pages = len(pdf.pages)

        if page_format.value == "DUPLEX":
            side_a_indices = [i for i in range(total_pages) if i % 2 == 0]
        else:
            side_a_indices = list(range(total_pages))

        pages_debug = []
        for page_idx in side_a_indices:
            page_texts = extractor.extract_page_text(
                template.sample_pdf_path, page_idx, regions
            )
            page_info: dict = {
                "page_index": page_idx,
                "page_label": page_idx + 1,
            }

            for r in gb_regions:
                raw = page_texts.get(r.id, "")
                matched = TextMatcher.match(r.match_type, r.match_pattern, raw)
                page_info.setdefault("group_boundary", {})[r.name or str(r.id)] = {
                    "raw": raw,
                    "matched": matched,
                }

            for r in pc_regions:
                raw = page_texts.get(r.id, "")
                matched = TextMatcher.match(r.match_type, r.match_pattern, raw)
                page_info.setdefault("page_counter", {})[r.name or str(r.id)] = {
                    "raw": raw,
                    "matched": matched,
                }

            for r in uid_regions:
                raw = page_texts.get(r.id, "")
                matched = TextMatcher.match(r.match_type, r.match_pattern, raw)
                page_info.setdefault("unique_id", {})[r.name or str(r.id)] = {
                    "raw": raw,
                    "matched": matched,
                }

            pages_debug.append(page_info)

        # Add full-page text dump for the first 4 side-A pages to help
        # diagnose coordinate issues when regions don't capture text.
        full_text_pages = []
        with pdfplumber.open(template.sample_pdf_path) as pdf:
            for page_idx in side_a_indices[:4]:
                page = pdf.pages[page_idx]
                page_h = page.height
                full_text = page.extract_text() or "(no text extracted)"
                # Also get character positions for coordinate debugging
                chars = []
                for ch in page.chars:
                    pdf_x = ch["x0"]
                    pdf_y = page_h - ch["top"]  # convert to PDF coords (y=0 bottom)
                    chars.append({
                        "text": ch["text"],
                        "x": round(pdf_x, 1),
                        "y": round(pdf_y, 1),
                        "size": round(ch.get("height", ch.get("size", 0)), 1),
                    })
                full_text_pages.append({
                    "page_index": page_idx,
                    "page_label": page_idx + 1,
                    "page_height": round(page_h, 1),
                    "char_count": len(chars),
                    "full_text": full_text,
                })

        result["debug"] = {
            "total_pages": total_pages,
            "side_a_pages": side_a_indices,
            "full_text_sample": full_text_pages,
            "pages": pages_debug,
        }

    return result
