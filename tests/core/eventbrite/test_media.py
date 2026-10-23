import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core.eventbrite import EventbriteError
import requests

from core.eventbrite.media import short_reason, upload_logo
from tests.support.config import eventbrite_credentials
from tests.support.images import image_file

UPLOAD_TARGET = {
    "upload_url": "https://upload.example.com/post", "upload_data": {"key": "k"},
    "file_parameter_name": "file", "upload_token": "tok",
}


class TestUploadLogo(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.path = image_file(temp_dir.name, "logo.jpg", 300, 600)

    @patch("core.eventbrite.media.eb_post", return_value={"id": "media-1"})
    @patch("core.eventbrite.media.requests.post")
    @patch("core.eventbrite.media.eb_get", return_value=UPLOAD_TARGET)
    def test_three_step_flow_with_a_2_to_1_crop(self, mock_get, mock_upload, mock_post):
        mock_upload.return_value = MagicMock(status_code=204)
        with eventbrite_credentials():
            self.assertEqual(upload_logo(self.path), "media-1")

        mock_get.assert_called_once_with("/media/upload/", params={"type": "image-event-logo"})
        args, kwargs = mock_upload.call_args
        self.assertEqual(args[0], "https://upload.example.com/post")
        self.assertEqual(kwargs["data"], {"key": "k"})
        self.assertIn("file", kwargs["files"])
        self.assertNotIn("Authorization", kwargs["headers"])  # pre-signed URL: no Authorization header
        self.assertTrue(kwargs["headers"]["User-Agent"].startswith("Mozilla/5.0"))

        path, body = mock_post.call_args.args[0], mock_post.call_args.kwargs["json"]
        self.assertEqual(path, "/media/upload/")
        self.assertEqual(body["upload_token"], "tok")
        crop = body["crop_mask"]
        self.assertEqual(crop["top_left"], {"x": 0, "y": 0})
        self.assertEqual(crop["width"], 2 * crop["height"])
        self.assertGreaterEqual(crop["width"], 2160)

    @patch("core.eventbrite.media.pad_to_aspect")
    @patch("core.eventbrite.media.eb_post")
    @patch("core.eventbrite.media.requests.post", return_value=MagicMock(status_code=403, text="denied"))
    @patch("core.eventbrite.media.eb_get", return_value=UPLOAD_TARGET)
    def test_failed_upload_raises_and_removes_the_temp_file(self, _get, _upload, mock_post, mock_pad):
        from utils.image_utils import pad_to_aspect
        temp_paths = []

        def real_pad(*args, **kwargs):
            temp_paths.append(pad_to_aspect(*args, **kwargs))
            return temp_paths[-1]

        mock_pad.side_effect = real_pad
        with eventbrite_credentials(), self.assertRaises(EventbriteError) as ctx:
            upload_logo(self.path)
        self.assertEqual(ctx.exception.error, "UPLOAD_FAILED")
        mock_post.assert_not_called()
        self.assertFalse(os.path.exists(temp_paths[0]))


WAF_PAGE = '<html lang="en">\n<!-- WAF -->\n<head>\n<meta charset="utf-8" />\n<title>Whoops!</title>\n<style>body{}</style>'


def refusal(status, text="", retry_after=None):
    headers = {} if retry_after is None else {"Retry-After": str(retry_after)}
    return MagicMock(status_code=status, text=text, headers=headers)


class TestUploadRetries(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.path = image_file(temp_dir.name, "logo.jpg", 300, 600)
        self.padded = []
        from utils.image_utils import pad_to_aspect

        def tracking_pad(*args, **kwargs):
            self.padded.append(pad_to_aspect(*args, **kwargs))
            return self.padded[-1]

        patchers = {
            "get": patch("core.eventbrite.media.eb_get", return_value=UPLOAD_TARGET),
            "post": patch("core.eventbrite.media.eb_post", return_value={"id": "media-1"}),
            "upload": patch("core.eventbrite.media.requests.post"),
            "sleep": patch("core.eventbrite.media.time.sleep"),
            "pad": patch("core.eventbrite.media.pad_to_aspect", side_effect=tracking_pad),
        }
        self.m = {name: patcher.start() for name, patcher in patchers.items()}
        self.addCleanup(patch.stopall)

    def run_upload(self):
        with eventbrite_credentials():
            return upload_logo(self.path)

    def test_a_waf_429_is_retried_with_a_fresh_upload_target(self):
        self.m["upload"].side_effect = [refusal(429, WAF_PAGE), refusal(429, WAF_PAGE), MagicMock(status_code=204)]

        self.assertEqual(self.run_upload(), "media-1")

        self.assertEqual(self.m["upload"].call_count, 3)
        self.assertEqual(self.m["get"].call_count, 3)  # a new upload_token for every attempt
        self.assertEqual([c.args[0] for c in self.m["sleep"].call_args_list], [3, 8])
        self.assertEqual(len(self.padded), 1)  # the image is padded once, not per attempt
        self.assertFalse(os.path.exists(self.padded[0]))

    def test_retries_on_server_errors_and_network_errors(self):
        for failure in (refusal(502), refusal(503), refusal(504), requests.ConnectionError("down"), requests.Timeout("slow")):
            with self.subTest(failure=failure):
                self.m["upload"].reset_mock()
                self.m["upload"].side_effect = [failure, MagicMock(status_code=204)]
                self.assertEqual(self.run_upload(), "media-1")
                self.assertEqual(self.m["upload"].call_count, 2)

    def test_retries_when_the_final_registration_step_hits_a_server_error(self):
        self.m["upload"].return_value = MagicMock(status_code=204)
        self.m["post"].side_effect = [EventbriteError(503, "HTTP_503", ""), {"id": "media-2"}]
        self.assertEqual(self.run_upload(), "media-2")
        self.assertEqual(self.m["get"].call_count, 2)

    def test_gives_up_after_three_attempts_with_a_short_readable_error(self):
        self.m["upload"].return_value = refusal(429, WAF_PAGE)

        with self.assertRaises(EventbriteError) as ctx:
            self.run_upload()

        self.assertEqual(self.m["upload"].call_count, 3)
        self.assertEqual((ctx.exception.status_code, ctx.exception.error, ctx.exception.description),
                         (429, "UPLOAD_FAILED", "Whoops!"))
        self.assertNotIn("<", str(ctx.exception))
        self.assertFalse(os.path.exists(self.padded[0]))

    def test_other_client_errors_are_not_retried(self):
        for status in (400, 401, 403, 404, 413):
            with self.subTest(status=status):
                self.m["upload"].reset_mock()
                self.m["upload"].return_value = refusal(status, "denied")
                with self.assertRaises(EventbriteError):
                    self.run_upload()
                self.assertEqual(self.m["upload"].call_count, 1)
        self.m["sleep"].assert_not_called()

    def test_retry_after_is_honored_and_capped(self):
        self.m["upload"].side_effect = [refusal(429, "", retry_after=4), refusal(429, "", retry_after=600),
                                        MagicMock(status_code=204)]
        self.run_upload()
        self.assertEqual([c.args[0] for c in self.m["sleep"].call_args_list], [4, 15])

    def test_unparseable_retry_after_falls_back_to_the_default_delay(self):
        self.m["upload"].side_effect = [refusal(429, "", retry_after="Wed, 21 Oct 2026 07:28:00 GMT"),
                                        MagicMock(status_code=204)]
        self.run_upload()
        self.assertEqual([c.args[0] for c in self.m["sleep"].call_args_list], [3])

    def test_the_temp_file_is_removed_even_for_unexpected_errors(self):
        self.m["get"].side_effect = RuntimeError("bug")
        with self.assertRaises(RuntimeError):
            self.run_upload()
        self.assertFalse(os.path.exists(self.padded[0]))


class TestShortReason(unittest.TestCase):
    def test_reasons(self):
        self.assertEqual(short_reason(WAF_PAGE), "Whoops!")
        self.assertEqual(short_reason("<p>Too   many\nrequests</p>"), "Too many requests")
        self.assertEqual(short_reason("plain text"), "plain text")
        self.assertEqual(short_reason(None), "")
        long = short_reason("x" * 500)
        self.assertEqual(len(long), 120)
        self.assertTrue(long.endswith("…"))


if __name__ == "__main__":
    unittest.main()
