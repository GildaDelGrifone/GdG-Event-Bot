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


class TestEnvChoice(unittest.TestCase):
    def choice(self, value):
        with patch.dict("os.environ", {} if value is None else {"ARTICLE_BACKEND": value}, clear=True):
            return config._env_choice("ARTICLE_BACKEND", ("astro", "wordpress"), "astro")

    def test_default_when_unset(self):
        self.assertEqual(self.choice(None), "astro")

    def test_valid_values_are_case_insensitive(self):
        self.assertEqual(self.choice("WordPress"), "wordpress")
        self.assertEqual(self.choice(" astro "), "astro")

    def test_invalid_value_falls_back_and_warns(self):
        with self.assertLogs("core.config", level="WARNING") as logs:
            self.assertEqual(self.choice("drupal"), "astro")
        self.assertIn("ARTICLE_BACKEND", logs.output[0])


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


class TestEnvNumbers(unittest.TestCase):
    def test_valid_and_invalid_values(self):
        with patch.dict("os.environ", {"N": " 7 ", "F": "2.5", "BAD": "abc"}, clear=True):
            self.assertEqual(config._env_int("N", 0), 7)
            self.assertEqual(config._env_float("F", 4.0), 2.5)
            self.assertEqual(config._env_int("BAD", 3), 3)
            self.assertEqual(config._env_float("BAD", 4.0), 4.0)
            self.assertEqual(config._env_int("UNSET", 5), 5)


class TestEnvWeekdays(unittest.TestCase):
    def days(self, value):
        with patch.dict("os.environ", {} if value is None else {"DAYS": value}, clear=True):
            return config._env_weekdays("DAYS", "0,2,4")

    def test_default_when_unset(self):
        self.assertEqual(self.days(None), frozenset({0, 2, 4}))

    def test_valid_value_is_parsed(self):
        self.assertEqual(self.days(" 1, 3 ,6"), frozenset({1, 3, 6}))

    def test_an_invalid_value_falls_back_to_the_default(self):
        for value in ("mon", "7", "", "1,,x"):
            with self.subTest(value=value):
                self.assertEqual(self.days(value), frozenset({0, 2, 4}))


class TestRequiredSettings(unittest.TestCase):
    def test_lists_unset_required_settings(self):
        with patch.object(config, "TELEGRAM_BOT_TOKEN", None), patch.object(config, "ADMIN_CHAT_ID", "-100"):
            self.assertEqual(config.missing_required_settings(), ["TELEGRAM_BOT_TOKEN"])
        with patch.object(config, "TELEGRAM_BOT_TOKEN", "t"), patch.object(config, "ADMIN_CHAT_ID", "-100"):
            self.assertEqual(config.missing_required_settings(), [])


if __name__ == "__main__":
    unittest.main()
