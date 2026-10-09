from core.db import get_reservations_for_event
from utils.templates import format_event_title_link
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
    text = f"{icon} <b>ATTENZIONE:</b> L'evento {format_event_title_link(event)} è stato <b>{status_word}</b>!"
    tags_str = format_subscribers_tags(get_reservations_for_event(event['id']))
    if tags_str:
        text += f"\n\n{subscribers_label}: {tags_str}"
    await send_discussion_notice(context, event, text, label=f"{status_word.lower()} notice")


async def send_cancellation_notice(context, event):
    await _send_status_notice(context, event, "⚠️", "ANNULLATO", "Iscritti avvisati")


async def send_reactivation_notice(context, event):
    await _send_status_notice(context, event, "✅", "RIATTIVATO", "Iscritti prenotati")
