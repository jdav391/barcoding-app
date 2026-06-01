from unittest.mock import patch, MagicMock

from app.services.email import send_report_email, build_message


class TestBuildMessage:
    def test_message_structure(self):
        msg = build_message(
            sender="test@example.com",
            recipients=["qa@example.com"],
            subject="Test Subject",
            body="Test body text.",
            attachment_bytes=b"%PDF-fake",
            attachment_filename="report.pdf",
        )
        assert msg["From"] == "test@example.com"
        assert msg["To"] == "qa@example.com"
        assert msg["Subject"] == "Test Subject"
        payloads = msg.get_payload()
        assert len(payloads) == 2
        assert payloads[0].get_content_type() == "text/plain"
        assert payloads[1].get_content_type() == "application/pdf"
        assert payloads[1].get_filename() == "report.pdf"

    def test_multiple_recipients(self):
        msg = build_message(
            sender="test@example.com",
            recipients=["a@example.com", "b@example.com"],
            subject="Multi",
            body="Body",
            attachment_bytes=b"%PDF-fake",
            attachment_filename="report.pdf",
        )
        assert msg["To"] == "a@example.com, b@example.com"

    def test_body_content(self):
        msg = build_message(
            sender="test@example.com",
            recipients=["qa@example.com"],
            subject="Subj",
            body="Expected body content here.",
            attachment_bytes=b"%PDF-fake",
            attachment_filename="report.pdf",
        )
        text_part = msg.get_payload()[0]
        assert "Expected body content here." in text_part.get_payload()


class TestSendReportEmail:
    @patch("app.services.email.smtplib.SMTP")
    def test_sends_via_smtp(self, mock_smtp_class):
        mock_smtp = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        result = send_report_email(
            host="smtp.gmail.com",
            port=587,
            username="user@gmail.com",
            password="secret",
            recipients=["qa@example.com"],
            subject="Test",
            body="Body",
            pdf_bytes=b"%PDF-fake",
            pdf_filename="report.pdf",
        )

        assert result is True
        mock_smtp_class.assert_called_once_with("smtp.gmail.com", 587)
        mock_smtp.starttls.assert_called_once()
        mock_smtp.login.assert_called_once_with("user@gmail.com", "secret")
        mock_smtp.send_message.assert_called_once()

    @patch("app.services.email.smtplib.SMTP")
    def test_returns_false_on_smtp_error(self, mock_smtp_class):
        mock_smtp_class.side_effect = Exception("Connection refused")

        result = send_report_email(
            host="smtp.gmail.com",
            port=587,
            username="user@gmail.com",
            password="secret",
            recipients=["qa@example.com"],
            subject="Test",
            body="Body",
            pdf_bytes=b"%PDF-fake",
            pdf_filename="report.pdf",
        )

        assert result is False

    def test_returns_false_when_no_smtp_configured(self):
        result = send_report_email(
            host="",
            port=587,
            username="",
            password="",
            recipients=["qa@example.com"],
            subject="Test",
            body="Body",
            pdf_bytes=b"%PDF-fake",
            pdf_filename="report.pdf",
        )

        assert result is False
