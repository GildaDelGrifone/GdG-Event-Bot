import html
import logging
import os
import uuid

from telegram import Update
from telegram.ext import ContextTypes

from core import config
from core.db import (
    get_event,
    insert_scheduled_event,
    get_scheduled_event,
    get_all_scheduled_events,
    update_scheduled_event_specific_date,
    update_scheduled_event_content,
)
from utils.date_utils import parse_user_date, format_standard_event_date
from utils.templates import REPOST_UPDATE_REMINDER, format_schedule_repost_message
from bot.common.auth import admin_only, describe_user
from bot.common.messages import command_argument, command_tokens, reply_in_chunks, resolve_message
from bot.common.parsing import extract_event_id_from_reply
from bot.handlers.repost import extract_repost_content
from bot.keyboards import get_schedule_repost_keyboard

logger = logging.getLogger(__name__)


def _save_scheduled_image(image_bytes):
    if not image_bytes:
        return None
    sched_dir = os.path.join(config.DATA_DIR, "scheduled")
    os.makedirs(sched_dir, exist_ok=True)
    path = os.path.join(sched_dir, f"sched_{uuid.uuid4().hex[:8]}.jpg")
    try:
        with open(path, "wb") as f:
            f.write(image_bytes)
        return path
    except Exception as e:
        logger.error(f"Error saving scheduled image: {e}")
        return None


def _scheduled_title(text, target_msg):
    ev_id = extract_event_id_from_reply(target_msg)
    ev = get_event(ev_id) if ev_id else None
    if ev and ev.get('title'):
        return ev['title']
    return text.strip().split("\n")[0][:50]


async def _reply_schedule_card(message, sched_ev, prefix=""):
    kb = get_schedule_repost_keyboard(sched_ev['id'], sched_ev.get('schedule_days'))
    await message.reply_text(prefix + format_schedule_repost_message(sched_ev), reply_markup=kb, parse_mode="HTML")


@admin_only(notify=True)
async def event_repost_schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = resolve_message(update)
    if not message:
        return

    args_str = command_argument(message)
    tokens = args_str.split()

    # "/event_repost_schedule <ID> [DATE]" manages an existing schedule
    if tokens and tokens[0].isdigit():
        sched_id = int(tokens[0])
        sched_ev = get_scheduled_event(sched_id)
        if sched_ev:
            if len(tokens) == 1:
                await _reply_schedule_card(message, sched_ev)
                return
            parsed = parse_user_date(" ".join(tokens[1:]))
            if not parsed:
                await message.reply_text("❌ Formato data non valido per la programmazione specifica.")
                return
            formatted_d, _ = format_standard_event_date(*parsed)
            update_scheduled_event_specific_date(sched_id, formatted_d)
            await _reply_schedule_card(message, get_scheduled_event(sched_id), prefix="✅ Data specifica aggiornata!\n\n")
            return

    if not message.reply_to_message:
        await message.reply_text(
            "❌ Rispondi al messaggio dell'evento che vuoi programmare per il repost.\n"
            "Uso: <code>/event_repost_schedule [DATA HH:MM]</code>\n"
            "Esempi:\n"
            "• <code>/event_repost_schedule</code> (mostra i giorni di apertura)\n"
            "• <code>/event_repost_schedule 09-10-2026 21:00</code>",
            parse_mode="HTML"
        )
        return

    text, image_bytes, target_msg = await extract_repost_content(update)
    if not text:
        await message.reply_text("❌ Nessun testo trovato nel messaggio risposto.")
        return

    specific_date_val = None
    if args_str:
        parsed = parse_user_date(args_str)
        if not parsed:
            await message.reply_text("❌ Formato data specifica non valido. Usa DD-MM-YYYY [HH:MM] o oggi/LUN/MER/VEN.")
            return
        specific_date_val, _ = format_standard_event_date(*parsed)

    saved_img_path = _save_scheduled_image(image_bytes)
    scheduled_id = insert_scheduled_event(
        title=_scheduled_title(text, target_msg),
        text=text,
        image_path=saved_img_path,
        schedule_days=[],
        specific_date=specific_date_val
    )
    if not scheduled_id:
        await message.reply_text("❌ Errore durante il salvataggio della programmazione nel database.")
        return

    msg_text = format_schedule_repost_message(get_scheduled_event(scheduled_id))
    kb = get_schedule_repost_keyboard(scheduled_id, [])

    if saved_img_path and os.path.exists(saved_img_path):
        try:
            with open(saved_img_path, "rb") as f:
                await message.reply_photo(photo=f, caption=msg_text, reply_markup=kb, parse_mode="HTML")
                return
        except Exception as e:
            logger.warning(f"Failed to send scheduled event preview photo: {e}")

    await message.reply_text(msg_text, reply_markup=kb, parse_mode="HTML")


@admin_only(notify=True)
async def event_repost_update_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = resolve_message(update)
    if not message:
        return

    if not message.reply_to_message:
        await message.reply_text(
            "❌ Rispondi al messaggio dell'evento con cui vuoi aggiornare la programmazione.\n"
            "Uso: <code>/event_repost_update SCHEDULED_ID</code> (es. <code>/event_repost_update 1</code>)",
            parse_mode="HTML"
        )
        return

    tokens = command_tokens(message)
    if not tokens or not tokens[0].isdigit():
        await message.reply_text("❌ Specifica l'ID dell'evento programmato da aggiornare (es. /event_repost_update 1).")
        return

    sched_id = int(tokens[0])
    if not get_scheduled_event(sched_id):
        await message.reply_text(f"❌ Evento programmato #{sched_id} non trovato.")
        return

    text, image_bytes, target_msg = await extract_repost_content(update)
    if not text:
        await message.reply_text("❌ Nessun testo trovato nel messaggio risposto.")
        return

    ok = update_scheduled_event_content(
        sched_id,
        text=text,
        image_path=_save_scheduled_image(image_bytes),
        title=_scheduled_title(text, target_msg),
    )
    if ok:
        await message.reply_text(
            f"✅ Evento programmato #{sched_id} aggiornato con successo con il nuovo contenuto!",
            parse_mode="HTML"
        )
    else:
        await message.reply_text("❌ Errore durante l'aggiornamento nel database.")


@admin_only(notify=True)
async def event_repost_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = resolve_message(update)
    if not message:
        return

    logger.info(f"{describe_user(update.effective_user)} requested scheduled reposts list (/event_repost_list).")

    all_events = get_all_scheduled_events()
    if not all_events:
        await message.reply_text("📋 Nessun evento programmato per il repost nel database.")
        return

    lines = [f"📋 <b>Eventi programmati per il reposting ({len(all_events)}):</b>\n"]
    for ev in all_events:
        sched_id = ev['id']
        days = ev.get('schedule_days') or []
        lines.append(
            f"• <b>{html.escape(ev.get('title') or 'Evento')}</b> (ID #{sched_id})\n"
            f"  🗓️ Giorni: {', '.join(days) if days else 'Nessuno'} | Data: {ev.get('specific_date') or 'Nessuna'}\n"
            f"  👉 Invia per preparare il post: <code>/event_repost_invoke {sched_id}</code>\n"
            f"  ⚙️ Gestisci programmazione: <code>/event_repost_schedule {sched_id}</code>\n"
        )
    lines.append(REPOST_UPDATE_REMINDER)

    await reply_in_chunks(message, lines, limit=4000, parse_mode="HTML")
