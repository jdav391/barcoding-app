from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session

from app.config import settings
from app.enums import FeedDirection, JobMode, JobStatus, VerificationStatus
from app.models import Job, JobResult, Preset
from app.services.barcode import generate_barcode_image, generate_barcode_string
from app.services.pdf_splitter import split_by_preset, validate_page_count
from app.services.pdf_writer import merge_pdfs, process_document
from app.services.email import send_report_email
from app.services.report_pdf import generate_report_pdf
from app.services.reporter import generate_report
from app.services.sequence import claim_range


def _run_job_template(
    db: Session,
    job: Job,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> JobResult:
    from app.services.detector import detect_from_regions

    template = job.template
    source = Path(job.source_path)

    def report_progress(current: int, total: int, msg: str = ""):
        if progress_callback:
            progress_callback(current, total, msg)

    # Detect document sets from template regions
    doc_sets = detect_from_regions(source, template.regions, template.page_format)

    if not doc_sets:
        job.status = JobStatus.ERROR
        db.commit()
        raise ValueError("No document sets detected in the source PDF")

    job.total_doc_sets = len(doc_sets)
    job.status = JobStatus.PROCESSING
    db.commit()

    start_index = (job.last_processed_index or -1) + 1
    doc_sets_to_process = doc_sets[start_index:]

    # Assign unique IDs: use detected IDs where available, fall back to sequential
    need_sequential = sum(1 for ds in doc_sets_to_process if ds.unique_id is None)
    id_start = None
    seq_idx = 0
    if need_sequential > 0:
        id_start, _ = claim_range(db, count=need_sequential)

    output_dir = source.parent / f"{job.name}_{job.session_id}_{job.date.isoformat()}"
    machine_dir = output_dir / "machine_ready"
    overflow_dir = output_dir / "manual_overflow"
    machine_dir.mkdir(parents=True, exist_ok=True)
    overflow_dir.mkdir(parents=True, exist_ok=True)

    embed_config = template.embed_config
    overflow_threshold = settings.overflow_threshold

    total_barcodes = 0
    total_sheets = 0
    overflow_count = 0
    diverts_triggered = 0
    insert_count = 0
    overflow_detail = []
    machine_ready_paths = []

    # When resuming a partial job, recover existing machine-ready files
    # from the previous run so the combined output includes everything.
    if start_index > 0:
        for f in sorted(machine_dir.glob("doc_*.pdf")):
            try:
                idx = int(f.stem.split("_")[-1])
                if idx < start_index:
                    machine_ready_paths.append(f)
            except (ValueError, IndexError):
                pass

    for i, ds in enumerate(doc_sets_to_process):
        # Assign unique ID: use detected ID or fall back to sequential
        if ds.unique_id is not None:
            unique_id = ds.unique_id
        else:
            unique_id = id_start + seq_idx
            seq_idx += 1

        is_overflow = ds.sheet_count > overflow_threshold
        barcodes_for_doc: dict[int, tuple] = {}

        for sheet_idx in range(ds.sheet_count):
            sheet_num = sheet_idx + 1

            if template.feed_direction == FeedDirection.ASCENDING:
                is_eog = sheet_num == ds.sheet_count
            else:
                is_eog = sheet_num == 1

            divert = None  # Template mode has no divert support

            barcode_str = generate_barcode_string(
                unique_id=unique_id,
                sheet_number=sheet_num,
                set_count=ds.sheet_count,
                has_insert=template.has_insert,
                is_end_of_group=is_eog,
                divert=divert,
            )

            bc_conf = embed_config.get("barcode", {})
            barcode_img = generate_barcode_image(
                barcode_str,
                module_size_mm=bc_conf.get("module_size_mm", 0.50),
                quiet_zone_mm=bc_conf.get("quiet_zone_mm", 6.5),
                dpi=bc_conf.get("dpi", 600),
            )

            page_index = ds.side_a_pages[sheet_idx]
            barcodes_for_doc[page_index] = (barcode_img, barcode_str)

            total_barcodes += 1
            total_sheets += 1
            if template.has_insert:
                insert_count += 1

        if is_overflow:
            out_subdir = overflow_dir
            overflow_count += 1
            overflow_detail.append({"doc_index": ds.index, "sheets": ds.sheet_count, "unique_id": unique_id})
        else:
            out_subdir = machine_dir

        out_file = out_subdir / f"doc_{ds.index:06d}.pdf"
        process_document(
            input_path=source,
            page_range=(ds.start_page, ds.end_page),
            side_a_barcodes=barcodes_for_doc,
            embed_config=embed_config,
            output_path=out_file,
        )

        if not is_overflow:
            machine_ready_paths.append(out_file)

        job.last_processed_index = start_index + i
        db.commit()
        report_progress(i + 1, len(doc_sets_to_process), f"Processed doc set {ds.index + 1}")

    imports = [
        {
            "expected_letters": bi.expected_letters,
            "expected_sheets": bi.expected_sheets,
        }
        for bi in job.batch_imports
    ]

    totals = {
        "total_documents": len(doc_sets),
        "total_sheets": total_sheets,
        "total_barcodes": total_barcodes,
        "inserts_triggered": insert_count,
        "diverts_triggered": diverts_triggered,
        "overflow_documents": overflow_count,
    }

    report = generate_report(
        job_info={"name": job.name, "session_id": job.session_id, "date": job.date.isoformat()},
        totals=totals,
        imports=imports,
        overflow_detail=overflow_detail,
    )

    report_json_path = output_dir / "report.json"
    report_json_path.write_text(json.dumps(report, indent=2))

    report_pdf_bytes = generate_report_pdf(report)
    report_pdf_path = output_dir / "report.pdf"
    report_pdf_path.write_bytes(report_pdf_bytes)

    combined_path = output_dir / "combined_output.pdf"
    if machine_ready_paths:
        merge_pdfs(
            [report_pdf_path] + machine_ready_paths + [report_pdf_path],
            combined_path,
        )

    verification_data = report.get("verification")
    verification = VerificationStatus(verification_data["verdict"]) if verification_data else VerificationStatus.OK

    result = JobResult(
        job_id=job.id,
        total_barcodes=total_barcodes,
        total_documents=len(doc_sets),
        total_sheets=total_sheets,
        overflow_docs=overflow_count,
        diverts_triggered=diverts_triggered,
        insert_count=insert_count,
        verification=verification,
        report_path=str(report_json_path),
        output_dir=str(output_dir),
    )
    db.add(result)

    job.status = JobStatus.COMPLETE
    job.completed_at = datetime.now(UTC)
    db.commit()

    # Template mode: no auto-email (template has no auto_email config)

    return result


def run_job(
    db: Session,
    job: Job,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> JobResult:
    if job.mode == JobMode.TEMPLATE:
        if not job.template:
            job.status = JobStatus.ERROR
            db.commit()
            raise ValueError("Template mode job has no template assigned")
        return _run_job_template(db, job, progress_callback)
    return _run_job_preset(db, job, progress_callback)


def _run_job_preset(
    db: Session,
    job: Job,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> JobResult:
    preset: Preset = job.preset
    source = Path(job.source_path)

    def report_progress(current: int, total: int, msg: str = ""):
        if progress_callback:
            progress_callback(current, total, msg)

    validation = validate_page_count(source, preset.sheets_per_doc, preset.page_format)
    if not validation.valid:
        job.status = JobStatus.ERROR
        db.commit()
        raise ValueError(validation.error)

    job.total_doc_sets = validation.doc_sets
    job.status = JobStatus.PROCESSING
    db.commit()

    doc_sets = split_by_preset(source, preset.sheets_per_doc, preset.page_format)

    start_index = (job.last_processed_index or -1) + 1
    doc_sets_to_process = doc_sets[start_index:]

    id_start, _ = claim_range(db, count=len(doc_sets_to_process))

    output_dir = source.parent / f"{job.name}_{job.session_id}_{job.date.isoformat()}"
    machine_dir = output_dir / "machine_ready"
    overflow_dir = output_dir / "manual_overflow"
    machine_dir.mkdir(parents=True, exist_ok=True)
    overflow_dir.mkdir(parents=True, exist_ok=True)

    embed_config = preset.embed_config
    overflow_threshold = settings.overflow_threshold

    total_barcodes = 0
    total_sheets = 0
    overflow_count = 0
    diverts_triggered = 0
    insert_count = 0
    overflow_detail = []
    machine_ready_paths = []

    # When resuming a partial job, recover existing machine-ready files
    # from the previous run so the combined output includes everything.
    if start_index > 0:
        for f in sorted(machine_dir.glob("doc_*.pdf")):
            try:
                idx = int(f.stem.split("_")[-1])
                if idx < start_index:
                    machine_ready_paths.append(f)
            except (ValueError, IndexError):
                pass

    for i, ds in enumerate(doc_sets_to_process):
        unique_id = id_start + i
        is_overflow = ds.sheet_count > overflow_threshold
        barcodes_for_doc: dict[int, tuple] = {}

        for sheet_idx in range(ds.sheet_count):
            sheet_num = sheet_idx + 1

            if preset.feed_direction == FeedDirection.ASCENDING:
                is_eog = sheet_num == ds.sheet_count
            else:
                is_eog = sheet_num == 1

            divert = None
            if preset.has_divert:
                divert = is_overflow and preset.divert_overflow

            barcode_str = generate_barcode_string(
                unique_id=unique_id,
                sheet_number=sheet_num,
                set_count=ds.sheet_count,
                has_insert=preset.has_insert,
                is_end_of_group=is_eog,
                divert=divert,
            )

            bc_conf = embed_config.get("barcode", {})
            barcode_img = generate_barcode_image(
                barcode_str,
                module_size_mm=bc_conf.get("module_size_mm", 0.50),
                quiet_zone_mm=bc_conf.get("quiet_zone_mm", 6.5),
                dpi=bc_conf.get("dpi", 600),
            )

            page_index = ds.side_a_pages[sheet_idx]
            barcodes_for_doc[page_index] = (barcode_img, barcode_str)

            total_barcodes += 1
            total_sheets += 1
            if preset.has_insert:
                insert_count += 1
            if divert:
                diverts_triggered += 1

        if is_overflow:
            out_subdir = overflow_dir
            overflow_count += 1
            overflow_detail.append({"doc_index": ds.index, "sheets": ds.sheet_count, "unique_id": unique_id})
        else:
            out_subdir = machine_dir

        out_file = out_subdir / f"doc_{ds.index:06d}.pdf"
        process_document(
            input_path=source,
            page_range=(ds.start_page, ds.end_page),
            side_a_barcodes=barcodes_for_doc,
            embed_config=embed_config,
            output_path=out_file,
        )

        if not is_overflow:
            machine_ready_paths.append(out_file)

        job.last_processed_index = start_index + i
        db.commit()
        report_progress(i + 1, len(doc_sets_to_process), f"Processed doc set {ds.index + 1}")

    imports = [
        {
            "expected_letters": bi.expected_letters,
            "expected_sheets": bi.expected_sheets,
        }
        for bi in job.batch_imports
    ]

    totals = {
        "total_documents": len(doc_sets),
        "total_sheets": total_sheets,
        "total_barcodes": total_barcodes,
        "inserts_triggered": insert_count,
        "diverts_triggered": diverts_triggered,
        "overflow_documents": overflow_count,
    }

    report = generate_report(
        job_info={"name": job.name, "session_id": job.session_id, "date": job.date.isoformat()},
        totals=totals,
        imports=imports,
        overflow_detail=overflow_detail,
    )

    report_json_path = output_dir / "report.json"
    report_json_path.write_text(json.dumps(report, indent=2))

    report_pdf_bytes = generate_report_pdf(report)
    report_pdf_path = output_dir / "report.pdf"
    report_pdf_path.write_bytes(report_pdf_bytes)

    combined_path = output_dir / "combined_output.pdf"
    if machine_ready_paths:
        merge_pdfs(
            [report_pdf_path] + machine_ready_paths + [report_pdf_path],
            combined_path,
        )

    verification_data = report.get("verification")
    verification = VerificationStatus(verification_data["verdict"]) if verification_data else VerificationStatus.OK

    result = JobResult(
        job_id=job.id,
        total_barcodes=total_barcodes,
        total_documents=len(doc_sets),
        total_sheets=total_sheets,
        overflow_docs=overflow_count,
        diverts_triggered=diverts_triggered,
        insert_count=insert_count,
        verification=verification,
        report_path=str(report_json_path),
        output_dir=str(output_dir),
    )
    db.add(result)

    job.status = JobStatus.COMPLETE
    job.completed_at = datetime.now(UTC)
    db.commit()

    if preset.auto_email_enabled and preset.email_recipients:
        recipients = [r.strip() for r in preset.email_recipients.split(",") if r.strip()]
        if recipients:
            is_error = verification != VerificationStatus.OK or overflow_count > 0
            if is_error:
                subject = f"[BrazeBars] [ACTION REQUIRED] {job.name} — {job.session_id} — Errors Detected"
                status_text = "ERRORS DETECTED"
            else:
                subject = f"[BrazeBars] {job.name} — {job.session_id} — Complete"
                status_text = "COMPLETE"

            body = (
                f"Job: {job.name}\n"
                f"Session: {job.session_id}\n"
                f"Date: {job.date.isoformat()}\n"
                f"Status: {status_text}\n\n"
                f"Letters Processed: {len(doc_sets)}\n"
                f"Total Sheets: {total_sheets}\n"
                f"Barcodes Applied: {total_barcodes}\n\n"
                f"See attached report for full details."
            )

            pdf_filename = f"{job.name}_{job.session_id}_report.pdf"
            send_report_email(
                host=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_username,
                password=settings.smtp_password,
                recipients=recipients,
                subject=subject,
                body=body,
                pdf_bytes=report_pdf_bytes,
                pdf_filename=pdf_filename,
            )

    return result
