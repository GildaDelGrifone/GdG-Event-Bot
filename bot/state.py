from dataclasses import dataclass, field

from core import config


@dataclass
class BotRuntimeState:
    is_paused: bool = False
    # Eventbrite-only mode: pending cards hide the Telegram publish buttons and no Instagram story is generated
    eventbrite_only: bool = field(default_factory=lambda: config.EVENTBRITE_ONLY_MODE)
    # Venue picked with /bot_eventbrite_venue for new Eventbrite events (None = the default venue)
    eventbrite_venue: str | None = None
    venue_names: dict = field(default_factory=dict)
    # Eventbrite publishes running in the background: the tasks (kept so they are not garbage collected) and the
    # event ids in flight (a second press for the same event is refused)
    eventbrite_tasks: set = field(default_factory=set)
    eventbrite_publishing: set = field(default_factory=set)
    last_recap_message_id: int | None = None
    last_recap_events: list | None = None


runtime_state = BotRuntimeState()


def remember_published_recap(message_id, events):
    runtime_state.last_recap_message_id = message_id
    runtime_state.last_recap_events = events
