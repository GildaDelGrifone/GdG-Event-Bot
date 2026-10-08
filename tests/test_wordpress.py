import unittest
from unittest.mock import patch, MagicMock
from core import config
from core.wordpress import (
    publish_article,
    get_category_ids,
    resolve_category_slug_or_name,
)

class TestWordPressPostCategory(unittest.TestCase):

    def setUp(self):
        self.mock_response_post = MagicMock()
        self.mock_response_post.status_code = 201
        self.mock_response_post.json.return_value = {
            "id": 123,
            "link": "https://example.com/post-123",
        }

    @patch("core.wordpress.client.requests.post")
    def test_publish_article_without_category_env(self, mock_post):
        mock_post.return_value = self.mock_response_post
        with patch.object(config, "WP_URL", "https://example.com"), \
             patch.object(config, "WP_USERNAME", "testuser"), \
             patch.object(config, "WP_APP_PASSWORD", "testpass"), \
             patch.object(config, "WP_POST_CATEGORY", None):
            
            link, post_id = publish_article("Title", "Content")
            self.assertEqual(post_id, 123)

            call_kwargs = mock_post.call_args[1]
            payload = call_kwargs.get("json", {})
            self.assertNotIn("categories", payload)

    @patch("core.wordpress.client.requests.post")
    def test_publish_article_with_empty_category_env(self, mock_post):
        mock_post.return_value = self.mock_response_post
        for empty_val in ["", "   ", None]:
            with patch.object(config, "WP_URL", "https://example.com"), \
                 patch.object(config, "WP_USERNAME", "testuser"), \
                 patch.object(config, "WP_APP_PASSWORD", "testpass"), \
                 patch.object(config, "WP_POST_CATEGORY", empty_val):
                
                link, post_id = publish_article("Title", "Content")
                self.assertEqual(post_id, 123)
                
                payload = mock_post.call_args[1].get("json", {})
                self.assertNotIn("categories", payload, f"Failed for empty_val: {empty_val}")

    @patch("core.wordpress.client.requests.post")
    def test_publish_article_with_integer_category_env(self, mock_post):
        mock_post.return_value = self.mock_response_post
        with patch.object(config, "WP_URL", "https://example.com"), \
             patch.object(config, "WP_USERNAME", "testuser"), \
             patch.object(config, "WP_APP_PASSWORD", "testpass"), \
             patch.object(config, "WP_POST_CATEGORY", "42"):
            
            link, post_id = publish_article("Title", "Content")
            self.assertEqual(post_id, 123)

            payload = mock_post.call_args[1].get("json", {})
            self.assertIn("categories", payload)
            self.assertEqual(payload["categories"], [42])

    @patch("core.wordpress.client.requests.post")
    def test_publish_article_with_comma_separated_categories(self, mock_post):
        mock_post.return_value = self.mock_response_post
        with patch.object(config, "WP_URL", "https://example.com"), \
             patch.object(config, "WP_USERNAME", "testuser"), \
             patch.object(config, "WP_APP_PASSWORD", "testpass"), \
             patch.object(config, "WP_POST_CATEGORY", "7, 15, 23"):
            
            link, post_id = publish_article("Title", "Content")
            self.assertEqual(post_id, 123)

            payload = mock_post.call_args[1].get("json", {})
            self.assertIn("categories", payload)
            self.assertEqual(payload["categories"], [7, 15, 23])

    @patch("core.wordpress.client.requests.post")
    def test_publish_article_with_explicit_category_override(self, mock_post):
        mock_post.return_value = self.mock_response_post
        with patch.object(config, "WP_URL", "https://example.com"), \
             patch.object(config, "WP_USERNAME", "testuser"), \
             patch.object(config, "WP_APP_PASSWORD", "testpass"), \
             patch.object(config, "WP_POST_CATEGORY", "42"):
            
            link, post_id = publish_article("Title", "Content", category="99")
            self.assertEqual(post_id, 123)

            payload = mock_post.call_args[1].get("json", {})
            self.assertEqual(payload["categories"], [99])

    @patch("core.wordpress.client.requests.get")
    @patch("core.wordpress.client.requests.post")
    def test_publish_article_with_category_slug_resolved(self, mock_post, mock_get):
        mock_post.return_value = self.mock_response_post
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.json.return_value = [{"id": 88, "slug": "eventi", "name": "Eventi"}]
        mock_get.return_value = mock_get_resp

        with patch.object(config, "WP_URL", "https://example.com"), \
             patch.object(config, "WP_USERNAME", "testuser"), \
             patch.object(config, "WP_APP_PASSWORD", "testpass"), \
             patch.object(config, "WP_POST_CATEGORY", "eventi"):
            
            link, post_id = publish_article("Title", "Content")
            self.assertEqual(post_id, 123)

            payload = mock_post.call_args[1].get("json", {})
            self.assertIn("categories", payload)
            self.assertEqual(payload["categories"], [88])

    @patch("core.wordpress.client.requests.get")
    @patch("core.wordpress.client.requests.post")
    def test_publish_article_with_unresolvable_category(self, mock_post, mock_get):
        mock_post.return_value = self.mock_response_post
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.json.return_value = []
        mock_get.return_value = mock_get_resp

        with patch.object(config, "WP_URL", "https://example.com"), \
             patch.object(config, "WP_USERNAME", "testuser"), \
             patch.object(config, "WP_APP_PASSWORD", "testpass"), \
             patch.object(config, "WP_POST_CATEGORY", "nonexistent_slug"):
            
            link, post_id = publish_article("Title", "Content")
            self.assertEqual(post_id, 123)

            payload = mock_post.call_args[1].get("json", {})
            self.assertNotIn("categories", payload)

    def test_publish_article_missing_credentials(self):
        with patch.object(config, "WP_URL", None), \
             patch.object(config, "WP_USERNAME", None), \
             patch.object(config, "WP_APP_PASSWORD", None):
            
            link, post_id = publish_article("Title", "Content")
            self.assertFalse(link)
            self.assertIsNone(post_id)

    def test_get_category_ids_helper(self):
        with patch.object(config, "WP_POST_CATEGORY", None), \
             patch("core.config.WP_POST_CATEGORY", None):
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

