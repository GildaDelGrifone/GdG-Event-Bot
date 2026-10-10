import os
import logging
from telegram import Update, BotCommand, BotCommandScopeDefault, BotCommandScopeChat
from telegram.error import NetworkError
from telegram.ext import ContextTypes

from telegram.ext import Application, MessageHandler, CommandHandler, filters, CallbackQueryHandler
from core.config import (
    TELEGRAM_BOT_TOKEN, PUBLIC_CHANNEL_ID, DISCUSSION_GROUP_ID, ADMIN_CHAT_ID,
    LOGS_DIR
)
from core.db import init_db
from bot.handlers.albums import cache_admin_media_group
from bot.handlers.control import bot_pause_command, bot_resume_command, bot_status_command
from bot.handlers.edit import event_edit_command
from bot.handlers.ingestion import process_message, manual_trigger_command
from bot.handlers.public import event_next_command, event_subs_command, start_command
from bot.handlers.recap import manual_recap_command, handle_discussion_forward
from bot.handlers.repost import event_repost_command, event_schedule_invoke_command
from bot.handlers.repost_schedule import (
    event_schedule_command, event_schedule_update_command, event_schedule_list_command,
)
from bot.handlers.subscribers import event_sub_add_command, event_sub_remove_command, handle_admin_reply
from bot.handlers.story import event_regenerate_story_command
from bot.event_generator.command import event_generate_command
from bot.callbacks.router import handle_callback_query
from core.scheduler.runner import start_scheduler, stop_scheduler
from core.log_utils import DailyMonthlyLogHandler

log_file_path = os.path.join(LOGS_DIR, "bot.log")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        DailyMonthlyLogHandler(log_file_path),
        logging.StreamHandler()
    ]
)

# Set httpx logging to WARNING to prevent clutter from Telegram getUpdates polling
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

async def post_init(application: Application):
    start_scheduler(application.bot)

    # Default commands for users in private chats / groups
    default_commands = [
        BotCommand("start", "Avvia il bot e visualizza info o iscritti"),
        BotCommand("event_next", "Mostra gli eventi di oggi e futuri"),
        BotCommand("event_subs", "<id> Mostra gli iscritti di un evento"),
    ]

    # Admin commands available in ADMIN_CHAT_ID with syntax descriptions
    admin_commands = [
        BotCommand("event_process", "<testo o foto> Analizza e crea bozza evento"),
        BotCommand("ep", "<testo o foto> Analizza e crea bozza evento"),
        BotCommand("event_generate", "<istruzioni> Genera evento e locandina con AI"),
        BotCommand("eg", "<istruzioni> Genera evento e locandina con AI"),
        BotCommand("recap_generate", "[DD-MM-YYYY] Genera recap giornaliero (/rg)"),
        BotCommand("rg", "[DD-MM-YYYY] Genera recap giornaliero"),
        BotCommand("bot_pause", "Mette in pausa l'intercettazione automatica"),
        BotCommand("bot_resume", "Riattiva l'intercettazione automatica"),
        BotCommand("bot_status", "Mostra lo stato operativo del bot"),
        BotCommand("event_edit_title", "<Titolo> Modifica il titolo dell'evento"),
        BotCommand("event_edit_date", "<DD-MM-YYYY HH:MM> Modifica data e ora"),
        BotCommand("event_edit_system", "<Sistema> Modifica il sistema/gioco"),
        BotCommand("event_edit_host", "<Nome> Modifica Master o Host"),
        BotCommand("event_edit_type", "<rpg|boardgame> Imposta tipo tavolo"),
        BotCommand("event_edit_seats", "<X/Y> Modifica posti disponibili/totali"),
        BotCommand("event_edit_booked", "<N> Modifica posti già prenotati"),
        BotCommand("event_edit_extra", "<Note> Modifica dettagli/note extra"),
        BotCommand("event_edit_description", "<Testo> Modifica la descrizione"),
        BotCommand("event_edit_image", "[ID] Allega nuova foto per la locandina"),
        BotCommand("event_regenerate_story", "[ID] Rigenera immagine Storia Instagram (/ers)"),
        BotCommand("ers", "[ID] Rigenera immagine Storia Instagram"),
        BotCommand("event_sub_add", "<ID> @username [posti] Aggiunge iscritto"),
        BotCommand("event_sub_remove", "<ID> @username [posti] Rimuove iscritto"),
        BotCommand("event_repost", "<DATE> <SEATS> Ripubblica evento con nuova data e posti"),
        BotCommand("event_schedule", "[ID] [DATA HH:MM] Programma ripubblicazione evento"),
        BotCommand("event_schedule_invoke", "<ID> Prepara il post dell'evento programmato"),
        BotCommand("event_schedule_update", "<ID> Aggiorna il contenuto dell'evento programmato"),
        BotCommand("event_schedule_list", "Mostra tutti gli eventi programmati per il repost"),
    ]

    try:
        await application.bot.set_my_commands(default_commands, scope=BotCommandScopeDefault())
        if ADMIN_CHAT_ID:
            admin_target = int(ADMIN_CHAT_ID) if str(ADMIN_CHAT_ID).lstrip("-").isdigit() else str(ADMIN_CHAT_ID)
            await application.bot.set_my_commands(
                admin_commands + default_commands,
                scope=BotCommandScopeChat(chat_id=admin_target)
            )
            logger.info("Comandi bot registrati con successo tramite API (Default + Admin Chat).")
    except Exception as e:
        logger.error(f"Errore durante l'impostazione dei comandi bot via API: {e}")

