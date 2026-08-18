"""PDF -> raw text, so the extraction pipeline can accept real PDF rate
confirmations directly (matching how brokers actually receive them), not just
pre-extracted text files.
"""
from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


def extract_text_from_pdf(path: str | Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)
