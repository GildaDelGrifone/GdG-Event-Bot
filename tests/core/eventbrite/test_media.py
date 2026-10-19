import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core.eventbrite import EventbriteError
from core.eventbrite.media import upload_logo
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
        self.assertNotIn("headers", kwargs)  # pre-signed URL: no Authorization header

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


if __name__ == "__main__":
    unittest.main()
