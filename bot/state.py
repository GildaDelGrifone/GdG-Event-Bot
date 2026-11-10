from dataclasses import dataclass, field

import logging

from core import config
from core.db import clear_settings, get_setting, set_setting

logger = logging.getLogger(__name__)

# Runtime switches saved in the bot_settings table, so a restart keeps them
PERSISTED_SETTINGS = ("is_paused", "eventbrite_only", "eventbrite_venue", "eventbrite_booking_notifications")


@dataclass
class BotRuntimeState:
    is_paused: bool = False
    # Eventbrite-only mode: pending cards hide the Telegram publish buttons and no Instagram story is generated
    eventbrite_only: bool = field(default_factory=lambda: config.EVENTBRITE_ONLY_MODE)
    # Venue picked with /bot_eventbrite_venue for new Eventbrite events (None = the default venue)
    eventbrite_venue: str | None = None
    # /bot_eb_notif_toggle: announce Eventbrite bookings/releases (seats sync either way)
    eventbrite_booking_notifications: bool = field(default_factory=lambda: config.EVENTBRITE_BOOKING_NOTIFICATIONS)
    venue_names: dict = field(default_factory=dict)
    # Eventbrite publishes running in the background: the tasks (kept so they are not garbage collected) and the
    # event ids in flight (a second press for the same event is refused)
    eventbrite_tasks: set = field(default_factory=set)
    eventbrite_publishing: set = field(default_factory=set)
    # ✏️ Modifica prompts waiting for the admin's reply: prompt message id -> (event_id, command, admin card message)
    edit_prompts: dict = field(default_factory=dict)
    last_recap_message_id: int | None = None
    last_recap_events: list | None = None
    # Day (dd-mm-yyyy) the open-seats reminder was last posted, so the recap path and the daily job never both send it
    open_seats_sent_on: str | None = None


runtime_state = BotRuntimeState()


EDIT_PROMPTS_KEPT = 50


def remember_edit_prompt(prompt_message_id, event_id, command, card_message):
    prompts = runtime_state.edit_prompts
    prompts[prompt_message_id] = (event_id, command, card_message)
    while len(prompts) > EDIT_PROMPTS_KEPT:
        prompts.pop(next(iter(prompts)))


def load_persisted_state():
    """Called once at startup: restores the saved switches; a switch never set keeps its default (env value)."""
    for name in PERSISTED_SETTINGS:
        setattr(runtime_state, name, get_setting(name, getattr(runtime_state, name)))
    logger.info("Runtime state restored: " + ", ".join(f"{n}={getattr(runtime_state, n)!r}" for n in PERSISTED_SETTINGS))


def set_persisted(name, value):
    """Changes a persisted switch in memory and in the database."""
    setattr(runtime_state, name, value)
    if not set_setting(name, value):
        logger.warning(f"Could not save {name}={value!r}: it will be lost on restart.")


def reset_persisted_state():
    """/bot_settings_clear: deletes the saved switches and puts them back to their defaults (env values).
    Returns False when the database could not be cleared (the switches are reset in memory anyway)."""
    cleared = clear_settings()
    defaults = BotRuntimeState()
    for name in PERSISTED_SETTINGS:
        setattr(runtime_state, name, getattr(defaults, name))
    if not cleared:
        logger.warning("Could not clear bot_settings: the saved switches will come back on restart.")
    logger.info("Persisted settings reset: " + ", ".join(f"{n}={getattr(runtime_state, n)!r}" for n in PERSISTED_SETTINGS))
    return cleared


def remember_published_recap(message_id, events):
    runtime_state.last_recap_message_id = message_id
    runtime_state.last_recap_events = events
