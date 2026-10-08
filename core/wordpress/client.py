import base64
import logging

import requests

from core import config

logger = logging.getLogger(__name__)

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
REQUEST_TIMEOUT = 30


def site_credentials():
    """(base_url, auth_headers) from config, or None when the WordPress credentials are incomplete."""
    if not (config.WP_URL and config.WP_USERNAME and config.WP_APP_PASSWORD):
        return None
    token = base64.b64encode(f"{config.WP_USERNAME}:{config.WP_APP_PASSWORD}".encode()).decode("utf-8")
    return config.WP_URL.rstrip('/'), {'Authorization': f'Basic {token}', 'User-Agent': USER_AGENT}


def api_url(base_url, path):
    return f"{base_url}/wp-json/wp/v2/{path}"


def wp_get(base_url, headers, path, params=None, timeout=10):
    return requests.get(api_url(base_url, path), headers=headers, params=params, timeout=timeout)


def wp_post(base_url, headers, path, **kwargs):
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    return requests.post(api_url(base_url, path), headers=headers, **kwargs)
