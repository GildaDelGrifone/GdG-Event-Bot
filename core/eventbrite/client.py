import logging

import requests

from core import config

logger = logging.getLogger(__name__)

API_BASE = "https://www.eventbriteapi.com/v3"
REQUEST_TIMEOUT = 30


class EventbriteError(Exception):
    """An Eventbrite API refusal. Branch on `.error` (the API's error constant, e.g. HIT_RATE_LIMIT), never on the description."""

    def __init__(self, status_code, error, description=""):
        self.status_code = status_code
        self.error = error
        self.description = description
        super().__init__(f"Eventbrite {status_code} {error}: {description}")


def eventbrite_enabled():
    """True when token, organization ID and venue ID are all set; every button and hook checks this."""
    return bool(config.EVENTBRITE_TOKEN and config.EVENTBRITE_ORGANIZATION_ID and config.EVENTBRITE_VENUE_ID)


def _headers():
    return {"Authorization": f"Bearer {config.EVENTBRITE_TOKEN}"}


def _json_or_empty(response):
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _check(response):
    if 200 <= response.status_code < 300:
        return _json_or_empty(response)
    body = _json_or_empty(response)
    raise EventbriteError(
        response.status_code,
        body.get("error") or f"HTTP_{response.status_code}",
        body.get("error_description") or "",
    )


def eb_get(path, params=None):
    return _check(requests.get(f"{API_BASE}{path}", headers=_headers(), params=params, timeout=REQUEST_TIMEOUT))


def eb_delete(path, json=None):
    kwargs = {} if json is None else {"json": json}
    return _check(requests.delete(f"{API_BASE}{path}", headers=_headers(), timeout=REQUEST_TIMEOUT, **kwargs))


def eb_post(path, json=None):
    return _check(requests.post(f"{API_BASE}{path}", headers=_headers(), json=json, timeout=REQUEST_TIMEOUT))


def paginate(path, params, key):
    """Yields every item of `key` across pages, following `continuation` while has_more_items is true."""
    params = dict(params or {})
    while True:
        data = eb_get(path, dict(params))
        yield from data.get(key) or []
        pagination = data.get("pagination") or {}
        if not (pagination.get("has_more_items") and pagination.get("continuation")):
            return
        params["continuation"] = pagination["continuation"]
