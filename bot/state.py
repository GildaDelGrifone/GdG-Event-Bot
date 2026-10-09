from dataclasses import dataclass


@dataclass
class BotRuntimeState:
    is_paused: bool = False
    last_recap_message_id: int | None = None
    last_recap_events: list | None = None


runtime_state = BotRuntimeState()


def remember_published_recap(message_id, events):
    runtime_state.last_recap_message_id = message_id
    runtime_state.last_recap_events = events
