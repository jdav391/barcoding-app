from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.config import settings
from app.enums import FeedDirection, JobMode, JobStatus, VerificationStatus
from app.models import Job, JobResult, MailPiece, Preset
from app.services.barcode import (
    MAX_SET_COUNT,
    generate_barcode_string,
    validate_barcode_string,
)
from app.services.clear_zone import find_clear_zone_violations
from app.services.pdf_splitter import split_by_preset, validate_page_count
from app.services.pdf_writer import merge_pdfs, process_document
from app.services.email import send_report_email
from app.services.report_pdf import generate_report_pdf
from app.services.reporter import generate_report
from app.services.sequence import claim_range

QUARANTINE_MARKER = "QUARANTINED_DO_NOT_MAIL.txt"


@dataclass
class PipelineConfig:
    embed_config: dict
    feed_direction: FeedDirection
    has_insert: bool
    has_divert: bool = False
    divert_overflow: bool = False


def _has_prior_output(output_dir: Path) -> bool:
    """True if a previous run left processed documents or a report here."""
    if not output_dir.exists():
        return False
    if (output_dir / "report.json").exists():
        return True
    for sub in ("machine_ready", "manual_overflow"):
        if any((output_dir / sub).glob("*.pdf")):
            return True
    return False


def _check_doc_sets(doc_sets_to_process: list) -> None:
    """Reject document sets that cannot produce a valid barcode payload."""
    for ds in doc_sets_to_process:
        if ds.sheet_count < 1:
            raise ValueError(
                f"Document set {ds.index + 1} has {ds.sheet_count} sheets — "
                f"cannot process an empty document set"
            )
        if ds.sheet_count > MAX_SET_COUNT:
            raise ValueError(
                f"Document set {ds.index + 1} has {ds.sheet_count} sheets, "
                f"exceeding the {MAX_SET_COUNT}-sheet barcode field capacity — "
                f"no valid barcode can be generated; split or pull this document"
            )


def _check_unique_ids(ids_to_process: list[int], prior_ids: list[int]) -> None:
    """Abort if any mailpiece UID would be duplicated within the job."""
    seen: set[int] = set(prior_ids)
    duplicates: set[int] = set()
    for uid in ids_to_process:
        effective = uid % (10 ** 9)
        if effective in seen:
            duplicates.add(effective)
        seen.add(effective)
    if duplicates:
        shown = ", ".join(str(d) for d in sorted(duplicates)[:10])
        raise ValueError(
            f"Duplicate unique ID(s) detected within this job: {shown} — "
            f"the inserter cannot distinguish these mailpieces; aborting"
        )


def _check_page_sizes(reader: PdfReader, warnings: list[str]) -> None:
    """Warn when the batch mixes page sizes — fixed-position regions and the
    barcode anchor assume a uniform sheet size."""
    sizes: dict[tuple[int, int], int] = {}
    for page in reader.pages:
        box = page.mediabox
        key = (round(float(box.width)), round(float(box.height)))
        sizes[key] = sizes.get(key, 0) + 1
    if len(sizes) > 1:
        listing = ", ".join(
            f"{w}x{h} pt ({n} page(s))" for (w, h), n in sorted(sizes.items())
        )
        warnings.append(
            f"Mixed page sizes in source PDF: {listing} — verify barcode "
            f"placement and template regions on every size"
        )


def _write_manifest(output_dir: Path, pieces: list[MailPiece]) -> Path:
    """Write the per-piece mail run data file (sidecar manifest)."""
    manifest_path = output_dir / "mail_run_data.csv"
    with open(manifest_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "piece", "unique_id", "sheets", "start_page", "end_page",
            "overflow", "insert", "divert", "barcodes", "output_file",
        ])
        for p in pieces:
            writer.writerow([
                p.doc_index + 1,
                f"{p.unique_id:09d}",
                p.sheet_count,
                p.start_page + 1,
                p.end_page + 1,
                int(p.is_overflow),
                int(p.has_insert),
                int(p.divert),
                ";".join(p.barcodes),
                Path(p.output_path).name,
            ])
    return manifest_path


