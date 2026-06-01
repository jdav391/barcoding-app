import shutil
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.config import settings
from pypdf import PdfReader

from app.schemas import FileEntry

router = APIRouter(prefix="/api/files", tags=["files"])


@router.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")
    upload_dir = Path(settings.uploads_dir) / "source"
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / file.filename
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    reader = PdfReader(str(dest))
    return {
        "path": str(dest.resolve()),
        "name": file.filename,
        "page_count": len(reader.pages),
    }


@router.get("/browse", response_model=list[FileEntry])
def browse_directory(path: str = Query(...)):
    dir_path = Path(path)
    if not dir_path.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if not dir_path.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    entries = []
    for item in sorted(dir_path.iterdir()):
        if item.name.startswith("."):
            continue
        if item.is_dir():
            entries.append(FileEntry(name=item.name, path=str(item), is_dir=True))
        elif item.suffix.lower() == ".pdf":
            entries.append(
                FileEntry(
                    name=item.name,
                    path=str(item),
                    is_dir=False,
                    size=item.stat().st_size,
                )
            )
    return entries


@router.get("/info")
def file_info(path: str = Query(...)):
    file_path = Path(path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if file_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Not a PDF file")

    reader = PdfReader(str(file_path))
    return {
        "name": file_path.name,
        "path": str(file_path),
        "size": file_path.stat().st_size,
        "page_count": len(reader.pages),
    }
