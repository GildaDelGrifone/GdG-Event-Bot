import unittest
from unittest.mock import patch

from core.db.connection import db_safe


class TestDbSafe(unittest.TestCase):
    def test_returns_fresh_default_and_logs(self):
        @db_safe(default=list)
        def broken():
            raise RuntimeError("boom")

        with patch("core.db.connection.logger") as log:
            first, second = broken(), broken()
        self.assertEqual(first, [])
        self.assertIsNot(first, second)
        self.assertIn("broken", log.error.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
