#!/usr/bin/env python3
"""
Utility script to manually generate an Instagram Story image for an event from the database.

Usage Examples:
    # Generate story image for event with ID 1:
    python3 scripts/generate_story.py 1

    # List all available events in the database:
    python3 scripts/generate_story.py --list

    # Generate story image and send it to the Telegram Admin Chat:
    python3 scripts/generate_story.py 1 --send-telegram

    # Generate story image with a custom output directory:
    python3 scripts/generate_story.py 1 --output-dir /path/to/custom_dir

    # Generate story image overriding the event photo:
    python3 scripts/generate_story.py 1 --image /path/to/image.jpg

    # Generate story image and publish directly to Instagram:
    python3 scripts/generate_story.py 1 --publish-ig
"""

import os
import sys
import argparse
import asyncio
import sqlite3

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.config import (
    DATA_DIR,
    TELEGRAM_BOT_TOKEN,
    ADMIN_CHAT_ID,
    WP_URL,
    WP_USERNAME,
    WP_APP_PASSWORD,
    IG_ACCESS_TOKEN,
    IG_ACCOUNT_ID
)
from core.db import get_event, get_connection
from utils.image_utils import create_story_image


def list_events():
    """Retrieve and display events stored in the SQLite database."""
    try:
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, title, date, normalized_date, status, booked_seats, max_seats, image_path "
                "FROM events ORDER BY id DESC"
            )
            rows = cursor.fetchall()

        if not rows:
            print("ℹ️  Nessun evento presente nel database.")
            return

        print("\n📋 Eventi presenti nel database:")
        print("=" * 80)
        print(f"{'ID':<5} | {'Stato':<10} | {'Data':<22} | {'Titolo'}")
        print("-" * 80)
        for r in rows:
            seats_info = f"({r['booked_seats']}/{r['max_seats']})" if r['max_seats'] else ""
            img_marker = " 🖼️" if (r['image_path'] and os.path.exists(r['image_path'])) else ""
            print(f"{r['id']:<5} | {r['status']:<10} | {r['date'][:20]:<22} | {r['title']}{img_marker} {seats_info}")
        print("=" * 80)
        print("Legenda: 🖼️ = Immagine presente su disco\n")
    except Exception as e:
        print(f"❌ Errore durante il recupero degli eventi: {e}")


async def send_story_to_telegram(photo_path, event):
    """Send the generated story image to the Telegram Admin Chat."""
    if not TELEGRAM_BOT_TOKEN or not ADMIN_CHAT_ID:
        print("⚠️  Impossibile inviare a Telegram: TELEGRAM_BOT_TOKEN o ADMIN_CHAT_ID non configurati.")
        return False

    try:
        from telegram import Bot
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        caption = (
            f"📸 <b>Storia Instagram (Generata Manualmente)</b>\n\n"
            f"<b>Evento #{event['id']}:</b> {event.get('title', 'Senza titolo')}\n"
            f"�️ <b>Data:</b> {event.get('date', 'N/A')}\n"
            f"🎲 <b>Sistema:</b> {event.get('system', 'N/A')}"
        )
        with open(photo_path, "rb") as f:
            await bot.send_photo(
                chat_id=int(ADMIN_CHAT_ID),
                photo=f,
                caption=caption,
                parse_mode="HTML"
            )
        print(f"✅ Storia inviata con successo alla chat admin Telegram ({ADMIN_CHAT_ID}).")
        return True
    except Exception as e:
        print(f"❌ Errore durante l'invio su Telegram: {e}")
        return False


async def publish_story_to_instagram(photo_path):
    """Upload image to WordPress and publish as an Instagram Story via Meta Graph API."""
    if not WP_URL or not WP_USERNAME or not WP_APP_PASSWORD:
        print("⚠️  Credenziali WordPress non configurate: impossibile caricare l'immagine per Instagram.")
        return False
    if not IG_ACCESS_TOKEN or not IG_ACCOUNT_ID:
        print("⚠️  Credenziali Instagram non configurate: impossibile pubblicare la storia.")
        return False

    try:
        from core.wordpress import upload_media
        from core.instagram import publish_instagram_story

        print("⏳ Caricamento immagine su WordPress per ottenere un URL pubblico...")
        media_info = upload_media(photo_path)
        if not media_info or not media_info.get("source_url"):
            print("❌ Errore durante l'upload dell'immagine su WordPress.")
            return False

        public_url = media_info["source_url"]
        print(f"✅ Immagine caricata su WordPress: {public_url}")

        print("⏳ Pubblicazione storia su Instagram...")
        success, msg = await publish_instagram_story(public_url)
        if success:
            print(f"✅ {msg}")
            return True
        else:
            print(f"❌ {msg}")
            return False
    except Exception as e:
        print(f"❌ Eccezione durante la pubblicazione su Instagram: {e}")
        return False


