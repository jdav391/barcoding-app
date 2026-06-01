from __future__ import annotations

import json
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy.orm import Session as DBSession

from app.enums import JobStatus
from app.models import Job, Session
from app.services.pdf_writer import merge_pdfs
from app.services.session_report import generate_session_report_pdf


def compile_session(
    db: DBSession,
    session: Session,
    base_output_dir: str,
) -> dict:
    completed_jobs = [j for j in session.jobs if j.status == JobStatus.COMPLETE and j.result]
    all_jobs = list(session.jobs)
    skipped = len(all_jobs) - len(completed_jobs)

    if not completed_jobs:
        raise ValueError("No completed jobs in this session to compile")

    doc_pdfs: list[tuple[int, str, Path]] = []

    for job in completed_jobs:
        machine_dir = Path(job.result.output_dir) / "machine_ready"
        if not machine_dir.exists():
            continue
        for pdf_path in sorted(machine_dir.glob("*.pdf")):
            reader = PdfReader(str(pdf_path))
            page_count = len(reader.pages)
            source_name = Path(job.source_path).stem
            doc_pdfs.append((page_count, source_name, pdf_path))

    doc_pdfs.sort(key=lambda x: (x[0], x[1]))

    total_documents = sum(j.result.total_documents for j in completed_jobs)
    total_sheets = sum(j.result.total_sheets for j in completed_jobs)
    total_barcodes = sum(j.result.total_barcodes for j in completed_jobs)
    overflow_docs = sum(j.result.overflow_docs for j in completed_jobs)

    session_report_data = {
        "session_name": session.name,
        "session_id": session.session_id,
        "date": session.date.isoformat(),
        "jobs": [
            {
                "name": j.name,
                "source_file": Path(j.source_path).name,
                "preset": j.preset.name if j.preset else (j.template.name if j.template else "—"),
                "documents": j.result.total_documents,
                "sheets": j.result.total_sheets,
                "barcodes": j.result.total_barcodes,
                "status": j.status.value,
            }
            for j in completed_jobs
        ],
        "totals": {
            "total_documents": total_documents,
            "total_sheets": total_sheets,
            "total_barcodes": total_barcodes,
            "overflow_documents": overflow_docs,
        },
    }

    output_dir = Path(base_output_dir) / f"session_{session.session_id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    report_pdf_bytes = generate_session_report_pdf(session_report_data)
    report_pdf_path = output_dir / "session_report.pdf"
    report_pdf_path.write_bytes(report_pdf_bytes)

    report_json_path = output_dir / "session_report.json"
    report_json_path.write_text(json.dumps(session_report_data, indent=2))

    sorted_doc_paths = [p for _, _, p in doc_pdfs]
    compiled_path = output_dir / "compiled_output.pdf"
    merge_pdfs(
        [report_pdf_path] + sorted_doc_paths + [report_pdf_path],
        compiled_path,
    )

    session.compiled_output_path = str(compiled_path)
    db.commit()

    status = "ok" if skipped == 0 else "partial"

    return {
        "status": status,
        "compiled_path": str(compiled_path),
        "total_documents": total_documents,
        "total_sheets": total_sheets,
        "total_barcodes": total_barcodes,
        "skipped_jobs": skipped,
    }
