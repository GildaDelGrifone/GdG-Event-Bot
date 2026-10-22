import unittest
from unittest.mock import patch

from core import config


class TestLogLevel(unittest.TestCase):
    def level(self, value):
        with patch.dict("os.environ", {} if value is None else {"LOG_LEVEL": value}, clear=True):
            return config._env_log_level("LOG_LEVEL")

    def test_default_is_info(self):
        self.assertEqual(self.level(None), "INFO")

    def test_level_names_are_case_insensitive(self):
        self.assertEqual(self.level("debug"), "DEBUG")
        self.assertEqual(self.level(" Warning "), "WARNING")

    def test_an_unknown_value_falls_back_to_info(self):
        self.assertEqual(self.level("verbose"), "INFO")


class TestEnvTime(unittest.TestCase):
    def time(self, value):
        with patch.dict("os.environ", {} if value is None else {"JOB_TIME": value}, clear=True):
            return config._env_time("JOB_TIME", "16:00")

    def test_default_when_unset(self):
        self.assertEqual(self.time(None), (16, 0))

    def test_valid_value_is_parsed(self):
        self.assertEqual(self.time(" 7:05 "), (7, 5))

    def test_an_invalid_value_falls_back_to_the_default(self):
        for value in ("25:00", "10:60", "abc", "10", "", "10:30:00"):
            with self.subTest(value=value):
                self.assertEqual(self.time(value), (16, 0))


if __name__ == "__main__":
    unittest.main()
