#!/usr/bin/env python3
"""
Regenerate the Astro article of a past game night from the events in the database.

It reuses the images already uploaded to R2 (their address is derived from the event image file name, so the
original files are not needed) and the cover of the article that is already on the website. Nothing is written to
the database.

Usage Examples:
    # Generate the article and save it to a file to read it, without touching GitHub:
    python3 scripts/regenerate_article.py 28-10-2026 --dry-run --output /tmp/28-10.md

    # Create (or update) the draft branch serata/<slug> on the website repo:
    python3 scripts/regenerate_article.py 28-10-2026

    # Same, and publish it (merges the branch, the site deploys):
    python3 scripts/regenerate_article.py 28-10-2026 --publish

    # Use a specific cover instead of the one of the existing article:
    python3 scripts/regenerate_article.py 28-10-2026 --cover https://media.example.org/collage.jpg
"""

import argparse
import base64
import json
import os
import re
import sys
from datetime import datetime

import requests

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import astro, config
from core.ai_parser import GeminiQuotaError, generate_astro_article
from core.astro.client import gh_request
from core.astro.content import build_front_matter, file_stem, make_excerpt
from core.db import get_pending_events_for_recap
from utils.date_utils import DAYS_IT
from utils.templates.recap import recap_generate_text

MAX_ATTEMPTS = 3
IMAGE_CHECK_TIMEOUT = 10


def _parse_date(date_str):
    try:
        return datetime.strptime(date_str, "%d-%m-%Y")
    except ValueError:
        return None


def attach_image_urls(events, slug):
    """Sets `media_url` on every event whose image is already in R2, dropping the ones that cannot be reached."""
    for ev in events:
        if not ev.get('image_path'):
            continue
        url = f"{config.R2_PUBLIC_URL}/serate/{slug}/{os.path.basename(ev['image_path'])}"
        try:
            reachable = requests.head(url, timeout=IMAGE_CHECK_TIMEOUT, allow_redirects=True).status_code == 200
        except requests.RequestException:
            reachable = False
        if reachable:
            ev['media_url'] = url
        else:
            print(f"⚠️  Immagine non raggiungibile su R2, la salto: {url}")
    return events


def existing_cover(date_str, slug):
    """The `cover` of the article already on the website branch, or None."""
    path = f"{config.ASTRO_CONTENT_DIR.strip('/')}/{file_stem(date_str, slug)}.md"
    try:
        response = gh_request("GET", f"contents/{path}", params={"ref": config.ASTRO_GITHUB_BRANCH})
    except (RuntimeError, requests.RequestException) as e:
        print(f"⚠️  Impossibile leggere l'articolo esistente: {e}")
        return None
    if response.status_code != 200:
        return None
    text = base64.b64decode(response.json().get("content", "")).decode("utf-8", "replace")
    match = re.search(r'^cover:\s*("(?:[^"\\]|\\.)*")\s*$', text, re.M)
    return json.loads(match.group(1)) if match else None


def check_structure(body, events):
    """The ways in which `body` differs from the prescribed layout (empty when it matches)."""
    problems = []
    if body.lstrip().startswith("#"):
        problems.append("inizia con un titolo invece che con un paragrafo di introduzione")
    sections = len(re.findall(r"^### ", body, re.M))
    if sections != len(events):
        problems.append(f"ci sono {sections} sezioni ### invece di {len(events)} (una per evento)")
    if not re.search(r"^---\s*$", body, re.M):
        problems.append("manca la riga --- prima della chiusura")
    without_links = re.sub(r"!?\[[^\]]*\]\([^)]*\)", "", body)
    for handle in config.RECAP_CONTACTS:  # the contacts' addresses may stay plain: the site turns them into links
        without_links = without_links.replace(f"https://t.me/{handle.lstrip('@')}", "")
    if re.search(r"https?://", without_links):
        problems.append("contiene indirizzi senza link Markdown")
    return problems


