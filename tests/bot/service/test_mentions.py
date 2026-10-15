import unittest

from bot.service.mentions import format_subscriber_tag


class TestSubscriberTag(unittest.TestCase):
    def test_tag_rules(self):
        self.assertEqual(format_subscriber_tag("@mario"), "@mario")
        self.assertEqual(format_subscriber_tag(None, "Mario <R>", 5), '<a href="tg://user?id=5">Mario &lt;R&gt;</a>')
        self.assertEqual(format_subscriber_tag("Mario Rossi", None, 5), '<a href="tg://user?id=5">Mario Rossi</a>')
        self.assertEqual(format_subscriber_tag(None, None, 5), '<a href="tg://user?id=5">Utente</a>')
        self.assertEqual(format_subscriber_tag(None, "Anna", None), "Anna")
        self.assertIsNone(format_subscriber_tag(None, None, None))


if __name__ == "__main__":
    unittest.main()
