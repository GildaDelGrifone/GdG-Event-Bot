"""WordPress REST API: import from core.wordpress. HTTP goes through core.wordpress.client (patch its `requests`)."""
from core.wordpress.categories import get_category_ids, resolve_category_slug_or_name
from core.wordpress.content import publish_article, update_article_status, upload_media

__all__ = [
    "get_category_ids",
    "resolve_category_slug_or_name",
    "publish_article",
    "update_article_status",
    "upload_media",
]
