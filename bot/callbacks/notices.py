from core.db import get_reservations_for_event
from utils.templates import format_event_title_link, format_status_notice
from bot.service.mentions import format_subscriber_tag
from bot.service.notices import send_discussion_notice


def format_subscribers_tags(reservations):
    tags = []
    seen = set()
    for res in reservations:
        tag = format_subscriber_tag(res.get('username'), res.get('full_name'), res.get('user_id'))
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            tags.append(tag)
    return ", ".join(tags)


async def _send_status_notice(context, event, icon, status_word, subscribers_label):
    tags_str = format_subscribers_tags(get_reservations_for_event(event['id']))
    text = format_status_notice(icon, status_word, format_event_title_link(event), subscribers_label, tags_str)
    await send_discussion_notice(context, event, text, label=f"{status_word.lower()} notice")


async def send_cancellation_notice(context, event):
    await _send_status_notice(context, event, "⚠️", "ANNULLATO", "Iscritti avvisati")


async def send_reactivation_notice(context, event):
    await _send_status_notice(context, event, "✅", "RIATTIVATO", "Iscritti prenotati")
