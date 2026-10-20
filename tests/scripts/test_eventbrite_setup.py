import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from core.eventbrite.client import EventbriteError
from scripts.eventbrite_setup import main
from tests.support.config import eventbrite_credentials, patched_config


def run(*argv):
    out = io.StringIO()
    with redirect_stdout(out):
        code = main(list(argv))
    return code, out.getvalue()


class TestEventbriteSetupScript(unittest.TestCase):
    def test_requires_an_action(self):
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()):
            main([])

    def test_create_venue_requires_name_and_address(self):
        with self.assertRaises(SystemExit), patch("sys.stderr", io.StringIO()):
            main(["--create-venue"])

    def test_missing_token_fails_without_network(self):
        with patched_config(EVENTBRITE_TOKEN=None), patch("scripts.eventbrite_setup.eb_get") as mock_get:
            code, out = run("--check")
        self.assertEqual(code, 1)
        self.assertIn("EVENTBRITE_TOKEN", out)
        mock_get.assert_not_called()

    @patch("scripts.eventbrite_setup.paginate")
    @patch("scripts.eventbrite_setup.eb_get", return_value={"id": "7", "name": "Mario Rossi"})
    def test_check_and_orgs(self, _get, mock_paginate):
        mock_paginate.return_value = iter([{"id": "111", "name": "Gilda"}])
        with eventbrite_credentials():
            code, out = run("--check", "--orgs")
        self.assertEqual(code, 0)
        self.assertIn("Mario Rossi", out)
        self.assertIn("111\tGilda", out)

    @patch("scripts.eventbrite_setup.paginate")
    def test_venues_uses_the_configured_organization(self, mock_paginate):
        mock_paginate.return_value = iter([{"id": "v1", "name": "Sede", "address": {"localized_address_display": "Via X"}}])
        with eventbrite_credentials():
            code, out = run("--venues")
        self.assertEqual(code, 0)
        self.assertIn("v1\tSede\tVia X", out)
        self.assertEqual(mock_paginate.call_args.args[0], "/organizations/org1/venues/")

    @patch("scripts.eventbrite_setup.create_collection", return_value={"id": "55", "name": "Giochi di ruolo", "absolute_url": "https://eb/cc/x"})
    @patch("scripts.eventbrite_setup.paginate")
    def test_create_collection_prints_its_id(self, mock_paginate, mock_create):
        mock_paginate.return_value = iter([{"id": "o1", "name": "Gilda"}])
        with eventbrite_credentials():
            code, out = run("--create-collection", "Giochi di ruolo")
        self.assertEqual(code, 0)
        mock_create.assert_called_once_with("Giochi di ruolo", "o1")
        self.assertIn("ID collezione: 55", out)

    def test_venues_without_organization_fails(self):
        with eventbrite_credentials(EVENTBRITE_ORGANIZATION_ID=None):
            code, out = run("--venues")
        self.assertEqual(code, 1)
        self.assertIn("--orgs", out)

    @patch("scripts.eventbrite_setup.eb_post", return_value={"id": "v9", "name": "Gilda"})
    def test_create_venue_prints_the_env_line(self, mock_post):
        with eventbrite_credentials():
            code, out = run("--create-venue", "--name", "Gilda", "--address", "Via Ada Negri 8/A",
                            "--postal-code", "10135", "--org", "orgX")
        self.assertEqual(code, 0)
        self.assertIn("EVENTBRITE_VENUE_ID=v9", out)
        self.assertEqual(mock_post.call_args.args[0], "/organizations/orgX/venues/")
        self.assertEqual(mock_post.call_args.kwargs["json"]["venue"]["address"], {
            "address_1": "Via Ada Negri 8/A", "city": "Torino", "postal_code": "10135", "country": "IT"})

    @patch("scripts.eventbrite_setup.eb_get", side_effect=EventbriteError(401, "INVALID_AUTH", "bad token"))
    def test_api_errors_exit_non_zero(self, _get):
        with eventbrite_credentials():
            code, out = run("--check")
        self.assertEqual(code, 1)
        self.assertIn("INVALID_AUTH", out)


if __name__ == "__main__":
    unittest.main()