async def post_shutdown(application: Application):
    stop_scheduler()

async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler catching exceptions across all handlers and polling loops."""
    if isinstance(context.error, NetworkError):
        logger.warning(
            "Errore di rete temporaneo con Telegram (natura transiente, si risolve automaticamente): %s",
            context.error
        )
    else:
        logger.error("Eccezione non gestita durante l'elaborazione di un update:", exc_info=context.error)

def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN non impostato.")
        return
        
    init_db()
    
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    
    # Handlers for admin commands
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("event_process", manual_trigger_command, block=False))
    application.add_handler(CommandHandler("ep", manual_trigger_command, block=False))
    application.add_handler(CommandHandler("event_generate", event_generate_command, block=False))
    application.add_handler(CommandHandler("eg", event_generate_command, block=False))
    application.add_handler(CommandHandler("event_next", event_next_command))
    application.add_handler(CommandHandler(["event_subs", "subs"], event_subs_command))
    application.add_handler(MessageHandler(filters.Regex(r"^/(?:event_subs|subs)(?:_\d+|\s+\d+|$)") | filters.CaptionRegex(r"^/(?:event_subs|subs)(?:_\d+|\s+\d+|$)"), event_subs_command))
    application.add_handler(CommandHandler("recap_generate", manual_recap_command))
    application.add_handler(CommandHandler("rg", manual_recap_command))
    application.add_handler(CommandHandler("bot_pause", bot_pause_command))
    application.add_handler(CommandHandler("bot_resume", bot_resume_command))
    application.add_handler(CommandHandler("bot_status", bot_status_command))
    
    edit_cmds = [
        "event_edit_title", "event_edit_date",
        "event_edit_system", "event_edit_seats", "event_edit_booked",
        "event_edit_host", "event_edit_extra", "event_edit_description",
        "event_edit_image", "event_edit_type"
    ]
    for cmd in edit_cmds:
        application.add_handler(CommandHandler(cmd, event_edit_command, block=False))
    application.add_handler(CommandHandler(["event_regenerate_story", "ers"], event_regenerate_story_command, block=False))
    application.add_handler(CommandHandler("event_sub_add", event_sub_add_command))
    application.add_handler(CommandHandler("event_sub_remove", event_sub_remove_command))
    application.add_handler(CommandHandler(["event_repost", "er"], event_repost_command, block=False))
    application.add_handler(CommandHandler("event_schedule", event_schedule_command, block=False))
    application.add_handler(CommandHandler("event_schedule_invoke", event_schedule_invoke_command, block=False))
    application.add_handler(CommandHandler("event_schedule_update", event_schedule_update_command, block=False))
    application.add_handler(CommandHandler("event_schedule_list", event_schedule_list_command, block=False))

    # Caption command handlers (PTB CommandHandler only matches message.text, not message.caption)
    application.add_handler(MessageHandler(filters.CaptionRegex(r"^/event_edit_"), event_edit_command, block=False))
    application.add_handler(MessageHandler(filters.CaptionRegex(r"^/(event_process|ep)(\s|$|@)"), manual_trigger_command, block=False))
    application.add_handler(MessageHandler(filters.CaptionRegex(r"^/(event_generate|eg)(\s|$|@)"), event_generate_command, block=False))
    application.add_handler(MessageHandler(filters.CaptionRegex(r"^/(event_regenerate_story|ers)(\s|$|@)"), event_regenerate_story_command, block=False))
    application.add_handler(MessageHandler(filters.CaptionRegex(r"^/(recap_generate|rg)(\s|$|@)"), manual_recap_command))
    application.add_handler(MessageHandler(filters.CaptionRegex(r"^/(event_repost|er)(\s|$|@)"), event_repost_command, block=False))
    application.add_handler(MessageHandler(filters.CaptionRegex(r"^/event_schedule(\s|$|@)"), event_schedule_command, block=False))
    application.add_handler(MessageHandler(filters.CaptionRegex(r"^/event_schedule_invoke(\s|$|@)"), event_schedule_invoke_command, block=False))
    application.add_handler(MessageHandler(filters.CaptionRegex(r"^/event_schedule_update(\s|$|@)"), event_schedule_update_command, block=False))
    application.add_handler(MessageHandler(filters.CaptionRegex(r"^/event_schedule_list(\s|$|@)"), event_schedule_list_command, block=False))
    
    # Listen to admin chat for prompt replies and album photos caching
    if ADMIN_CHAT_ID:
        try:
            admin_id = int(ADMIN_CHAT_ID)
            # Register caching in group=-1 so incoming admin photos are cached without consuming group=0
            application.add_handler(MessageHandler(filters.Chat(chat_id=admin_id) & (filters.PHOTO | filters.Document.IMAGE), cache_admin_media_group, block=False), group=-1)
            application.add_handler(MessageHandler(filters.Chat(chat_id=admin_id) & filters.TEXT & filters.REPLY, handle_admin_reply))
        except ValueError:
            logger.error("ADMIN_CHAT_ID deve essere un intero valido.")

    
    # Listen to public channel
    if PUBLIC_CHANNEL_ID:
        try:
            channel_id = int(PUBLIC_CHANNEL_ID)
            application.add_handler(MessageHandler(filters.Chat(chat_id=channel_id) & (filters.TEXT | filters.PHOTO), process_message))
        except ValueError:
            logger.error("PUBLIC_CHANNEL_ID deve essere un intero valido.")
            
    # Listen to discussion group for automatic forwards
    if DISCUSSION_GROUP_ID:
        try:
            discussion_id = int(DISCUSSION_GROUP_ID)
            application.add_handler(MessageHandler(filters.Chat(chat_id=discussion_id), handle_discussion_forward))
        except ValueError:
            logger.error("DISCUSSION_GROUP_ID deve essere un intero valido.")
            
    async def debug_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message or update.channel_post
        if msg:
            logger.info(f"Ricevuto update non gestito da chat_id: {msg.chat_id} (Verifica se coincide con PUBLIC_CHANNEL_ID: {PUBLIC_CHANNEL_ID})")
            
    application.add_handler(MessageHandler(filters.ALL, debug_all))
        
    # Callback queries (buttons)
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # Global error handler
    application.add_error_handler(global_error_handler)
    
    logger.info("Bot in esecuzione...")
    application.run_polling()

if __name__ == '__main__':
    main()