def generate_event_story(event_id, output_dir=None, custom_image=None):
    """
    Fetch event from DB and generate its Instagram story image.

    Returns:
        tuple: (story_path, event) on success, or (None, None) on failure.
    """
    event = get_event(event_id)
    if not event:
        print(f"❌ Evento con ID {event_id} non trovato nel database.")
        return None, None

    print(f"\n🎮 Evento selezionato [ID: {event_id}]:")
    print(f"   Titolo:          {event.get('title')}")
    print(f"   Data:            {event.get('date')} (Normalizzata: {event.get('normalized_date')})")
    print(f"   Sistema:         {event.get('system')}")
    print(f"   Posti:           {event.get('booked_seats', 0)}/{event.get('max_seats', 'Illimitati')}")
    print(f"   Stato:           {event.get('status')}")

    # Determine image path
    if custom_image:
        if not os.path.exists(custom_image):
            print(f"❌ L'immagine personalizzata specificata non esiste: {custom_image}")
            return None, event
        image_path = custom_image
        print(f"   Immagine custom: {image_path}")
    else:
        image_path = event.get('image_path')
        if image_path:
            if os.path.exists(image_path):
                print(f"   Immagine evento: {image_path}")
            else:
                print(f"   ⚠️  Immagine evento registrata ma non trovata su disco: {image_path}")
                print("      (La storia verrà generata con il solo testo)")
                image_path = None
        else:
            print("   ℹ️  Nessuna immagine associata all'evento (layout solo testo).")

    dest_dir = output_dir or DATA_DIR
    print("\n⏳ Generazione immagine Storia Instagram (1080x1920)...")
    story_path = create_story_image(event, image_path, dest_dir)

    if story_path and os.path.exists(story_path):
        size_kb = os.path.getsize(story_path) / 1024
        print("✅ Storia generata con successo!")
        print(f"   File:       {story_path}")
        print("   Dimensioni: 1080x1920 px")
        print(f"   Peso:       {size_kb:.1f} KB")
        return story_path, event
    else:
        print("❌ Errore durante la creazione dell'immagine della storia.")
        return None, event


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generatore manuale di Storie Instagram per eventi della Gilda del Grifone.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "event_id",
        type=int,
        nargs="?",
        help="ID numerico dell'evento nel database SQLite."
    )
    parser.add_argument(
        "-l", "--list",
        action="store_true",
        help="Elenca tutti gli eventi presenti nel database con i relativi ID."
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=str,
        default=None,
        help="Directory di destinazione (default: cartella basata sulla data in DATA_DIR)."
    )
    parser.add_argument(
        "-i", "--image",
        type=str,
        default=None,
        help="Percorso di un'immagine da usare al posto di quella salvata nel database."
    )
    parser.add_argument(
        "-t", "--send-telegram",
        action="store_true",
        help="Invia l'immagine generata alla chat degli amministratori Telegram."
    )
    parser.add_argument(
        "-p", "--publish-ig",
        action="store_true",
        help="Carica l'immagine su WordPress e pubblicala come Storia su Instagram (richiede credenziali)."
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.list:
        list_events()
        return

    if args.event_id is None:
        print("⚠️  Nessun ID evento specificato.")
        list_events()
        print("Uso: python3 scripts/generate_story.py <ID_EVENTO> [OPZIONI]")
        print("Esempio: python3 scripts/generate_story.py 1 --send-telegram\n")
        return

    story_path, event = generate_event_story(
        event_id=args.event_id,
        output_dir=args.output_dir,
        custom_image=args.image
    )

    if not story_path:
        sys.exit(1)

    if args.send_telegram:
        print("\n⏳ Invio dell'immagine alla chat admin Telegram...")
        asyncio.run(send_story_to_telegram(story_path, event))

    if args.publish_ig:
        print("\n⏳ Pubblicazione su Instagram...")
        asyncio.run(publish_story_to_instagram(story_path))


if __name__ == "__main__":
    main()

