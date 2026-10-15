import unittest
from unittest.mock import MagicMock

import core.db as db
from bot.common.parsing import contains_event_keywords, extract_event_id_from_reply, parse_seats_input
from tests.support.db import TempDBMixin, create_event
from tests.support.telegram import make_message


def plain_message(text=None, caption=None, message_id=9999):
    message = make_message(text=text, caption=caption, message_id=message_id)
    message.reply_markup = None
    return message


class TestParseSeatsInput(unittest.TestCase):
    def test_unlimited_tokens(self):
        for token in ["null", "Nessuno", "illimitati", "unlimited", "none", "0", "", "  "]:
            with self.subTest(token=token):
                self.assertIsNone(parse_seats_input(token), token)

    def test_free_over_total(self):
        self.assertEqual(parse_seats_input("2/4"), (2, 4))
        self.assertEqual(parse_seats_input(" 3 / 5 "), (3, 5))

    def test_total_only(self):
        self.assertEqual(parse_seats_input("4"), (None, 4))

    def test_invalid(self):
        for token in ["abc", "x/4", "2/"]:
            with self.subTest(token=token), self.assertRaises(ValueError):
                parse_seats_input(token)


class TestKeywordPreFilter(unittest.TestCase):
    def test_keywords_with_colon(self):
        # Case insensitive and optional space before colon
        colon_keywords = ["Titolo", "Posti liberi", "Posti", "Descrizione", "Sinossi", "SInossi", "Gioco", "Quando", "Data"]
        for kw in colon_keywords:
            with self.subTest(keyword=kw):
                self.assertTrue(contains_event_keywords(f"Ecco il post: {kw}: Valore dell'evento"),
                                f"Failed to match without space: {kw}:")
                self.assertTrue(contains_event_keywords(f"Ecco il post: {kw} : Valore dell'evento"),
                                f"Failed to match with space: {kw} :")
                self.assertTrue(contains_event_keywords(f"{kw.lower()}: valore"),
                                f"Failed to match lowercase: {kw.lower()}:")
                self.assertTrue(contains_event_keywords(f"{kw.upper()}: VALORE"),
                                f"Failed to match uppercase: {kw.upper()}:")

    def test_phrase_keywords(self):
        for phrase in ["Gioco da tavolo", "Gioco di ruolo", "Oneshot", "One shot", "One-shot"]:
            with self.subTest(phrase=phrase):
                text = f"Venite a provare questo fantastico {phrase} venerdì sera!"
                self.assertTrue(contains_event_keywords(text), f"Failed to match phrase: {phrase}")
                self.assertTrue(contains_event_keywords(text.lower()),
                                f"Failed to match lowercase phrase: {phrase.lower()}")
                self.assertTrue(contains_event_keywords(text.upper()),
                                f"Failed to match uppercase phrase: {phrase.upper()}")

    def test_negative_cases(self):
        non_event_texts = [
            "Avviso importante: domani la sede rimarrà chiusa per festività.",
            "Ricordate di pagare la quota associativa entro fine mese!",
            "Ciao a tutti, ci vediamo presto in associazione.",
            "Numero partecipanti: 4",
            "",
            None,
        ]
        for text in non_event_texts:
            with self.subTest(text=text):
                self.assertFalse(contains_event_keywords(text), f"Should not have matched: {text}")


class TestExtractEventIdFromReply(TempDBMixin, unittest.TestCase):
    def test_extract_event_id_from_reply_various_formats(self):
        # 1. Button callback formats
        for callback_data in ["publish_event_42", "cancel_event_42", "book_42", "unbook_42", "manage_subs_42", "sub_inc_42_1"]:
            with self.subTest(callback_data=callback_data):
                msg = make_message(message_id=9999)
                msg.reply_markup.inline_keyboard = [[MagicMock(callback_data=callback_data)]]
                self.assertEqual(extract_event_id_from_reply(msg), 42)

        # 2. Caption/text regex
        self.assertEqual(extract_event_id_from_reply(plain_message(text="Modifica per evento #42")), 42)
        self.assertEqual(extract_event_id_from_reply(plain_message(caption="#42 Dettagli tavolo")), 42)

        # 3. DB admin_message_id
        event_id = create_event(original_text="test text", title="Old Event", host="Old Host", description="Old Desc")
        db.update_event_field(event_id, "admin_message_id", 8888)
        msg_admin = plain_message(text="Messaggio admin senza riferimenti", message_id=8888)
        self.assertEqual(extract_event_id_from_reply(msg_admin), event_id)


if __name__ == "__main__":
    unittest.main()
