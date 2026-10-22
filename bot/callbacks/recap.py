import asyncio
import logging
from datetime import datetime

from core import config
from core.ai_parser import generate_wordpress_article, GeminiQuotaError
from core.db import get_pending_events_for_recap, update_events_wp_info
from core.wordpress import publish_article, upload_media, update_article_status
from utils.date_utils import DAYS_IT
from utils.image_utils import create_collage, create_recap_story_image
from utils.templates.recap import recap_generate_text
from utils.templates.wordpress import (
    ARTICLE_PUBLISHED_SUFFIX, ARTICLE_PUBLISH_ERROR_SUFFIX, RECAP_DISCARDED_SUFFIX, RECAP_PUBLISHED_SUFFIX,
    RECAP_STORY_CAPTION, RECAP_STORY_ERROR, WORDPRESS_CREATE_ERROR, WORDPRESS_DRAFT_PROGRESS,
    format_wordpress_draft_created,
)
from bot.common.auth import describe_user
from bot.common.messages import send_image_or_error
from bot.common.previews import notify_quota_depleted
from bot.keyboards import get_wp_publish_keyboard
from bot.state import remember_published_recap

logger = logging.getLogger(__name__)


async def _append_to_card(query, suffix):
    try:
        await query.edit_message_caption(caption=f"{query.message.caption}{suffix}")
    except Exception:
        await query.edit_message_text(text=f"{query.message.text}{suffix}")


def _recap_day_name(date_str):
    try:
        day = datetime.strptime(date_str, "%d-%m-%Y")
    except ValueError:
        day = datetime.now()
    return DAYS_IT[day.weekday()]


async def _generate_article(bot, chat_id, recap_text, events):
    try:
        return await asyncio.to_thread(generate_wordpress_article, recap_text, events)
    except GeminiQuotaError as e:
        await notify_quota_depleted(bot, chat_id, e, "WP article generation")
        return None


async def _create_wordpress_draft(bot, chat_id, date_str, day_str, events, collage_path):
    for ev in events:
        if ev.get('image_path'):
            media_info = await asyncio.to_thread(upload_media, ev['image_path'])
            if media_info:
                ev['wp_media_url'] = media_info.get('source_url')

    wp_content = await _generate_article(bot, chat_id, recap_generate_text(day_str, date_str, events), events)
    if not wp_content:
        return

    collage_info = await asyncio.to_thread(upload_media, collage_path) if collage_path else None
    media_id = collage_info.get('id') if collage_info else None

    wp_link, post_id = await asyncio.to_thread(publish_article, f"Eventi della Serata: {day_str} {date_str}", wp_content, media_id=media_id)
    if not (wp_link and post_id):
        await bot.send_message(chat_id=chat_id, text=WORDPRESS_CREATE_ERROR)
        return

    update_events_wp_info([ev['id'] for ev in events], post_id, wp_link)
    await bot.send_message(
        chat_id=chat_id,
        text=format_wordpress_draft_created(wp_link),
        reply_markup=get_wp_publish_keyboard(post_id),
    )


async def _run_post_recap_pipeline(bot, chat_id, date_str, events):
    """Recap Instagram story preview, then the WordPress draft article."""
    await bot.send_message(chat_id=chat_id, text=WORDPRESS_DRAFT_PROGRESS)
    day_str = _recap_day_name(date_str)

    collage_path = await asyncio.to_thread(create_collage, [ev['image_path'] for ev in events if ev.get('image_path')], config.DATA_DIR, date_str)
    story_path = await asyncio.to_thread(create_recap_story_image, events, collage_path, date_str, config.DATA_DIR)
    await send_image_or_error(
        bot, chat_id, story_path,
        caption=RECAP_STORY_CAPTION,
        error_text=RECAP_STORY_ERROR,
    )
    await _create_wordpress_draft(bot, chat_id, date_str, day_str, events, collage_path)


async def handle_publish_recap(query, context, date_str):
    await query.answer()
    logger.info(f"{describe_user(query.from_user)} approved and published recap for date {date_str}.")
    events = get_pending_events_for_recap(date_str)

    if config.PUBLIC_CHANNEL_ID:
        pub_msg = await context.bot.copy_message(
            chat_id=config.PUBLIC_CHANNEL_ID, from_chat_id=query.message.chat_id, message_id=query.message.message_id
        )
        if pub_msg:
            remember_published_recap(pub_msg.message_id, events)

    await _append_to_card(query, RECAP_PUBLISHED_SUFFIX)

    if events:
        await _run_post_recap_pipeline(context.bot, query.message.chat_id, date_str, events)


async def handle_discard_recap(query, context, payload):
    await query.answer()
    logger.info(f"{describe_user(query.from_user)} discarded recap.")
    await _append_to_card(query, RECAP_DISCARDED_SUFFIX)


async def handle_publish_wordpress(query, context, payload):
    await query.answer()
    post_id = int(payload)
    admin_identifier = describe_user(query.from_user)

    if await asyncio.to_thread(update_article_status, post_id, "publish"):
        logger.info(f"{admin_identifier} published WordPress article #{post_id}.")
        suffix = ARTICLE_PUBLISHED_SUFFIX
    else:
        logger.warning(f"{admin_identifier} failed to publish WordPress article #{post_id}.")
        suffix = ARTICLE_PUBLISH_ERROR_SUFFIX
    try:
        await query.edit_message_text(text=f"{query.message.text}{suffix}")
    except Exception:
        pass
