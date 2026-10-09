import logging
import mimetypes
import os

from core.wordpress.categories import get_category_ids
from core.wordpress.client import site_credentials, wp_post

logger = logging.getLogger(__name__)

_SUCCESS = (200, 201)


def upload_media(filepath):
    """Uploads a file to the Media Library; returns {'id', 'source_url'} or None."""
    creds = site_credentials()
    if not creds:
        logger.warning("WordPress credentials not fully configured for media upload.")
        return None
    base_url, headers = creds

    filename = os.path.basename(filepath)
    headers = {**headers, 'Content-Disposition': f'attachment; filename="{filename}"'}
    content_type, _ = mimetypes.guess_type(filepath)
    if content_type:
        headers['Content-Type'] = content_type

    try:
        logger.info(f"WordPress: Uploading media file '{filename}'...")
        with open(filepath, 'rb') as f:
            media_data = f.read()
        response = wp_post(base_url, headers, "media", data=media_data)
        if response.status_code not in _SUCCESS:
            logger.error(f"WordPress: Failed to upload media '{filename}': {response.status_code} - {response.text}")
            return None
        resp_json = response.json()
        media_id = resp_json.get('id')
        logger.info(f"WordPress: Image '{filename}' uploaded successfully (Media ID: {media_id}).")
        return {'id': media_id, 'source_url': resp_json.get('source_url')}
    except Exception as e:
        logger.error(f"WordPress: Error uploading media '{filename}': {e}")
        return None


def publish_article(title, content, media_id=None, category=None):
    """Creates a draft post; returns (edit_link, post_id) or (False, None)."""
    creds = site_credentials()
    if not creds:
        logger.warning("WordPress credentials not fully configured.")
        return False, None
    base_url, headers = creds

    data = {'title': title, 'content': content, 'status': 'draft'}
    if media_id:
        data['featured_media'] = media_id
    category_ids = get_category_ids(category)
    if category_ids:
        data['categories'] = category_ids

    try:
        logger.info(f"WordPress: Publishing article '{title}' (media_id={media_id})...")
        response = wp_post(base_url, headers, "posts", json=data)
        if response.status_code not in _SUCCESS:
            logger.error(f"WordPress: Failed to publish article '{title}': {response.status_code} - {response.text}")
            return False, None
        post_id = response.json().get('id')
        logger.info(f"WordPress: Article '{title}' published successfully as draft (Post ID: {post_id}).")
        return f"{base_url}/wp-admin/post.php?post={post_id}&action=edit", post_id
    except Exception as e:
        logger.error(f"WordPress: Error publishing article '{title}': {e}")
        return False, None


def update_article_status(post_id, status='publish'):
    creds = site_credentials()
    if not creds:
        logger.warning("WordPress credentials not fully configured.")
        return False
    base_url, headers = creds

    try:
        response = wp_post(base_url, headers, f"posts/{post_id}", json={'status': status})
        if response.status_code not in _SUCCESS:
            logger.error(f"WordPress: Failed to update article {post_id} status to '{status}': {response.status_code} - {response.text}")
            return False
        logger.info(f"WordPress: Article {post_id} status updated to '{status}'.")
        return True
    except Exception as e:
        logger.error(f"WordPress: Error updating article {post_id} status to '{status}': {e}")
        return False
