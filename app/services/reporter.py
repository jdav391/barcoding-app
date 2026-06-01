from __future__ import annotations

from dataclasses import dataclass

from app.enums import VerificationStatus


@dataclass
class VerificationResult:
    status: VerificationStatus
    match: bool
    details: str = ""


def verify_against_imports(
    actual: dict, expected_imports: list[dict]
) -> VerificationResult:
    if not expected_imports:
        return VerificationResult(status=VerificationStatus.OK, match=True)

    total_expected_letters = sum(e["expected_letters"] for e in expected_imports)
    total_expected_sheets = sum(e["expected_sheets"] for e in expected_imports)

    mismatches = []
    if actual["total_documents"] != total_expected_letters:
        mismatches.append(
            f"Documents: expected {total_expected_letters}, got {actual['total_documents']}"
        )
    if actual["total_sheets"] != total_expected_sheets:
        mismatches.append(
            f"Sheets: expected {total_expected_sheets}, got {actual['total_sheets']}"
        )

    if mismatches:
        return VerificationResult(
            status=VerificationStatus.MISMATCH,
            match=False,
            details="; ".join(mismatches),
        )

    return VerificationResult(status=VerificationStatus.OK, match=True)


def generate_report(
    job_info: dict,
    totals: dict,
    imports: list[dict],
    overflow_detail: list[dict] | None = None,
    warnings: list[str] | None = None,
) -> dict:
    verification = verify_against_imports(
        {"total_documents": totals["total_documents"], "total_sheets": totals["total_sheets"]},
        imports,
    )

    report = {
        "job": job_info["name"],
        "session_id": job_info["session_id"],
        "date": job_info["date"],
        "status": verification.status.value,
        "totals": {
            "documents_processed": totals["total_documents"],
            "total_sheets": totals["total_sheets"],
            "total_barcodes": totals["total_barcodes"],
            "inserts_triggered": totals["inserts_triggered"],
            "diverts_triggered": totals["diverts_triggered"],
            "overflow_documents": totals["overflow_documents"],
        },
        "overflow_detail": overflow_detail or [],
        "warnings": warnings or [],
    }

    if imports:
        total_expected_letters = sum(e["expected_letters"] for e in imports)
        total_expected_sheets = sum(e["expected_sheets"] for e in imports)
        report["verification"] = {
            "expected_letters": total_expected_letters,
            "actual_documents": totals["total_documents"],
            "expected_sheets": total_expected_sheets,
            "actual_sheets": totals["total_sheets"],
            "match": verification.match,
            "verdict": verification.status.value,
            "details": verification.details or None,
        }

    return report
