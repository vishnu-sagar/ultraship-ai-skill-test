import unittest
from pathlib import Path

from extraction.email_utils import extract_text_from_eml

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"


class TestEmailBodyExtraction(unittest.TestCase):
    def test_plain_text_body_is_extracted(self):
        text = extract_text_from_eml(SAMPLES_DIR / "rate_con_5_email_body.eml")
        self.assertIn("LD70001", text)
        self.assertIn("Columbus, OH", text)


class TestEmailPdfAttachmentExtraction(unittest.TestCase):
    def test_pdf_attachment_text_is_pulled_in(self):
        text = extract_text_from_eml(SAMPLES_DIR / "rate_con_6_email_with_pdf_attachment.eml")
        # the body only says "see attached" -- the load details must come from the PDF
        self.assertIn("LD64407", text)
        self.assertIn("please see the attached", text.lower())


if __name__ == "__main__":
    unittest.main()