def _check_clear_zones(
    source: Path,
    doc_sets_to_process: list,
    embed_config: dict,
    warnings: list[str],
) -> None:
    """Inspect barcode footprints on all pages to be stamped."""
    mode = settings.clear_zone_mode
    if mode == "off":
        return
    pages = [p for ds in doc_sets_to_process for p in ds.side_a_pages]
    violations = find_clear_zone_violations(source, pages, embed_config)
    if not violations:
        return
    shown = "; ".join(
        f"page {v['page_index'] + 1}: {v['chars']} char(s), {v['images']} image(s)"
        for v in violations[:10]
    )
    more = "" if len(violations) <= 10 else f" (+{len(violations) - 10} more pages)"
    message = (
        f"Barcode clear-zone violation on {len(violations)} page(s) — existing "
        f"page content lies under the barcode footprint and will be covered: "
        f"{shown}{more}"
    )
    if mode == "abort":
        raise ValueError(message)
    warnings.append(message)


def _process_pipeline(
    db: Session,
    job: Job,
    doc_sets: list,
    unique_ids: list[int],
    config: PipelineConfig,
    progress_callback: Callable[[int, int, str], None] | None = None,
    warnings: list[str] | None = None,
) -> tuple[JobResult, bytes]:
    source = Path(job.source_path)
    warnings = list(warnings or [])

    def report_progress(current: int, total: int, msg: str = ""):
        if progress_callback:
            progress_callback(current, total, msg)

    start_index = (job.last_processed_index or -1) + 1
    doc_sets_to_process = doc_sets[start_index:]
    ids_to_process = unique_ids[start_index:]

    output_dir = source.parent / f"{job.name}_{job.session_id}_{job.date.isoformat()}"

    # Never overwrite a previous run's output (resume of the same run is fine)
    if start_index == 0 and _has_prior_output(output_dir):
        raise ValueError(
            f"Output directory already contains a processed run: {output_dir} — "
            f"refusing to overwrite mailpiece output; move or remove it first"
        )

    machine_dir = output_dir / "machine_ready"
    overflow_dir = output_dir / "manual_overflow"
    machine_dir.mkdir(parents=True, exist_ok=True)
    overflow_dir.mkdir(parents=True, exist_ok=True)

    # Drop piece records for any docs we are about to (re)process, so a resume
    # cannot leave duplicate or stale rows behind.
    db.query(MailPiece).filter(
        MailPiece.job_id == job.id, MailPiece.doc_index >= start_index
    ).delete(synchronize_session=False)
    db.commit()

    prior_ids = [p.unique_id for p in db.query(MailPiece).filter_by(job_id=job.id)]

    # One parse of the source PDF, shared by every doc set in this run
    source_reader = PdfReader(str(source))

    # Pre-flight safety checks — fail before anything is stamped
    _check_doc_sets(doc_sets_to_process)
    _check_unique_ids(ids_to_process, prior_ids)
    _check_page_sizes(source_reader, warnings)
    _check_clear_zones(source, doc_sets_to_process, config.embed_config, warnings)

    embed_config = config.embed_config
    overflow_threshold = settings.overflow_threshold

    for i, ds in enumerate(doc_sets_to_process):
        unique_id = ids_to_process[i]
        is_overflow = ds.sheet_count > overflow_threshold
        divert = None
        if config.has_divert:
            divert = is_overflow and config.divert_overflow

        barcodes_for_doc: dict[int, str] = {}
        barcode_strings: list[str] = []

        for sheet_idx in range(ds.sheet_count):
            sheet_num = sheet_idx + 1

            if config.feed_direction == FeedDirection.ASCENDING:
                is_eog = sheet_num == ds.sheet_count
            else:
                is_eog = sheet_num == 1

            barcode_str = generate_barcode_string(
                unique_id=unique_id,
                sheet_number=sheet_num,
                set_count=ds.sheet_count,
                has_insert=config.has_insert,
                is_end_of_group=is_eog,
                divert=divert,
            )
            if not validate_barcode_string(barcode_str):
                raise ValueError(
                    f"Generated barcode failed validation for document set "
                    f"{ds.index + 1}, sheet {sheet_num}: {barcode_str!r}"
                )

            page_index = ds.side_a_pages[sheet_idx]
            barcodes_for_doc[page_index] = barcode_str
            barcode_strings.append(barcode_str)

        out_subdir = overflow_dir if is_overflow else machine_dir
        out_file = out_subdir / f"doc_{ds.index:06d}.pdf"
        process_document(
            input_path=source_reader,
            page_range=(ds.start_page, ds.end_page),
            side_a_barcodes=barcodes_for_doc,
            embed_config=embed_config,
            output_path=out_file,
        )

        # Piece record + progress checkpoint commit atomically together
        db.add(MailPiece(
            job_id=job.id,
            doc_index=ds.index,
            unique_id=unique_id % (10 ** 9),
            sheet_count=ds.sheet_count,
            start_page=ds.start_page,
            end_page=ds.end_page,
            is_overflow=is_overflow,
            has_insert=config.has_insert,
            divert=bool(divert),
            barcodes=barcode_strings,
            output_path=str(out_file),
        ))
        job.last_processed_index = start_index + i
        db.commit()
        report_progress(i + 1, len(doc_sets_to_process), f"Processed doc set {ds.index + 1}")

    # Rebuild all totals from the persisted piece records so they are correct
    # whether this run was fresh or resumed.
    pieces = (
        db.query(MailPiece)
        .filter_by(job_id=job.id)
        .order_by(MailPiece.doc_index)
        .all()
    )
    total_documents = len(pieces)
    total_sheets = sum(p.sheet_count for p in pieces)
    total_barcodes = sum(len(p.barcodes) for p in pieces)
    insert_count = sum(p.sheet_count for p in pieces if p.has_insert)
    diverts_triggered = sum(p.sheet_count for p in pieces if p.divert)
    overflow_pieces = [p for p in pieces if p.is_overflow]
    overflow_detail = [
        {"doc_index": p.doc_index, "sheets": p.sheet_count, "unique_id": p.unique_id}
        for p in overflow_pieces
    ]
    machine_ready_paths = [Path(p.output_path) for p in pieces if not p.is_overflow]

    imports = [
        {
            "expected_letters": bi.expected_letters,
            "expected_sheets": bi.expected_sheets,
        }
        for bi in job.batch_imports
    ]

    totals = {
        "total_documents": total_documents,
        "total_sheets": total_sheets,
        "total_barcodes": total_barcodes,
        "inserts_triggered": insert_count,
        "diverts_triggered": diverts_triggered,
        "overflow_documents": len(overflow_pieces),
    }

    report = generate_report(
        job_info={"name": job.name, "session_id": job.session_id, "date": job.date.isoformat()},
        totals=totals,
        imports=imports,
        overflow_detail=overflow_detail,
        warnings=warnings,
    )

    report_json_path = output_dir / "report.json"
    report_json_path.write_text(json.dumps(report, indent=2))

    # Sidecar manifest: one row per mailpiece for machine import/reconciliation
    _write_manifest(output_dir, pieces)

    report_pdf_bytes = generate_report_pdf(report)
    report_pdf_path = output_dir / "report.pdf"
    report_pdf_path.write_bytes(report_pdf_bytes)

    verification_data = report.get("verification")
    verification = VerificationStatus(verification_data["verdict"]) if verification_data else VerificationStatus.OK

    # Gate the machine-ready deliverable on verification: a count mismatch
    # means pieces are unaccounted for, so the combined output is withheld.
    combined_path = output_dir / "combined_output.pdf"
    if verification == VerificationStatus.OK:
        marker = output_dir / QUARANTINE_MARKER
        if marker.exists():
            marker.unlink()
        if machine_ready_paths:
            merge_pdfs(
                [report_pdf_path] + machine_ready_paths + [report_pdf_path],
                combined_path,
            )
    else:
        details = verification_data.get("details") if verification_data else None
        (output_dir / QUARANTINE_MARKER).write_text(
            f"Job: {job.name}\n"
            f"Session: {job.session_id}\n"
            f"Verification: {verification.value}\n"
            f"Details: {details or 'n/a'}\n\n"
            f"Document/sheet counts did not match the expected batch data.\n"
            f"combined_output.pdf was NOT generated. Do not feed this output\n"
            f"to the inserter until the discrepancy is resolved.\n"
        )

    result = JobResult(
        job_id=job.id,
        total_barcodes=total_barcodes,
        total_documents=total_documents,
        total_sheets=total_sheets,
        overflow_docs=len(overflow_pieces),
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

    return result, report_pdf_bytes


def _run_job_template(
    db: Session,
    job: Job,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> JobResult:
    from app.services.detector import detect_from_regions

    template = job.template
    source = Path(job.source_path)

    detection_warnings: list[str] = []
    doc_sets = detect_from_regions(
        source,
        template.regions,
        template.page_format,
        max_sheets_per_doc=settings.max_sheets_per_doc,
        warnings=detection_warnings,
    )
    if not doc_sets:
        raise ValueError("No document sets detected in the source PDF")

    job.total_doc_sets = len(doc_sets)
    db.commit()

    start_index = (job.last_processed_index or -1) + 1
    doc_sets_to_process = doc_sets[start_index:]

    need_sequential = sum(1 for ds in doc_sets_to_process if ds.unique_id is None)
    id_start = 0
    seq_idx = 0
    if need_sequential > 0:
        id_start, _ = claim_range(db, count=need_sequential)

    unique_ids = []
    for ds in doc_sets:
        if ds.index >= start_index:
            if ds.unique_id is not None:
                unique_ids.append(ds.unique_id)
            else:
                unique_ids.append(id_start + seq_idx)
                seq_idx += 1
        else:
            unique_ids.append(0)

    config = PipelineConfig(
        embed_config=template.embed_config,
        feed_direction=template.feed_direction,
        has_insert=template.has_insert,
    )

    result, _ = _process_pipeline(
        db, job, doc_sets, unique_ids, config, progress_callback,
        warnings=detection_warnings,
    )
    return result


def run_job(
    db: Session,
    job: Job,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> JobResult:
    # Atomically claim the job so two callers cannot run it concurrently.
    claimed = (
        db.query(Job)
        .filter(
            Job.id == job.id,
            Job.status.in_((JobStatus.DRAFT, JobStatus.PARTIAL, JobStatus.ERROR)),
        )
        .update({Job.status: JobStatus.PROCESSING}, synchronize_session=False)
    )
    db.commit()
    if not claimed:
        raise ValueError(
            f"Job {job.id} cannot be started from status {job.status.value} — "
            f"it is already running or complete"
        )
    db.refresh(job)

    try:
        if job.mode == JobMode.TEMPLATE:
            if not job.template:
                raise ValueError("Template mode job has no template assigned")
            return _run_job_template(db, job, progress_callback)
        return _run_job_preset(db, job, progress_callback)
    except Exception as e:
        db.rollback()
        job.status = JobStatus.ERROR
        job.error_message = str(e)
        db.commit()
        raise


def _run_job_preset(
    db: Session,
    job: Job,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> JobResult:
    preset: Preset = job.preset
    source = Path(job.source_path)

    validation = validate_page_count(source, preset.sheets_per_doc, preset.page_format)
    if not validation.valid:
        raise ValueError(validation.error)

    job.total_doc_sets = validation.doc_sets
    db.commit()

    doc_sets = split_by_preset(source, preset.sheets_per_doc, preset.page_format)

    start_index = (job.last_processed_index or -1) + 1
    doc_sets_to_process = doc_sets[start_index:]

    id_start, _ = claim_range(db, count=len(doc_sets_to_process))
    unique_ids = [0] * start_index + [id_start + i for i in range(len(doc_sets_to_process))]

    config = PipelineConfig(
        embed_config=preset.embed_config,
        feed_direction=preset.feed_direction,
        has_insert=preset.has_insert,
        has_divert=preset.has_divert,
        divert_overflow=preset.divert_overflow,
    )

    result, report_pdf_bytes = _process_pipeline(db, job, doc_sets, unique_ids, config, progress_callback)

    if preset.auto_email_enabled and preset.email_recipients:
        recipients = [r.strip() for r in preset.email_recipients.split(",") if r.strip()]
        if recipients:
            is_error = result.verification != VerificationStatus.OK or result.overflow_docs > 0
            if is_error:
                subject = f"[Braze Codes] [ACTION REQUIRED] {job.name} — {job.session_id} — Errors Detected"
                status_text = "ERRORS DETECTED"
            else:
                subject = f"[Braze Codes] {job.name} — {job.session_id} — Complete"
                status_text = "COMPLETE"

            body = (
                f"Job: {job.name}\n"
                f"Session: {job.session_id}\n"
                f"Date: {job.date.isoformat()}\n"
                f"Status: {status_text}\n\n"
                f"Letters Processed: {result.total_documents}\n"
                f"Total Sheets: {result.total_sheets}\n"
                f"Barcodes Applied: {result.total_barcodes}\n\n"
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
