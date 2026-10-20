from dataclasses import dataclass, field

from core import config


@dataclass
class BotRuntimeState:
    is_paused: bool = False
    # Eventbrite-only mode: pending cards hide the Telegram publish buttons and no Instagram story is generated
    eventbrite_only: bool = field(default_factory=lambda: config.EVENTBRITE_ONLY_MODE)
    last_recap_message_id: int | None = None
    last_recap_events: list | None = None


runtime_state = BotRuntimeState()


def remember_published_recap(message_id, events):
    runtime_state.last_recap_message_id = message_id
    runtime_state.last_recap_events = events
