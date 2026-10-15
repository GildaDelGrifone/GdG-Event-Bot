from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from core import config
from tests.support.telegram import ADMIN_CHAT_ID


@contextmanager
def patched_config(**values):
    """Temporarily overrides core.config attributes, e.g. patched_config(ADMIN_CHAT_ID="999", DATA_DIR=tmp)."""
    with ExitStack() as stack:
        for name, value in values.items():
            if not hasattr(config, name):
                raise AttributeError(f"core.config has no setting {name}")
            stack.enter_context(patch.object(config, name, value))
        yield


def as_admin_chat(**extra):
    """patched_config with ADMIN_CHAT_ID matching tests.support.telegram.admin_update()."""
    return patched_config(ADMIN_CHAT_ID=ADMIN_CHAT_ID, **extra)


@contextmanager
def wordpress_credentials(url="https://example.com", username="testuser", password="testpass", category=None):
    with patched_config(WP_URL=url, WP_USERNAME=username, WP_APP_PASSWORD=password, WP_POST_CATEGORY=category):
        yield
