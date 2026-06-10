from __future__ import annotations

import logging
import smtplib
from functools import lru_cache
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import quote

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    @staticmethod
    def _password_reset_base_url() -> str:
        return str(settings.BACKEND_PUBLIC_URL or settings.FRONTEND_URL).rstrip("/")

    @staticmethod
    def _sender() -> str:
        sender_email = str(settings.SMTP_USERNAME or "").strip()
        if not sender_email:
            raise RuntimeError("SMTP_USERNAME is not configured.")
        sender_name = str(settings.SMTP_FROM_NAME or settings.PROJECT_NAME).strip() or settings.PROJECT_NAME
        return f"{sender_name} <{sender_email}>"

    @staticmethod
    def build_password_reset_url(reset_token: str) -> str:
        return f"{EmailService._password_reset_base_url()}/reset-password?token={quote(reset_token, safe='')}"

    @staticmethod
    def _validate_smtp_settings() -> tuple[str, int, str, str]:
        host = str(settings.SMTP_HOST or "").strip()
        port = int(settings.SMTP_PORT)
        username = str(settings.SMTP_USERNAME or "").strip()
        password = "".join(str(settings.SMTP_PASSWORD or "").split())

        if not host:
            raise RuntimeError("SMTP_HOST is not configured.")
        if not username:
            raise RuntimeError("SMTP_USERNAME is not configured.")
        if not password:
            raise RuntimeError("SMTP_PASSWORD is not configured.")

        return host, port, username, password

    def send_email(self, to_email: str, subject: str, html_body: str) -> None:
        host, port, username, password = self._validate_smtp_settings()

        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = self._sender()
        message["To"] = to_email
        message.attach(MIMEText(html_body, "html"))

        try:
            with smtplib.SMTP(host, port, timeout=30) as server:
                server.starttls()
                server.login(username, password)
                server.send_message(message)
        except Exception:
            logger.exception("SMTP email delivery failed for recipient=%s subject=%s", to_email, subject)
            raise

    def send_password_reset_email(self, *, recipient: str, user_name: str, reset_token: str) -> None:
        reset_url = self.build_password_reset_url(reset_token)
        safe_name = str(user_name or "there").strip() or "there"
        subject = f"Reset Your Password - {settings.PROJECT_NAME}"
        html_body = (
            '<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">'
            f"<h2>Hi {safe_name},</h2>"
            f"<p>We received a request to reset your <strong>{settings.PROJECT_NAME}</strong> password.</p>"
            f'<a href="{reset_url}" '
            'style="display: inline-block; padding: 12px 24px; background: #2563eb; '
            'color: white; text-decoration: none; border-radius: 6px;">'
            "Reset your password"
            "</a>"
            '<p style="color: #666; margin-top: 16px;">'
            "If you did not request this change, you can safely ignore this email."
            "</p>"
            "</div>"
        )
        self.send_email(recipient, subject, html_body)


@lru_cache
def get_email_service() -> EmailService:
    return EmailService()
