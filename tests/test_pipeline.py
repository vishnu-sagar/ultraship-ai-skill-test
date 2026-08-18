import unittest
from pathlib import Path

from extraction.pdf_utils import extract_text_from_pdf
from extraction.pipeline import extract
from extraction.schema import safe_parse

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"


class TestPipelineWithMockProvider(unittest.TestCase):
    """Runs the full pipeline offline (no API key / network) using the
    regex-based mock provider, to prove schema enforcement + validation +
    confidence scoring work end-to-end.
    """

    def test_simple_sample_extracts_cleanly(self):
        text = extract_text_from_pdf(SAMPLES_DIR / "rate_con_1_LD64392.pdf")
        result = extract(text, provider="mock")

        self.assertTrue(result.ok)
        self.assertEqual(result.data["load_id"], "LD64392")
        self.assertEqual(result.data["equipment_type"], "flatbed")
        self.assertEqual(result.data["total_rate"], 50.0)
        self.assertIn(result.data["confidence"], {"high", "medium", "low"})

    def test_unreconciled_total_flagged_not_crashed(self):
        # LD64408: Base Carrier Rate 500 + Carrier Charge 200 = Total 700, with
        # no explicit fuel_surcharge field -- must be flagged, never crash.
        text = extract_text_from_pdf(SAMPLES_DIR / "rate_con_2_LD64408.pdf")
        result = extract(text, provider="mock")

        self.assertTrue(result.ok)
        self.assertTrue(any("unaccounted_charges" in w for w in result.warnings))
        self.assertNotEqual(result.data["confidence"], "high")


class TestSchemaNeverCrashesOnMalformedInput(unittest.TestCase):
    def test_bad_enum_value_is_rejected_not_fatal(self):
        raw = {
            "load_id": "LD1",
            "origin": {"city": "Chicago", "state": "IL", "zip": None},
            "destination": {"city": "NYC", "state": "NY", "zip": None},
            "pickup_date": "2026-07-30",
            "delivery_date": "2026-08-01",
            "equipment_type": "spaceship",  # invalid enum value
            "line_haul_rate": 50.0,
            "fuel_surcharge": None,
            "total_rate": 50.0,
            "weight_lbs": 182.0,
            "commodity": "Ceramics",
        }
        model, errors = safe_parse(raw)
        self.assertIsNone(model)
        self.assertTrue(errors)

    def test_malformed_date_is_rejected_not_fatal(self):
        raw = {"pickup_date": "3/4/26"}  # not YYYY-MM-DD
        model, errors = safe_parse(raw)
        self.assertIsNone(model)
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
