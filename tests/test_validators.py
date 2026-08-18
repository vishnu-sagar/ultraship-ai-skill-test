import unittest

from extraction.equipment import normalize_equipment_type
from extraction.validators import (
    check_conflicting_totals,
    find_missing_fields,
    find_unverified_locations,
    is_ambiguous_date_string,
)


class TestConflictingTotals(unittest.TestCase):
    def test_matching_total_is_fine(self):
        data = {"line_haul_rate": 1200.0, "fuel_surcharge": 150.0, "total_rate": 1350.0}
        self.assertIsNone(check_conflicting_totals(data))

    def test_hard_conflict_when_fuel_surcharge_present(self):
        # line haul + fuel != total, and we DO have a fuel figure -> real conflict
        data = {"line_haul_rate": 1200.0, "fuel_surcharge": 100.0, "total_rate": 1500.0}
        self.assertEqual(check_conflicting_totals(data), "conflicting_totals")

    def test_soft_flag_when_fuel_surcharge_missing(self):
        # sample LD64408: Base Carrier Rate 500 + Carrier Charge 200 = Total 700,
        # but there is no explicit fuel_surcharge line so we can't call it a hard conflict.
        data = {"line_haul_rate": 500.0, "fuel_surcharge": None, "total_rate": 700.0}
        self.assertEqual(check_conflicting_totals(data), "unaccounted_charges")

    def test_no_flag_when_total_missing(self):
        data = {"line_haul_rate": 500.0, "fuel_surcharge": None, "total_rate": None}
        self.assertIsNone(check_conflicting_totals(data))


class TestMissingFields(unittest.TestCase):
    def test_detects_missing_nested_field(self):
        data = {"origin": {"city": None, "state": "IL"}, "load_id": "LD1"}
        missing = find_missing_fields(data, ["origin.city", "origin.state", "load_id"])
        self.assertEqual(missing, ["origin.city"])


class TestAmbiguousDates(unittest.TestCase):
    def test_ambiguous_numeric_date(self):
        self.assertTrue(is_ambiguous_date_string("3/4/26"))

    def test_unambiguous_when_day_over_12(self):
        self.assertFalse(is_ambiguous_date_string("07/30/2026"))

    def test_unambiguous_month_name(self):
        self.assertFalse(is_ambiguous_date_string("28-Jul-2026"))


class TestEquipmentNormalization(unittest.TestCase):
    def test_known_synonym_mapped(self):
        self.assertEqual(normalize_equipment_type("Dry Van"), "van")
        self.assertEqual(normalize_equipment_type("Refrigerated"), "reefer")
        self.assertEqual(normalize_equipment_type("Step Deck"), "flatbed")

    def test_already_valid_enum_passthrough(self):
        self.assertEqual(normalize_equipment_type("flatbed"), "flatbed")

    def test_unrecognized_value_becomes_other_not_crash(self):
        self.assertEqual(normalize_equipment_type("Conestoga Wagon Deluxe"), "other")

    def test_null_stays_null(self):
        self.assertIsNone(normalize_equipment_type(None))


class TestUnverifiedLocations(unittest.TestCase):
    def test_city_present_in_text_is_verified(self):
        data = {"origin": {"city": "Chicago"}, "destination": {"city": "New York"}}
        text = "Pickup in Chicago, IL. Drop in New York, NY."
        self.assertEqual(find_unverified_locations(data, text), [])

    def test_hallucinated_city_flagged(self):
        data = {"origin": {"city": "Chicago"}, "destination": {"city": "Atlantis"}}
        text = "Pickup in Chicago, IL. Drop in New York, NY."
        self.assertEqual(find_unverified_locations(data, text), ["destination"])


if __name__ == "__main__":
    unittest.main()
