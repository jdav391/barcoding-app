import io

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import BatchImport as BatchImportModel
from app.schemas import BatchImportCreate
from app.services.batch_import import parse_csv, parse_email_text

router = APIRouter(prefix="/api/batch-import", tags=["batch-import"])


@router.post("/parse-email")
def parse_email(body: dict):
    results = parse_email_text(body.get("text", ""))
    return [r.model_dump() for r in results]


@router.post("/parse-csv")
async def parse_csv_upload(file: UploadFile = File(...)):
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
