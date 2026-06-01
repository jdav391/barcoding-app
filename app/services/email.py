from __future__ import annotations

import logging
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def build_message(
    sender: str,
    recipients: list[str],
    subject: str,
    body: str,
    attachment_bytes: bytes,
    attachment_filename: str,
) -> MIMEMultipart:
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))

    part = MIMEBase("application", "pdf")
    part.set_payload(attachment_bytes)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{attachment_filename}"')
    msg.attach(part)

    return msg


def send_report_email(
    host: str,
    port: int,
    username: str,
    password: str,
    recipients: list[str],
    subject: str,
    body: str,
    pdf_bytes: bytes,
    pdf_filename: str,
) -> bool:
    if not host or not username:
        logger.warning("SMTP not configured — skipping email send")
        return False

    try:
        msg = build_message(
            sender=username,
            recipients=recipients,
            subject=subject,
            body=body,
            attachment_bytes=pdf_bytes,
            attachment_filename=pdf_filename,
        )
        with smtplib.SMTP(host, port) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(msg)
        logger.info("Report email sent to %s", ", ".join(recipients))
        return True
    except Exception:
        logger.exception("Failed to send report email")
        return False
