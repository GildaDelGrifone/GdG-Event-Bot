import logging

from core import config
from core.wordpress.client import site_credentials, wp_get

logger = logging.getLogger(__name__)


def _positive_int(value):
    """int(value) when value is a positive int or a digit string, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
        return number if number > 0 else None
    return None


def resolve_category_slug_or_name(category_str):
    """Numeric WordPress category ID for a slug or name, via the REST API; None if not found."""
    creds = site_credentials()
    if not creds:
        logger.warning(f"WordPress credentials not configured to resolve category: {category_str}")
        return None
    base_url, headers = creds
    wanted = category_str.strip().lower()

    try:
        resp = wp_get(base_url, headers, "categories", params={'slug': category_str})
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and data:
                return data[0].get('id')

        resp = wp_get(base_url, headers, "categories", params={'search': category_str})
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                for cat in data:
                    if wanted in (cat.get('name', '').strip().lower(), cat.get('slug', '').strip().lower()):
                        return cat.get('id')

        logger.warning(f"Could not resolve WordPress category: {category_str}")
        return None
    except Exception as e:
        logger.error(f"Error resolving WordPress category '{category_str}': {e}")
        return None


def get_category_ids(category_input=None):
    """IDs from an int, a list, or comma-separated IDs/slugs/names (default: WP_POST_CATEGORY); None if none resolve."""
    target = category_input if category_input is not None else config.WP_POST_CATEGORY
    if target is None:
        return None

    if isinstance(target, (int, list, tuple)):
        items = target if isinstance(target, (list, tuple)) else [target]
        ids = [n for n in (_positive_int(item) for item in items) if n]
        return ids or None

    parts = [p.strip() for p in str(target).split(',') if p.strip()]
    ids = []
    for part in parts:
        if part.isdigit():
            if int(part) > 0:
                ids.append(int(part))
            continue
        cat_id = resolve_category_slug_or_name(part)
        if cat_id:
            ids.append(cat_id)
    return ids or None
