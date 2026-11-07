"""Event listings shared by /event_next and /event_mine, and the /event_mine view with its private-chat buttons."""
import html

from core import config
from utils.templates.event import format_event_seats
from utils.templates.public import format_event_mine_entry, format_event_mine_prefix, format_event_next_subscribers_link
from bot.common.messages import private_chat_link
from bot.keyboards import get_event_mine_keyboard

# Longest /event_mine text sent as one message with buttons (Telegram's limit is 4096)
MY_BOOKINGS_SINGLE_MESSAGE_LIMIT = 3800


def event_links(ev, bot_username):
    links = []
    if ev.get('admin_message_id'):
        links.append(private_chat_link(config.ADMIN_CHAT_ID, ev['admin_message_id'], "Admin", "Admin msg"))

    disc_msg_id = ev.get('discussion_message_id')
    disc_chat = ev.get('discussion_chat_id') or config.DISCUSSION_GROUP_ID or ''
    if disc_msg_id and str(disc_chat):
        links.append(private_chat_link(disc_chat, disc_msg_id, "Chat Discussione", "Chat msg"))

    if ev.get('message_link'):
        links.append(f'<a href="{ev["message_link"]}">Canale Eventi</a>')

    links.append(format_event_next_subscribers_link(format_event_seats(ev), bot_username, ev['id']))
    return links


def event_title_and_date(ev):
    return (
        html.escape(ev.get('title') or 'Senza Titolo'),
        html.escape(ev.get('date') or ev.get('normalized_date') or 'N/A'),
    )


def format_event_mine_entry_for(ev, bot_username):
    escaped_title, escaped_date = event_title_and_date(ev)
    return format_event_mine_entry(ev['id'], escaped_title, escaped_date, ev['my_seats'], event_links(ev, bot_username))


def render_my_bookings(events, bot_username):
    """(text, keyboard) of /event_mine as one message with a release/calendar row per event, or None if too long."""
    text = format_event_mine_prefix() + "".join(format_event_mine_entry_for(ev, bot_username) + "\n" for ev in events)
    if len(text) > MY_BOOKINGS_SINGLE_MESSAGE_LIMIT:
        return None
    return text, get_event_mine_keyboard(events)
