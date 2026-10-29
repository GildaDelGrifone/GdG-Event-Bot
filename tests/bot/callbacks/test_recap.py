import unittest
from unittest.mock import MagicMock, patch

from bot.callbacks.router import handle_callback_query
from bot.handlers.recap import handle_discussion_forward
from bot.state import runtime_state
from core.ai_parser import GeminiQuotaError
from bot.callbacks.recap import run_article_pipeline
from bot.keyboards import get_astro_publish_keyboard, get_wp_publish_keyboard
from core.db import get_article_ref_for_date, get_event, update_events_article_info, update_events_wp_info
from tests.support.config import patched_config
from tests.support.db import TempDBMixin, create_event, sample_event
from tests.support.telegram import callback_update, make_bot, make_context, make_message, make_update


class TestGeminiQuotaDepletionAlert(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def test_recap_approval_sends_admin_alert_on_quota_depleted(self):
        update, _query = callback_update("publish_recap_05-09-2026", message_id=555, text=None,
                                         caption="Recap caption")
        context = make_context()
        context.bot.copy_message.return_value = MagicMock(message_id=777)

        test_events = [sample_event(
            id=1, title="Partita di Prova", date="05-09-2026", normalized_date="05-09-2026", system="D&D",
            host="DM", description="Descrizione", image_path=None, message_link="https://t.me/c/123/456", recap=0,
        )]

        err_text = "429 Your prepayment credits are depleted."
        with patched_config(PUBLIC_CHANNEL_ID="-100111111", ARTICLE_BACKEND="wordpress"), \
             patch("bot.callbacks.recap.get_pending_events_for_recap", return_value=test_events), \
             patch("bot.callbacks.recap.generate_wordpress_article", side_effect=GeminiQuotaError(err_text)), \
             patch("bot.callbacks.recap.upload_media", return_value=None), \
             patch("bot.callbacks.recap.create_collage", return_value=None), \
             patch("bot.callbacks.recap.create_recap_story_image", return_value=None):
            await handle_callback_query(update, context)

        alert = "🚨 Errore Gemini AI (Crediti esauriti):\n429 Your prepayment credits are depleted."
        found_alert = any(call.kwargs.get("text") == alert for call in context.bot.send_message.call_args_list)
        self.assertTrue(found_alert, "Expected quota alert message was not sent during recap approval.")


class TestPublishRecap(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        saved = (runtime_state.last_recap_message_id, runtime_state.last_recap_events)
        self.addCleanup(lambda: (setattr(runtime_state, "last_recap_message_id", saved[0]),
                                 setattr(runtime_state, "last_recap_events", saved[1])))

    async def test_publish_recap_does_not_send_links_to_event_channel(self):
        update, _query = callback_update("publish_recap_05-09-2026", chat_id=9999, message_id=123, text=None,
                                         caption="Recap caption")
        context = make_context()
        context.bot.copy_message.return_value = MagicMock(message_id=777)

        test_events = [{
            "id": 1,
            "title": "Avventura D&D",
            "system": "D&D 5e",
            "status": "approved",
            "message_link": "https://t.me/c/123/456",
            "image_path": None,
        }]

        with patched_config(PUBLIC_CHANNEL_ID="-100111111", ARTICLE_BACKEND="wordpress"), \
             patch("bot.callbacks.recap.get_pending_events_for_recap", return_value=test_events), \
             patch("bot.callbacks.recap.generate_wordpress_article", return_value=None), \
             patch("bot.callbacks.recap.upload_media", return_value=None), \
             patch("bot.callbacks.recap.create_collage", return_value=None), \
             patch("bot.callbacks.recap.create_recap_story_image", return_value=None):
            await handle_callback_query(update, context)

        # The recap is copied to PUBLIC_CHANNEL_ID
        context.bot.copy_message.assert_called_once_with(chat_id="-100111111", from_chat_id=9999, message_id=123)

        # No second links message is sent to the event channel
        for call in context.bot.send_message.call_args_list:
            self.assertNotEqual(str(call.kwargs.get("chat_id")), "-100111111")

        # The published recap is remembered for the discussion group forward
        self.assertEqual(runtime_state.last_recap_message_id, 777)
        self.assertEqual(runtime_state.last_recap_events, test_events)

        # Telegram automatically forwards the recap post into the discussion group
        fwd_msg = make_message(chat_id=-100222222, message_id=888)
        fwd_msg.is_automatic_forward = True
        fwd_msg.forward_origin = MagicMock(type="channel", message_id=777)

        context.bot.send_message.reset_mock()
        await handle_discussion_forward(make_update(message=fwd_msg), context)

        # The links text is sent to the discussion group instead
        context.bot.send_message.assert_called_once()
        fwd_call = context.bot.send_message.call_args[1]
        self.assertEqual(fwd_call["chat_id"], -100222222)
        self.assertEqual(fwd_call["reply_to_message_id"], 888)
        self.assertIn("<b>Avventura D&amp;D</b>", fwd_call["text"])

    async def test_publish_recap_creates_wordpress_draft_even_if_story_photo_times_out(self):
        update, _query = callback_update("publish_recap_05-09-2026", chat_id=9999, message_id=123, text=None,
                                         caption="Recap caption")
        context = make_context()
        context.bot.copy_message.return_value = MagicMock(message_id=777)
        context.bot.send_photo.side_effect = TimeoutError("Timed out")

        test_events = [sample_event(id=1, title="Avventura D&D", image_path=None)]

        with patched_config(PUBLIC_CHANNEL_ID="-100111111", ARTICLE_BACKEND="wordpress"), \
             patch("bot.callbacks.recap.get_pending_events_for_recap", return_value=test_events), \
             patch("bot.callbacks.recap.create_collage", return_value=None), \
             patch("bot.callbacks.recap.create_recap_story_image", return_value=__file__), \
             patch("bot.callbacks.recap.generate_wordpress_article", return_value="<p>Articolo</p>") as mock_gen, \
             patch("bot.callbacks.recap.publish_article", return_value=("https://example.com/?p=10", 10)) as mock_pub, \
             patch("bot.callbacks.recap.update_events_wp_info") as mock_upd:
            await handle_callback_query(update, context)

        mock_gen.assert_called_once()
        mock_pub.assert_called_once()
        mock_upd.assert_called_once_with([1], 10, "https://example.com/?p=10")


ASTRO_EVENTS = [
    sample_event(id=1, title="Catan", image_path="/fake/catan.jpg", is_roleplay=0, status="approved"),
    sample_event(id=2, title="D&D", image_path=None, is_roleplay=1, status="approved"),
    sample_event(id=3, title="Annullata", image_path=None, is_roleplay=0, status="cancelled"),
]


class TestAstroRecap(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def _run_recap(self, backend=None, publish_result=("https://github.com/o/r/blob/serata/x/f.md", "serata/x")):
        update, _query = callback_update("publish_recap_23-10-2026", chat_id=9999, message_id=123, text=None,
                                         caption="Recap caption")
        context = make_context()
        events = [dict(ev) for ev in ASTRO_EVENTS]
        overrides = {"PUBLIC_CHANNEL_ID": None, "ASTRO_BASE_URL": "https://example.org"}
        if backend:
            overrides["ARTICLE_BACKEND"] = backend
        with patched_config(**overrides), \
             patch("bot.callbacks.recap.get_pending_events_for_recap", return_value=events), \
             patch("bot.callbacks.recap.create_collage", return_value="/fake/collage.jpg"), \
             patch("bot.callbacks.recap.create_recap_story_image", return_value=None), \
             patch("bot.callbacks.recap.astro.upload_media",
                   side_effect=lambda path, prefix: {"id": f"{prefix}/{path}", "source_url": f"https://r2/{prefix}{path}"}) as up, \
             patch("bot.callbacks.recap.generate_astro_article", return_value="Articolo **md**") as gen, \
             patch("bot.callbacks.recap.astro.publish_article", return_value=publish_result) as pub, \
             patch("bot.callbacks.recap.update_events_article_info") as upd, \
             patch("bot.callbacks.recap.upload_media") as wp_up, \
             patch("bot.callbacks.recap.generate_wordpress_article", return_value="<p>x</p>"), \
             patch("bot.callbacks.recap.update_events_wp_info"), \
             patch("bot.callbacks.recap.publish_article", return_value=("https://wp/edit", 10)) as wp_pub:
            await handle_callback_query(update, context)
        return context, up, gen, pub, upd, wp_up, wp_pub

    async def test_default_backend_is_astro_and_creates_draft_branch(self):
        context, up, gen, pub, upd, wp_up, wp_pub = await self._run_recap()

        wp_up.assert_not_called()
        wp_pub.assert_not_called()
        slug = "eventi-della-serata-venerdi-23-10-2026"
        self.assertEqual(
            [call.args for call in up.call_args_list],
            [("/fake/catan.jpg", f"serate/{slug}"), ("/fake/collage.jpg", f"serate/{slug}")],
        )
        gen.assert_called_once()
        args = pub.call_args.args
        self.assertEqual(args[0], "Eventi della Serata: Venerdì 23-10-2026")
        self.assertEqual(args[2:4], ("23-10-2026", slug))
        self.assertEqual(args[4], f"https://r2/serate/{slug}/fake/collage.jpg")
        self.assertEqual(args[6], [
            {"gioco": "Catan", "tipo": "tavolo", "immagine": f"https://r2/serate/{slug}/fake/catan.jpg"},
            {"gioco": "D&D", "tipo": "gdr"},
        ])
        upd.assert_called_once_with([1, 2, 3], "astro", "serata/x", "https://github.com/o/r/blob/serata/x/f.md")
        last = context.bot.send_message.call_args.kwargs
        self.assertEqual(last["reply_markup"].inline_keyboard[0][0].callback_data, "publish_astro_23-10-2026")
        self.assertIn(f'href="https://example.org/serate/{slug}/"', last["text"])
        self.assertNotIn("2026-10-23", last["text"])
        self.assertEqual(last["parse_mode"], "HTML")
        self.assertIs(last["disable_web_page_preview"], True)

    async def test_failed_draft_reports_error_without_storing(self):
        context, _up, _gen, _pub, upd, _wp_up, _wp_pub = await self._run_recap("astro", publish_result=(False, None))

        upd.assert_not_called()
        self.assertIn("❌", context.bot.send_message.call_args.kwargs["text"])

    async def test_wordpress_backend_does_not_touch_astro(self):
        context, up, gen, pub, _upd, wp_up, wp_pub = await self._run_recap("wordpress")

        up.assert_not_called()
        gen.assert_not_called()
        pub.assert_not_called()
        wp_pub.assert_called_once()
        self.assertTrue(wp_up.called)


class TestPublishArticle(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    async def _publish_astro(self, merged, store_ref=True):
        if store_ref:
            event_id = create_event(normalized_date="23-10-2026")
            update_events_article_info([event_id], "astro", "serata/eventi-della-serata-venerdi-23-10-2026", "link")
        update, query = callback_update("publish_astro_23-10-2026", text="Bozza creata")
        with patched_config(ASTRO_BASE_URL="https://example.org"), \
             patch("bot.callbacks.recap.astro.update_article_status", return_value=merged) as upd:
            await handle_callback_query(update, make_context())
        return upd, query.edit_message_text.call_args.kwargs["text"]

    async def test_astro_publish_merges_branch_and_shows_public_url(self):
        upd, text = await self._publish_astro(True)

        upd.assert_called_once_with("serata/eventi-della-serata-venerdi-23-10-2026", "publish")
        self.assertIn("https://example.org/serate/eventi-della-serata-venerdi-23-10-2026/", text)
        self.assertNotIn("2026-10-23", text)
        self.assertIn("Cloudflare", text)

    async def test_astro_publish_failure_shows_error(self):
        _upd, text = await self._publish_astro(False)

        self.assertIn("Errore durante la pubblicazione", text)

    async def test_astro_publish_without_stored_draft_shows_error(self):
        upd, text = await self._publish_astro(True, store_ref=False)

        upd.assert_not_called()
        self.assertIn("Errore durante la pubblicazione", text)

    async def test_wordpress_publish_still_uses_post_id(self):
        update, query = callback_update("publish_wp_10", text="Bozza")
        with patch("bot.callbacks.recap.update_article_status", return_value=True) as upd:
            await handle_callback_query(update, make_context())

        upd.assert_called_once_with(10, "publish")
        self.assertIn("PUBBLICATO", query.edit_message_text.call_args.kwargs["text"])


class TestDiscardArticle(TempDBMixin, unittest.IsolatedAsyncioTestCase):
    BRANCH = "serata/eventi-della-serata-venerdi-23-10-2026"

    async def _discard(self, data, target, outcome):
        update, query = callback_update(data, text="Bozza creata")
        with patch(target, return_value=outcome) as discard:
            await handle_callback_query(update, make_context())
        return discard, query.edit_message_text.call_args.kwargs["text"]

    def _store_astro_draft(self):
        event_id = create_event(normalized_date="23-10-2026")
        update_events_article_info([event_id], "astro", self.BRANCH, "link")
        return event_id

    async def test_astro_discard_deletes_the_branch_and_clears_the_draft(self):
        self._store_astro_draft()

        discard, text = await self._discard("discard_astro_23-10-2026", "bot.callbacks.recap.astro.discard_article", True)

        discard.assert_called_once_with(self.BRANCH)
        self.assertIn("SCARTATO", text)
        self.assertIsNone(get_article_ref_for_date("23-10-2026", "astro"))

    async def test_astro_discard_of_a_published_article_is_refused_and_keeps_the_draft_info(self):
        self._store_astro_draft()

        _discard, text = await self._discard("discard_astro_23-10-2026", "bot.callbacks.recap.astro.discard_article", "published")

        self.assertIn("già stato pubblicato", text)
        self.assertEqual(get_article_ref_for_date("23-10-2026", "astro"), self.BRANCH)

    async def test_astro_discard_error_keeps_the_draft_info(self):
        self._store_astro_draft()

        _discard, text = await self._discard("discard_astro_23-10-2026", "bot.callbacks.recap.astro.discard_article", False)

        self.assertIn("Errore", text)
        self.assertEqual(get_article_ref_for_date("23-10-2026", "astro"), self.BRANCH)

    async def test_astro_discard_without_stored_draft_shows_error(self):
        discard, text = await self._discard("discard_astro_23-10-2026", "bot.callbacks.recap.astro.discard_article", True)

        discard.assert_not_called()
        self.assertIn("Errore", text)

    async def test_wordpress_discard_trashes_the_post_and_clears_it(self):
        event_id = create_event()
        update_events_wp_info([event_id], 10, "https://wp/10")

        discard, text = await self._discard("discard_wp_10", "bot.callbacks.recap.discard_article", True)

        discard.assert_called_once_with(10)
        self.assertIn("SCARTATO", text)
        self.assertIsNone(get_event(event_id)["wp_post_id"])

    async def test_wordpress_discard_outcomes_other_than_success_keep_the_post(self):
        event_id = create_event()
        update_events_wp_info([event_id], 10, "https://wp/10")

        _d, published = await self._discard("discard_wp_10", "bot.callbacks.recap.discard_article", "published")
        _d, failed = await self._discard("discard_wp_10", "bot.callbacks.recap.discard_article", False)

        self.assertIn("già stato pubblicato", published)
        self.assertIn("Errore", failed)
        self.assertEqual(get_event(event_id)["wp_post_id"], 10)

    def test_draft_keyboards_carry_publish_and_discard_buttons(self):
        astro_row = get_astro_publish_keyboard("23-10-2026").inline_keyboard[0]
        wp_row = get_wp_publish_keyboard(10).inline_keyboard[0]

        self.assertEqual([b.callback_data for b in astro_row], ["publish_astro_23-10-2026", "discard_astro_23-10-2026"])
        self.assertEqual([b.callback_data for b in wp_row], ["publish_wp_10", "discard_wp_10"])


class TestRunArticlePipeline(unittest.IsolatedAsyncioTestCase):
    async def test_only_the_article_is_built_without_the_story(self):
        bot = make_bot()
        events = [sample_event(id=1, title="Catan", image_path=None)]
        with patched_config(ARTICLE_BACKEND="astro"), \
             patch("bot.callbacks.recap.create_collage", return_value="/fake/collage.jpg") as collage, \
             patch("bot.callbacks.recap.create_recap_story_image") as story, \
             patch("bot.callbacks.recap._create_article_draft") as draft:
            await run_article_pipeline(bot, "999", "23-10-2026", events)

        story.assert_not_called()
        collage.assert_called_once()
        draft.assert_called_once_with(bot, "999", "23-10-2026", "Venerdì", events, "/fake/collage.jpg")
        bot.send_message.assert_called_once()

if __name__ == "__main__":
    unittest.main()
