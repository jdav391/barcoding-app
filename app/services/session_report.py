from __future__ import annotations

import io
from datetime import UTC, datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle


def generate_session_report_pdf(report_data: dict) -> bytes:
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
        "ReportSubtitle", parent=styles["Normal"], fontSize=11,
        textColor=colors.grey, spaceAfter=8,
    )
    section_style = ParagraphStyle(
        "SectionHeader", parent=styles["Heading2"], fontSize=12,
        spaceBefore=12, spaceAfter=4,
    )
    footer_style = ParagraphStyle(
        "Footer", parent=styles["Normal"], fontSize=8,
        textColor=colors.grey, spaceBefore=12,
    )

    elements = []

    elements.append(Paragraph("BrazeBars Session Report", title_style))
    elements.append(Paragraph(
        f"{report_data['session_name']} &mdash; {report_data['session_id']} &mdash; {report_data['date']}",
        subtitle_style,
    ))

    banner_data = [[Paragraph(
        '<font color="white"><b>SESSION COMPILED</b></font>',
        ParagraphStyle("Banner", parent=styles["Normal"], fontSize=14, alignment=1),
    )]]
    banner_table = Table(banner_data, colWidths=[7 * inch])
    banner_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.Color(0.2, 0.5, 0.8)),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    elements.append(banner_table)
    elements.append(Spacer(1, 8))

    elements.append(Paragraph("Session Totals", section_style))
    totals = report_data["totals"]
    summary_rows = [
        ["Total Documents", str(totals["total_documents"])],
        ["Total Sheets", str(totals["total_sheets"])],
        ["Total Barcodes", str(totals["total_barcodes"])],
    ]
    if totals.get("overflow_documents", 0) > 0:
        summary_rows.append(["Overflow (Manual)", str(totals["overflow_documents"])])

    summary_table = Table(summary_rows, colWidths=[4.5 * inch, 2.5 * inch])
    summary_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("BACKGROUND", (0, 0), (0, -1), colors.Color(0.95, 0.95, 0.95)),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(summary_table)

    elements.append(Paragraph("Jobs", section_style))
    job_header = ["Job Name", "Source File", "Preset", "Docs", "Sheets"]
    job_rows = [job_header]
    for j in report_data["jobs"]:
        job_rows.append([
            j["name"],
            j["source_file"],
            j["preset"],
            str(j["documents"]),
            str(j["sheets"]),
        ])
    job_table = Table(job_rows, colWidths=[1.5 * inch, 2 * inch, 1.5 * inch, 1 * inch, 1 * inch])
    job_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.85, 0.85, 0.85)),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(job_table)

    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    elements.append(Paragraph(
        f"Generated: {timestamp}<br/>This report was generated automatically by BrazeBars.",
        footer_style,
    ))

    doc.build(elements)
    return buf.getvalue()
