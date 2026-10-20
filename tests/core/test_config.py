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


if __name__ == "__main__":
    unittest.main()
