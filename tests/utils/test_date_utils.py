import unittest
from datetime import date, datetime

from utils.date_utils import format_standard_event_date, parse_user_date, validate_event_date_anomalies


class TestDateUtils(unittest.TestCase):
    def test_parse_user_date_valid(self):
        cases = [
            ("05-09-2026", datetime(2026, 9, 5, 0, 0), False),  # without time (dash)
            ("5/9/2026", datetime(2026, 9, 5, 0, 0), False),  # without time (slash, single digits)
            ("05-09-2026 21:30", datetime(2026, 9, 5, 21, 30), True),  # with time (dash)
            ("05/09/2026 20:00", datetime(2026, 9, 5, 20, 0), True),  # with time (slash)
        ]
        for text, expected, expected_has_time in cases:
            with self.subTest(text=text):
                dt, has_time = parse_user_date(text)
                self.assertEqual(dt, expected)
                self.assertEqual(has_time, expected_has_time)

    def test_parse_user_date_invalid(self):
        # Free text, unsupported keyword, 31 Feb, month 13, hour 25, empty, None
        for text in ["invalid_date_text", "tomorrow", "31-02-2026", "05-13-2026", "05-09-2026 25:00", "", None]:
            with self.subTest(text=text):
                self.assertIsNone(parse_user_date(text))

    def test_parse_user_date_keywords(self):
        ref_dt = datetime(2026, 10, 7, 10, 0)  # Wednesday (weekday 2)
        cases = [
            ("oggi", ref_dt, datetime(2026, 10, 7, 0, 0), False),
            ("oggi 21:00", ref_dt, datetime(2026, 10, 7, 21, 0), True),
            ("MER", ref_dt, datetime(2026, 10, 14, 0, 0), False),  # today is Wednesday -> next Wednesday
            ("VEN 21:30", ref_dt, datetime(2026, 10, 9, 21, 30), True),  # this Friday
            ("LUN", ref_dt, datetime(2026, 10, 12, 0, 0), False),  # next Monday
            ("LUN", datetime(2026, 10, 5, 12, 0), datetime(2026, 10, 12, 0, 0), False),  # Monday -> +7 days
        ]
        for text, reference, expected, expected_has_time in cases:
            with self.subTest(text=text, reference=reference):
                dt, has_time = parse_user_date(text, reference_date=reference)
                self.assertEqual(dt, expected)
                self.assertEqual(has_time, expected_has_time)

    def test_format_standard_event_date(self):
        # Sept 5, 2026 is Saturday (Sabato)
        disp, norm = format_standard_event_date(datetime(2026, 9, 5, 21, 0), has_time=True)
        self.assertEqual(disp, "Sabato 05-09-2026 21:00")
        self.assertEqual(norm, "05-09-2026")

        # Sept 4, 2026 is Friday (Venerdì)
        disp2, norm2 = format_standard_event_date(datetime(2026, 9, 4, 0, 0), has_time=False)
        self.assertEqual(disp2, "Venerdì 04-09-2026")
        self.assertEqual(norm2, "04-09-2026")

    def test_validate_event_date_anomalies_future_valid(self):
        # Sept 4, 2026 is Friday
        ev = {"date": "Venerdì 04-09-2026 21:00", "normalized_date": "04-09-2026"}
        self.assertEqual(validate_event_date_anomalies(ev, reference_date=date(2026, 9, 1)), [])

    def test_validate_event_date_anomalies_past_date(self):
        ev = {"date": "Lunedì 01-01-2024", "normalized_date": "01-01-2024"}
        warnings = validate_event_date_anomalies(ev, reference_date=date(2026, 9, 1))
        self.assertTrue(any("PASSATO" in w for w in warnings))

    def test_validate_event_date_anomalies_weekday_mismatch_italian(self):
        # Sept 4, 2026 is Friday, but the date string says 'Sabato'
        ev = {"date": "Sabato 04-09-2026 21:00", "normalized_date": "04-09-2026"}
        warnings = validate_event_date_anomalies(ev, reference_date=date(2026, 9, 1))
        self.assertTrue(any("Incongruenza data/giorno" in w for w in warnings))
        self.assertTrue(any("Sabato" in w and "Venerdì" in w for w in warnings))

    def test_validate_event_date_anomalies_weekday_mismatch_english(self):
        # Sept 4, 2026 is Friday, but the date string says 'Saturday'
        ev = {"date": "Saturday 04 September 2026", "normalized_date": "04-09-2026"}
        warnings = validate_event_date_anomalies(ev, reference_date=date(2026, 9, 1))
        self.assertTrue(any("Incongruenza data/giorno" in w for w in warnings))
        self.assertTrue(any("Sabato" in w and "Venerdì" in w for w in warnings))

    def test_validate_event_date_anomalies_unparseable(self):
        warnings = validate_event_date_anomalies({"date": "data da definirsi", "normalized_date": ""})
        self.assertTrue(any("Impossibile determinare una data valida" in w for w in warnings))


class TestUserDateKeywords(unittest.TestCase):
    def test_date_utils_keywords_oggi_and_days(self):
        ref_dt = datetime(2026, 10, 7, 10, 0)  # a Wednesday
        cases = [
            # (input, reference, expected datetime or date, has_time)
            ("oggi", ref_dt, date(2026, 10, 7), False),
            ("oggi 21:00", ref_dt, datetime(2026, 10, 7, 21, 0), True),
            ("MER", ref_dt, date(2026, 10, 14), False),  # today is Wednesday -> next Wednesday
            ("VEN 20:45", ref_dt, datetime(2026, 10, 9, 20, 45), True),  # this Friday
            ("LUN", ref_dt, date(2026, 10, 12), False),  # next Monday
            ("LUN", datetime(2026, 10, 5, 14, 0), date(2026, 10, 12), False),  # Monday + "LUN" -> next Monday
        ]
        for text, reference, expected, expected_has_time in cases:
            with self.subTest(text=text, reference=reference):
                dt, has_time = parse_user_date(text, reference_date=reference)
                self.assertEqual(dt if isinstance(expected, datetime) else dt.date(), expected)
                self.assertEqual(has_time, expected_has_time)


if __name__ == "__main__":
    unittest.main()