def generate_valid_article(day_str, date_str, events):
    """Asks Gemini until the article matches the layout; returns (body, problems) with the last attempt's problems."""
    problems = ["nessuna risposta da Gemini"]
    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"⏳ Generazione dell'articolo con Gemini (tentativo {attempt}/{MAX_ATTEMPTS})...")
        body = generate_astro_article(recap_generate_text(day_str, date_str, events), events)
        if not body:
            continue
        problems = check_structure(body, events)
        if not problems:
            return body, []
        print("⚠️  L'articolo non rispetta la struttura: " + "; ".join(problems))
    return None, problems


def missing_settings(dry_run):
    needed = ["GEMINI_API_KEY", "R2_PUBLIC_URL"]
    if not dry_run:
        needed += ["ASTRO_GITHUB_REPO", "ASTRO_GITHUB_TOKEN"]
    return [name for name in needed if not getattr(config, name, None)]


def run(args):
    date = _parse_date(args.date)
    if not date:
        print("❌ Data non valida. Usa il formato DD-MM-YYYY (es. 28-10-2026).")
        return 1
    missing = missing_settings(args.dry_run)
    if missing:
        print(f"❌ Impostazioni mancanti nel file .env: {', '.join(missing)}.")
        return 1

    date_str = date.strftime("%d-%m-%Y")
    day_str = DAYS_IT[date.weekday()]
    events = get_pending_events_for_recap(date_str)
    if not events:
        print(f"ℹ️  Nessun evento per la data {date_str}.")
        return 1

    slug = astro.article_slug(date_str)
    attach_image_urls(events, slug)
    cover = args.cover or existing_cover(date_str, slug)
    if not cover:
        print("⚠️  Nessuna copertina: l'articolo verrà creato senza.")

    try:
        body, problems = generate_valid_article(day_str, date_str, events)
    except GeminiQuotaError as e:
        print(f"❌ Crediti Gemini esauriti: {e}")
        return 1
    if not body:
        print("❌ Nessun articolo valido dopo %d tentativi: %s." % (MAX_ATTEMPTS, "; ".join(problems)))
        return 1

    title = f"Eventi della Serata: {day_str} {date_str}"
    tavoli = astro.tavoli_from_events(events)
    if args.dry_run:
        text = build_front_matter(title, date.strftime("%Y-%m-%d"), cover, make_excerpt(body), tavoli) + f"\n{body.strip()}\n"
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"✅ Articolo salvato in {args.output} (nessuna modifica su GitHub).")
        else:
            print(text)
        return 0

    draft_link, branch = astro.publish_article(title, body, date_str, slug, cover, make_excerpt(body), tavoli)
    if not (draft_link and branch):
        print("❌ Creazione della bozza su GitHub non riuscita (vedi i log).")
        return 1
    print(f"✅ Bozza creata: {draft_link}")
    if not args.publish:
        print("ℹ️  Per pubblicarla riesegui con --publish.")
        return 0
    if not astro.update_article_status(branch, "publish"):
        print("❌ Pubblicazione non riuscita (vedi i log).")
        return 1
    print(f"✅ Articolo pubblicato: {astro.public_url(date_str, slug)} (online dopo il deploy, circa 1-2 minuti).")
    return 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Rigenera l'articolo del sito per una serata passata usando gli eventi nel database.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("date", help="Data della serata nel formato DD-MM-YYYY.")
    parser.add_argument("--dry-run", action="store_true", help="Non scrive su GitHub: salva o stampa l'articolo.")
    parser.add_argument("-o", "--output", default=None, help="Con --dry-run, file in cui salvare l'articolo.")
    parser.add_argument("--cover", default=None, help="URL della copertina (default: quella dell'articolo esistente).")
    parser.add_argument("--publish", action="store_true", help="Dopo la bozza, la pubblica (merge sul ramo del sito).")
    args = parser.parse_args(argv)
    if args.publish and args.dry_run:
        parser.error("--publish non si può usare con --dry-run.")
    return args


def main():
    sys.exit(run(parse_args()))


if __name__ == "__main__":
    main()
