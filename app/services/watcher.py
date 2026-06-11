"""Watched intake directories — auto-process PDFs dropped per template.

Each template may define its own input_dir. New PDFs appearing there are
picked up once their size/mtime is stable across two polls (so half-copied
files are never processed), moved into an ingested/ subdirectory (so they can
never be picked up twice), and run through the normal job pipeline with that
template. One directory per template means a batch can never be processed
with the wrong template's regions or settings.

Processing is strictly serial: one watcher thread, one job at a time.
"""
from __future__ import annotations

import logging
import shutil
import threading
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.enums import JobMode, JobStatus
from app.models import Job, Template

logger = logging.getLogger(__name__)

INGESTED_SUBDIR = "ingested"


def find_stable_pdfs(directory: Path, state: dict) -> list[Path]:
    """Return PDFs whose size/mtime is unchanged since the previous scan.

    *state* maps path -> (size, mtime) from earlier scans; it is updated in
    place. A file is only returned once it has been observed twice with
    identical stats, so files still being copied are left alone.
    """
    stable: list[Path] = []
    seen_now: set[Path] = set()

    if not directory.is_dir():
        return stable

    for item in sorted(directory.iterdir()):
        if item.name.startswith(".") or item.is_dir():
            continue
        if item.suffix.lower() != ".pdf":
            continue
        try:
            stat = item.stat()
        except OSError:
            continue
        seen_now.add(item)
        current = (stat.st_size, stat.st_mtime)
        if state.get(item) == current:
            stable.append(item)
        state[item] = current

    # Forget files that disappeared (moved/deleted between polls)
    for known in list(state):
        if known.parent == directory and known not in seen_now:
            del state[known]

    return stable


def ingest_file(db: Session, template: Template, path: Path) -> Job:
    """Move *path* into the ingested/ subdir and create a DRAFT job for it."""
    ingested_dir = path.parent / INGESTED_SUBDIR
    ingested_dir.mkdir(parents=True, exist_ok=True)

    dest = ingested_dir / path.name
    counter = 1
    while dest.exists():
        dest = ingested_dir / f"{path.stem}_{counter}{path.suffix}"
        counter += 1
    shutil.move(str(path), str(dest))

    session_id = f"AUTO-{datetime.now().strftime('%Y%m%d-%H%M%S%f')}"
    job = Job(
        name=path.stem,
        session_id=session_id,
        source_path=str(dest),
        template_id=template.id,
        mode=JobMode.TEMPLATE,
        status=JobStatus.DRAFT,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    logger.info("Watcher ingested %s for template %r as job %s", dest.name, template.name, job.id)
    return job


def process_template_dirs(db: Session, state: dict) -> list[Job]:
    """One scan pass: ingest stable PDFs from every watched dir and run them.

    Failures are recorded on the job and as an .ERROR.txt marker next to the
    ingested file; one bad batch never blocks the others.
    """
    from app.services.job import run_job

    processed: list[Job] = []
    templates = (
        db.query(Template).filter(Template.input_dir.isnot(None)).all()
    )
    for template in templates:
        directory = Path(template.input_dir)
        for path in find_stable_pdfs(directory, state):
            job = ingest_file(db, template, path)
            try:
                run_job(db, job)
                logger.info("Watcher completed job %s (%s)", job.id, job.name)
            except Exception as e:
                logger.exception("Watcher job %s failed", job.id)
                marker = Path(job.source_path).with_name(
                    f"{Path(job.source_path).stem}.ERROR.txt"
                )
                marker.write_text(
                    f"Automatic processing failed for {Path(job.source_path).name}\n"
                    f"Template: {template.name}\n"
                    f"Job ID: {job.id}\n"
                    f"Error: {e}\n"
                )
            processed.append(job)
    return processed


class Watcher:
    """Background thread polling all template intake directories."""

    def __init__(self, session_factory=None, poll_seconds: float | None = None):
        if session_factory is None:
            from app.database import SessionLocal
            session_factory = SessionLocal
        self._session_factory = session_factory
        self._poll = poll_seconds or settings.watch_poll_seconds
        self._state: dict = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="intake-watcher", daemon=True)

    def start(self) -> None:
        logger.info("Intake watcher started (poll every %.1fs)", self._poll)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=self._poll + 5)

    def scan_once(self) -> list[Job]:
        db = self._session_factory()
        try:
            return process_template_dirs(db, self._state)
        finally:
            db.close()

    def _run(self) -> None:
        while not self._stop.wait(self._poll):
            try:
                self.scan_once()
            except Exception:
                logger.exception("Intake watcher scan failed")
