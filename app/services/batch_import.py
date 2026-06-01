from __future__ import annotations

import csv
import re
from io import StringIO
from typing import IO

from app.schemas import BatchImportData

EMAIL_PATTERN = re.compile(
    r"Sent file:\s*(?P<filename>\S+\.pdf)"
    r",\s*Letters:\s*(?P<letters>\d+)"
    r",\s*Total Sheets:\s*(?P<sheets>\d+)"
    r"(?:,\s*(?P<spe>\d+)\s*sheets? per envelope)?"
    r",\s*Print type:\s*(?P<print_type>[^,]+?)"
    r"(?:,\s*Insert:\s*(?P<insert>.+))?"
    r"\s*$",
    re.MULTILINE,
)


def parse_email_text(text: str) -> list[BatchImportData]:
    """Parse one or more email lines describing batch files into BatchImportData records."""
    results: list[BatchImportData] = []
    for m in EMAIL_PATTERN.finditer(text):
        filename = m.group("filename")
        # batch_id is the filename stem (strip .pdf)
        batch_id = filename.removesuffix(".pdf")
        spe = m.group("spe")
        insert_desc = m.group("insert")
        results.append(
            BatchImportData(
                batch_id=batch_id,
                source_filename=filename,
                expected_letters=int(m.group("letters")),
                expected_sheets=int(m.group("sheets")),
                sheets_per_doc=int(spe) if spe is not None else None,
                print_type=m.group("print_type"),
                has_insert=insert_desc is not None,
                insert_description=insert_desc if insert_desc is not None else None,
            )
        )
    return results


def parse_csv(file: IO[str]) -> list[BatchImportData]:
    """Parse a CSV file with batch import data into a list of BatchImportData records.

    Expected columns (at minimum):
        batch_id, source_filename, expected_letters, expected_sheets,
        sheets_per_doc, print_type, has_insert, insert_description
    """
    results: list[BatchImportData] = []
    reader = csv.DictReader(file)
    for row in reader:
        # Coerce types
        sheets_per_doc_raw = row.get("sheets_per_doc", "").strip()
        print_type_raw = row.get("print_type", "").strip() or None
        insert_desc_raw = row.get("insert_description", "").strip() or None
        has_insert_raw = row.get("has_insert", "false").strip().lower()
        results.append(
            BatchImportData(
                batch_id=row["batch_id"].strip(),
                source_filename=row.get("source_filename", "").strip() or None,
                expected_letters=int(row["expected_letters"]),
                expected_sheets=int(row["expected_sheets"]),
                sheets_per_doc=int(sheets_per_doc_raw) if sheets_per_doc_raw else None,
                print_type=print_type_raw,
                has_insert=has_insert_raw in ("true", "1", "yes"),
                insert_description=insert_desc_raw,
            )
        )
    return results
