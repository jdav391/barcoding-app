from __future__ import annotations

import io
from datetime import UTC, datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle


def generate_report_pdf(report: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle", parent=styles["Title"], fontSize=18, spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle", parent=styles["Normal"], fontSize=11, textColor=colors.grey, spaceAfter=8,
    )
    section_style = ParagraphStyle(
        "SectionHeader", parent=styles["Heading2"], fontSize=12, spaceBefore=12, spaceAfter=4,
    )
    footer_style = ParagraphStyle(
        "Footer", parent=styles["Normal"], fontSize=8, textColor=colors.grey, spaceBefore=12,
    )

    elements = []

    elements.append(Paragraph("BrazeBars Job Report", title_style))
    elements.append(Paragraph(
        f"{report['job']} &mdash; Session {report['session_id']} &mdash; {report['date']}",
        subtitle_style,
    ))

    has_verification = "verification" in report
    is_fail = report.get("status") == "MISMATCH"

    if is_fail:
        banner_text = "VERIFICATION FAILED"
        banner_bg = colors.Color(0.9, 0.2, 0.2)
    else:
        banner_text = "PROCESSING COMPLETE"
        banner_bg = colors.Color(0.2, 0.7, 0.3)

    banner_data = [[Paragraph(
        f'<font color="white"><b>{banner_text}</b></font>',
        ParagraphStyle("Banner", parent=styles["Normal"], fontSize=14, alignment=1),
    )]]
    banner_table = Table(banner_data, colWidths=[7 * inch])
    banner_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), banner_bg),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    elements.append(banner_table)
    elements.append(Spacer(1, 8))

    elements.append(Paragraph("Summary", section_style))
    totals = report["totals"]
    summary_rows = [
        ["Letters Processed", str(totals["documents_processed"])],
        ["Total Sheets", str(totals["total_sheets"])],
        ["Barcodes Applied", str(totals["total_barcodes"])],
    ]
    if totals.get("inserts_triggered", 0) > 0:
        summary_rows.append(["Inserts", str(totals["inserts_triggered"])])
    if totals.get("diverts_triggered", 0) > 0:
        summary_rows.append(["Diverts", str(totals["diverts_triggered"])])
    if totals.get("overflow_documents", 0) > 0:
        summary_rows.append(["Overflow (Manual Processing)", str(totals["overflow_documents"])])

    summary_table = Table(summary_rows, colWidths=[4.5 * inch, 2.5 * inch])
    summary_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("BACKGROUND", (0, 0), (0, -1), colors.Color(0.95, 0.95, 0.95)),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(summary_table)

    if has_verification:
        v = report["verification"]
        elements.append(Paragraph("Verification Details", section_style))
        result_text = "PASS" if v["match"] else "FAIL"
        verify_rows = [
            ["Expected Letters", str(v["expected_letters"])],
            ["Letters Processed", str(v["actual_documents"])],
            ["Expected Sheets", str(v["expected_sheets"])],
            ["Sheets Processed", str(v["actual_sheets"])],
            ["Result", result_text],
        ]
        verify_table = Table(verify_rows, colWidths=[4.5 * inch, 2.5 * inch])
        verify_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("BACKGROUND", (0, 0), (0, -1), colors.Color(0.95, 0.95, 0.95)),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("TEXTCOLOR", (1, -1), (1, -1), colors.green if v["match"] else colors.red),
            ("FONTNAME", (1, -1), (1, -1), "Helvetica-Bold"),
        ]))
        elements.append(verify_table)

    overflow = report.get("overflow_detail", [])
    if overflow:
        elements.append(Paragraph("Overflow Documents", section_style))
        elements.append(Paragraph(
            "The following documents exceeded the folding threshold and were diverted for manual processing.",
            styles["Normal"],
        ))
        elements.append(Spacer(1, 4))
        max_rows = 15
        overflow_rows = [["Document", "Sheets", "Unique ID"]]
        for od in overflow[:max_rows]:
            overflow_rows.append([str(od["doc_index"] + 1), str(od["sheets"]), str(od["unique_id"])])
        if len(overflow) > max_rows:
            overflow_rows.append([
                f"Showing {max_rows} of {len(overflow)} overflow documents. See full report in output directory.",
                "", "",
            ])
        overflow_table = Table(overflow_rows, colWidths=[2.33 * inch, 2.33 * inch, 2.34 * inch])
        overflow_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.85, 0.85, 0.85)),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(overflow_table)

    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    elements.append(Paragraph(
        f"Generated: {timestamp}<br/>This report was generated automatically by the BrazeBars.",
        footer_style,
    ))

    doc.build(elements)
    return buf.getvalue()
