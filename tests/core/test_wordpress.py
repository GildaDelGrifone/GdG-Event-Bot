import unittest
from unittest.mock import MagicMock, patch

from core.wordpress import get_category_ids, publish_article, update_article_status, upload_media
from tests.support.config import patched_config, wordpress_credentials


def _response(status_code, json_value=None):
    response = MagicMock(status_code=status_code)
    response.json.return_value = json_value
    return response


class TestWordPressPostCategory(unittest.TestCase):
    def setUp(self):
        post_patch = patch("core.wordpress.client.requests.post", return_value=_response(201, {"id": 123, "link": "https://example.com/post-123"}))
        get_patch = patch("core.wordpress.client.requests.get", return_value=_response(200, []))
        self.mock_post = post_patch.start()
        self.mock_get = get_patch.start()
        self.addCleanup(post_patch.stop)
        self.addCleanup(get_patch.stop)

    def _publish(self, category_env, **kwargs):
        """Publishes with WP_POST_CATEGORY=category_env; returns (post_id, JSON payload sent to WordPress)."""
        with wordpress_credentials(category=category_env):
            _link, post_id = publish_article("Title", "Content", **kwargs)
        return post_id, self.mock_post.call_args[1].get("json", {})

    def test_publish_article_without_category_env(self):
        post_id, payload = self._publish(None)
        self.assertEqual(post_id, 123)
        self.assertNotIn("categories", payload)

    def test_publish_article_with_empty_category_env(self):
        for empty_val in ["", "   ", None]:
            with self.subTest(empty_val=empty_val):
                post_id, payload = self._publish(empty_val)
                self.assertEqual(post_id, 123)
                self.assertNotIn("categories", payload, f"Failed for empty_val: {empty_val}")

    def test_publish_article_with_integer_category_env(self):
        post_id, payload = self._publish("42")
        self.assertEqual(post_id, 123)
        self.assertIn("categories", payload)
        self.assertEqual(payload["categories"], [42])

    def test_publish_article_with_comma_separated_categories(self):
        post_id, payload = self._publish("7, 15, 23")
        self.assertEqual(post_id, 123)
        self.assertIn("categories", payload)
        self.assertEqual(payload["categories"], [7, 15, 23])

    def test_publish_article_with_explicit_category_override(self):
        post_id, payload = self._publish("42", category="99")
        self.assertEqual(post_id, 123)
        self.assertEqual(payload["categories"], [99])

    def test_publish_article_with_category_slug_resolved(self):
        self.mock_get.return_value = _response(200, [{"id": 88, "slug": "eventi", "name": "Eventi"}])
        post_id, payload = self._publish("eventi")
        self.assertEqual(post_id, 123)
        self.assertIn("categories", payload)
        self.assertEqual(payload["categories"], [88])

    def test_publish_article_with_unresolvable_category(self):
        post_id, payload = self._publish("nonexistent_slug")
        self.assertEqual(post_id, 123)
        self.assertNotIn("categories", payload)

    def test_publish_article_missing_credentials(self):
        with patched_config(WP_URL=None, WP_USERNAME=None, WP_APP_PASSWORD=None):
            link, post_id = publish_article("Title", "Content")
        self.assertFalse(link)
        self.assertIsNone(post_id)

    def test_get_category_ids_helper(self):
        with patched_config(WP_POST_CATEGORY=None):
            self.assertIsNone(get_category_ids(None))
            self.assertIsNone(get_category_ids(""))
            self.assertIsNone(get_category_ids("   "))
            self.assertIsNone(get_category_ids(0))
            self.assertIsNone(get_category_ids("0"))
            self.assertEqual(get_category_ids(10), [10])
            self.assertEqual(get_category_ids("10"), [10])
            self.assertEqual(get_category_ids(" 10 "), [10])
            self.assertEqual(get_category_ids("10, 20"), [10, 20])
            self.assertEqual(get_category_ids([10, "20"]), [10, 20])


class TestWordPressClient(unittest.TestCase):
    def test_wordpress_logging(self):
        with patch("core.wordpress.client.requests.post", return_value=_response(200)), \
             wordpress_credentials(username="admin", password="pass"), \
             patch("core.wordpress.content.logger") as mock_logger:
            self.assertTrue(update_article_status(1234, "publish"))
        info_calls = [c[0][0] for c in mock_logger.info.call_args_list]
        self.assertTrue(any("1234" in msg and "publish" in msg for msg in info_calls))

    def test_posts_carry_timeout_and_auth(self):
        with wordpress_credentials(url="https://example.com/", username="u", password="p"), \
             patch("core.wordpress.client.requests.post", return_value=_response(200)) as post:
            self.assertTrue(update_article_status(7, "publish"))
        self.assertEqual(post.call_args.args[0], "https://example.com/wp-json/wp/v2/posts/7")
        self.assertIn("timeout", post.call_args.kwargs)
        self.assertTrue(post.call_args.kwargs["headers"]["Authorization"].startswith("Basic "))

    def test_missing_credentials_short_circuit(self):
        with patched_config(WP_URL=None), patch("core.wordpress.client.requests.post") as post:
            self.assertIsNone(upload_media("/nope.jpg"))
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
