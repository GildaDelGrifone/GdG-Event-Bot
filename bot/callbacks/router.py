from telegram import Update
from telegram.ext import ContextTypes

from bot.callbacks import booking, events, recap, schedule, subscribers, venues

# Ordered (prefix, handler) pairs; each handler receives (query, context, payload-after-prefix).
CALLBACK_ROUTES = (
    ("publish_event_", events.handle_publish_event),
    ("publish_eb_event_", events.handle_publish_event_with_eventbrite),
    ("publish_eb_only_", events.handle_publish_eventbrite_only),
    ("eb_publish_", events.handle_eventbrite_publish),
    ("eb_recreate_", events.handle_eventbrite_recreate),
    ("eb_cancel_retry_", events.handle_eventbrite_cancel_retry),
    ("eb_logo_", events.handle_eventbrite_logo_retry),
    ("eb_cancel_ask_", events.handle_eventbrite_cancel_ask),
    ("eb_cancel_do_", events.handle_eventbrite_cancel_do),
    ("ebvenue_close", venues.handle_venue_close),
    ("ebvenue_", venues.handle_venue_pick),
    ("discard_event_", events.handle_discard_event),
    ("cancel_event_", events.handle_cancel_event),
    ("cancel_confirm_", events.handle_cancel_confirm),
    ("cancel_abort_", events.handle_cancel_abort),
    ("reactivate_event_", events.handle_reactivate_event),
    ("publish_recap_", recap.handle_publish_recap),
    ("discard_recap_", recap.handle_discard_recap),
    ("publish_wp_", recap.handle_publish_wordpress),
    ("publish_astro_", recap.handle_publish_astro),
    ("discard_wp_", recap.handle_discard_wordpress),
    ("discard_astro_", recap.handle_discard_astro),
    ("full_", booking.handle_full),
    ("book_", booking.handle_book),
    ("unbook_", booking.handle_unbook),
    ("manage_subs_", subscribers.handle_manage_subs),
    ("sub_inc_", subscribers.handle_seat_increment),
    ("sub_dec_", subscribers.handle_seat_decrement),
    ("sub_addnew_", subscribers.handle_add_subscriber_prompt),
    ("close_subs_", subscribers.handle_close_panel),
    ("sched_toggle_", schedule.handle_toggle_day),
    ("sched_adv_", schedule.handle_advance_days),
    ("sched_del_", schedule.handle_delete_schedule),
    ("sched_close_", schedule.handle_close_schedule),
)


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    for prefix, handler in CALLBACK_ROUTES:
        if data.startswith(prefix):
            await handler(query, context, data[len(prefix):])
            return
