import os
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from bot.event_generator.pipeline import enforce_caption_limit, process_event_generation
from tests.support.db import TempDBMixin
from tests.support.telegram import make_context

CAPTION_EVENT = {"title": "Catan", "date": "10-10-2026", "system": "Board Game", "host": "Host", "seats": "4/4"}


def generated_event(title, games):
    return {**CAPTION_EVENT, "title": title, "games": games, "normalized_date": "10-10-2026",
            "description": "Descrizione"}


class TestEnforceCaptionLimit(unittest.TestCase):
    def test_enforce_caption_limit_under_1024(self):
        ev = {**CAPTION_EVENT, "description": "Breve descrizione."}
        res = enforce_caption_limit(ev, max_length=1024)
        self.assertLessEqual(len(res), 1024)
        self.assertEqual(ev["description"], "Breve descrizione.")

    def test_enforce_caption_limit_over_1024_trims_description(self):
        long_desc = "Questa è una descrizione lunghissima! " * 40
        ev = {**CAPTION_EVENT, "description": long_desc}
        res = enforce_caption_limit(ev, max_length=1024)
        self.assertLessEqual(len(res), 1024)
        self.assertTrue(ev["description"].endswith("..."))
        self.assertLess(len(ev["description"]), len(long_desc))


class TestProcessEventGeneration(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.context = make_context()
        self.context.bot.send_photo.return_value = MagicMock(message_id=12345)

    @contextmanager
    def pipeline(self, ev_data, images, saved_name, collage_result=None):
        """Patches the AI, image lookup and file I/O of process_event_generation; yields the collage mock."""
        with patch("bot.event_generator.pipeline.generate_event_data_with_ai", return_value=ev_data), \
             patch("bot.event_generator.pipeline.fetch_bgg_game_image", side_effect=images), \
             patch("bot.event_generator.pipeline.create_collage_from_bytes", return_value=collage_result) as mock_collage, \
             patch("bot.event_generator.pipeline.save_image_locally",
                   return_value=os.path.join(self.temp_dir.name, saved_name)), \
             patch("os.path.exists", return_value=True), \
             patch("builtins.open", MagicMock()):
            yield mock_collage

    async def test_process_event_generation_passes_bgg_id_hints(self):
        ev_data = {**generated_event("Catan & Wingspan", ["Catan", "Wingspan"]), "bgg_ids": {"Catan": 13}}
        with self.pipeline(ev_data, [b"IMG_1", None], "single.jpg"), \
             patch("bot.event_generator.pipeline.fetch_bgg_game_image", side_effect=[b"IMG_1", None]) as fetch:
            await process_event_generation("Catan e Wingspan", self.context)
        self.assertCountEqual([(c.args[0], c.kwargs["bgg_id"]) for c in fetch.call_args_list],
                              [("Catan", 13), ("Wingspan", None)])

    async def test_process_event_generation_single_game_no_collage(self):
        with self.pipeline(generated_event("Catan", ["Catan"]), [b"SINGLE_IMG_BYTES"], "test.jpg") as mock_collage:
            success, _msg = await process_event_generation("Catan, 10 ottobre", self.context)
            self.assertTrue(success)
            mock_collage.assert_not_called()
            self.context.bot.send_photo.assert_called_once()

    async def test_process_event_generation_multiple_games_collaged(self):
        with self.pipeline(generated_event("Catan & Wingspan", ["Catan", "Wingspan"]), [b"IMG_1", b"IMG_2"],
                           "collage.jpg", collage_result=b"COLLAGE_BYTES") as mock_collage:
            success, _msg = await process_event_generation("Catan e Wingspan", self.context)
            self.assertTrue(success)
            mock_collage.assert_called_once()
            self.assertEqual(mock_collage.call_args[0][0], [b"IMG_1", b"IMG_2"])

    async def test_process_event_generation_multiple_games_single_image_no_collage(self):
        with self.pipeline(generated_event("Catan & UnfindableGame", ["Catan", "UnfindableGame"]), [b"IMG_1", None],
                           "single.jpg") as mock_collage:
            success, _msg = await process_event_generation("prompt", self.context)
            self.assertTrue(success)
            mock_collage.assert_not_called()


if __name__ == "__main__":
    unittest.main()
