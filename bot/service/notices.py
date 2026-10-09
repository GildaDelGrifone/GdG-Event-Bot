import html
import logging

from core import config
from utils.templates import format_event_title_link
from bot.common.messages import send_with_reply_fallback
from bot.service.mentions import format_subscriber_tag

logger = logging.getLogger(__name__)


def discussion_chat_id():
    """DISCUSSION_GROUP_ID as an int, or None when unset/invalid."""
    if not config.DISCUSSION_GROUP_ID:
        return None
    try:
        return int(config.DISCUSSION_GROUP_ID)
    except (ValueError, TypeError):
        return None


async def send_discussion_notice(context, event, text, label):
    """Posts to the discussion group, replying to the event's booking message when known."""
    chat_id = discussion_chat_id()
    if chat_id is None:
        return
    await send_with_reply_fallback(
        context.bot, chat_id, text, event.get('discussion_message_id'), log=logger, label=label
    )


def _admin_suffix(admin_user):
    if not admin_user:
        return ""
    if getattr(admin_user, 'username', None):
        return f" (@{admin_user.username})"
    if getattr(admin_user, 'first_name', None):
        return f" ({html.escape(admin_user.first_name)})"
    return ""


async def send_admin_action_notice(
    context,
    event,
    target_username=None,
    target_user_id=None,
    action="add",
    seats=1,
    admin_user=None,
    target_full_name=None,
):
    """Tells the discussion group that an *event* admin (not a group admin) changed someone's seats."""
    if not event or event.get('status') not in ('approved', 'cancelled'):
        return

    user_tag = format_subscriber_tag(target_username, target_full_name, target_user_id) or "Utente"
    seats_count = max(1, int(seats or 1))
    if action == "add":
        icon, verb = "✅", "Aggiunto 1 posto" if seats_count == 1 else f"Aggiunti {seats_count} posti"
    else:
        icon, verb = "❌", "Rimosso 1 posto" if seats_count == 1 else f"Rimossi {seats_count} posti"

    text = (
        f"🛠️ <b>Operazione effettuata da un admin degli eventi{_admin_suffix(admin_user)}:</b>\n"
        f"{icon} {verb} per {user_tag} per: {format_event_title_link(event)}"
    )
    await send_discussion_notice(context, event, text, label="admin action notice")
