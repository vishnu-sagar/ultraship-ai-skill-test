"""Email (.eml) -> raw text, covering the two real-world shapes brokers get:
1. Rate confirmation details typed directly in the email body.
2. A one-line email ("see attached") with the actual rate confirmation as a
   PDF attachment -- very common in practice, so we pull text out of any PDF
   attachments too, not just the body.

Uses only the stdlib `email` package -- no new dependency.
"""
from __future__ import annotations

import io
from email import message_from_bytes
from email.message import Message
from html.parser import HTMLParser
from pathlib import Path

from pypdf import PdfReader


class _HTMLTextExtractor(HTMLParser):
    """Minimal HTML -> text fallback for text/html-only email bodies."""

    def __init__(self):
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        self._chunks.append(data)

    def get_text(self) -> str:
        return "".join(self._chunks)


def _html_to_text(html: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(html)
    return parser.get_text()


def _decode_part(part: Message) -> str:
    payload = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _extract_pdf_attachment_text(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if not payload:
        return ""
    reader = PdfReader(io.BytesIO(payload))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_text_from_eml(path: str | Path) -> str:
    with open(path, "rb") as f:
        message = message_from_bytes(f.read())

    body_text = ""
    body_html = ""
    attachment_texts: list[str] = []

    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            disposition = part.get_content_disposition()

            if content_type == "application/pdf" or (
                disposition == "attachment" and (part.get_filename() or "").lower().endswith(".pdf")
            ):
                attachment_texts.append(_extract_pdf_attachment_text(part))
            elif content_type == "text/plain" and disposition != "attachment":
                body_text += _decode_part(part)
            elif content_type == "text/html" and disposition != "attachment":
                body_html += _decode_part(part)
    else:
        if message.get_content_type() == "text/html":
            body_html = _decode_part(message)
        else:
            body_text = _decode_part(message)

    if not body_text and body_html:
        body_text = _html_to_text(body_html)

    return "\n".join(filter(None, [body_text, *attachment_texts]))
