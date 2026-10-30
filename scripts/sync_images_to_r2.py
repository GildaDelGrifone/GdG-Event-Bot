#!/usr/bin/env python3
"""
Upload the images of a game night from the data folder to the R2 bucket, so an article that is already published
with broken image links starts working. The article is not touched.

By default the images to upload are the ones the published article points at (cover, games list, body), found
through the website repo; each is uploaded under the same key the article uses. Files are looked for loose in the
night's folders and inside their archive.zip (the nightly job zips them), without extracting anything into data/.

Usage Examples:
    # See what is missing from R2 and where each file would come from (nothing is uploaded):
    python3 scripts/sync_images_to_r2.py 28-10-2026 --dry-run

    # Upload the missing images:
    python3 scripts/sync_images_to_r2.py 28-10-2026

    # Upload again even the ones already reachable:
    python3 scripts/sync_images_to_r2.py 28-10-2026 --force

    # Read the article from a local copy instead of GitHub:
    python3 scripts/sync_images_to_r2.py 28-10-2026 --article-file /tmp/article.md

    # Without the article: every event image of the night plus every collage in its folder:
    python3 scripts/sync_images_to_r2.py 28-10-2026 --all
"""

import argparse
import glob
import os
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime

import requests

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import astro, config
from core.db import get_pending_events_for_recap

HEAD_TIMEOUT = 10
ARCHIVE_NAME = "archive.zip"


def article_image_refs(text, base_url):
    """(key prefix, file name) of every image of the article hosted on `base_url` under serate/<slug>/, without repeats."""
    pattern = re.escape(base_url.rstrip("/")) + r"/(serate/[^/\s\"')]+)/([^\s\"')]+)"
    refs = []
    for match in re.finditer(pattern, text):
        ref = (match.group(1), match.group(2))
        if ref not in refs:
            refs.append(ref)
    return refs


def day_folder(date):
    return os.path.join(config.DATA_DIR, date.strftime("%Y"), date.strftime("%m"), date.strftime("%d"))


def candidate_folders(date, events):
    """The folders that can hold the night's images: the ones of the stored event image paths, then the day folder."""
    folders = []
    for ev in events:
        if not ev.get('image_path'):
            continue
        folder = os.path.dirname(ev['image_path'])
        folders.append(folder)
        parts = folder.split(os.sep)
        if not os.path.isabs(folder) and parts[0] == "data":  # stored relative to the repo; DATA_DIR may live elsewhere
            folders.append(os.path.join(config.DATA_DIR, *parts[1:]))
    folders.append(day_folder(date))
    return list(dict.fromkeys(folders))


def find_local_file(name, folders):
    """(path, None) for a loose file, (zip path, member) for one inside an archive.zip, or None. Loose files win."""
    for folder in folders:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path, None
    for folder in folders:
        zip_path = os.path.join(folder, ARCHIVE_NAME)
        if not os.path.isfile(zip_path):
            continue
        with zipfile.ZipFile(zip_path) as archive:
            members = [info for info in archive.infolist() if os.path.basename(info.filename) == name]
        if members:
            return zip_path, max(members, key=lambda info: info.date_time).filename
    return None


def extract_member(zip_path, member, target_dir):
    path = os.path.join(target_dir, os.path.basename(member))
    with zipfile.ZipFile(zip_path) as archive, archive.open(member) as source, open(path, "wb") as target:
        shutil.copyfileobj(source, target)
    return path


def collage_names(folders):
    names = []
    for folder in folders:
        names += [os.path.basename(path) for path in glob.glob(os.path.join(folder, "collage_*"))]
        zip_path = os.path.join(folder, ARCHIVE_NAME)
        if os.path.isfile(zip_path):
            with zipfile.ZipFile(zip_path) as archive:
                names += [os.path.basename(n) for n in archive.namelist() if os.path.basename(n).startswith("collage_")]
    return list(dict.fromkeys(names))


def refs_from_database(date_str, events, folders):
    """Without the article: every event image of the night plus every collage, under the night's own prefix."""
    prefix = f"serate/{astro.article_slug(date_str)}"
    names = [os.path.basename(ev['image_path']) for ev in events if ev.get('image_path')] + collage_names(folders)
    return [(prefix, name) for name in dict.fromkeys(names)]


def reachable(url):
    try:
        return requests.head(url, timeout=HEAD_TIMEOUT, allow_redirects=True).status_code == 200
    except requests.RequestException:
        return False


def missing_settings(args):
    needed = ["R2_PUBLIC_URL"]
    if not args.dry_run:
        needed += ["R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"]
    if not (args.all or args.article_file):
        needed += ["ASTRO_GITHUB_REPO", "ASTRO_GITHUB_TOKEN"]
    return [name for name in needed if not getattr(config, name, None)]


def load_refs(args, date_str, events, folders):
    """(refs, error): what to sync, or why it could not be worked out."""
    if args.all:
        return refs_from_database(date_str, events, folders), None
    if args.article_file:
        with open(args.article_file, encoding="utf-8") as f:
            text = f.read()
    else:
        try:
            text = astro.published_article_text(date_str, astro.article_slug(date_str))
        except (RuntimeError, requests.RequestException) as e:
            return None, f"impossibile leggere l'articolo da GitHub ({e})"
        if text is None:
            return None, "articolo non trovato sul sito"
    refs = article_image_refs(text, config.R2_PUBLIC_URL)
    if not refs:
        return None, f"l'articolo non contiene immagini ospitate su {config.R2_PUBLIC_URL}"
    return refs, None


def run(args):
    try:
        date = datetime.strptime(args.date, "%d-%m-%Y")
    except ValueError:
        print("❌ Data non valida. Usa il formato DD-MM-YYYY (es. 28-10-2026).")
        return 1
    missing = missing_settings(args)
    if missing:
        print(f"❌ Impostazioni mancanti nel file .env: {', '.join(missing)}.")
        return 1

    date_str = date.strftime("%d-%m-%Y")
    events = get_pending_events_for_recap(date_str)
    folders = candidate_folders(date, events)
    refs, error = load_refs(args, date_str, events, folders)
    if error:
        print(f"❌ {error}. Usa --article-file FILE per leggere l'articolo da un file, oppure --all.")
        return 1

    present, uploaded, not_found, failed, unreachable = [], [], [], [], []
    with tempfile.TemporaryDirectory() as tmp:
        for prefix, name in refs:
            key = f"{prefix}/{name}"
            url = f"{config.R2_PUBLIC_URL}/{key}"
            if not args.force and reachable(url):
                present.append(key)
                print(f"✔️  Già raggiungibile: {key}")
                continue
            found = find_local_file(name, folders)
            if not found:
                not_found.append(key)
                print(f"⚠️  Non trovato in locale: {name} (cartelle: {', '.join(folders)})")
                continue
            path, member = found
            source = path if member is None else f"{path}:{member}"
            if args.dry_run:
                uploaded.append(key)
                print(f"⬆️  Da caricare: {key}  <-  {source}")
                continue
            local_path = path if member is None else extract_member(path, member, tmp)
            print(f"⏳ Carico {key}  <-  {source}")
            if not astro.upload_media(local_path, prefix):
                failed.append(key)
                print(f"❌ Caricamento non riuscito: {key} (vedi i log)")
                continue
            uploaded.append(key)
            if not reachable(url):
                unreachable.append(key)
                print(f"⚠️  Caricato ma non raggiungibile: {url} (controlla l'accesso pubblico del bucket e R2_PUBLIC_URL)")

    verb = "da caricare" if args.dry_run else "caricati"
    print(f"\nRiepilogo: {len(present)} già presenti, {len(uploaded)} {verb}, {len(not_found)} non trovati in locale, "
          f"{len(failed)} caricamenti falliti, {len(unreachable)} non raggiungibili dopo il caricamento.")
    return 1 if (not_found or failed or unreachable) else 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Carica su R2 le immagini di una serata dalla cartella data/ (articolo già pubblicato con link rotti).",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("date", help="Data della serata nel formato DD-MM-YYYY.")
    parser.add_argument("--dry-run", action="store_true", help="Non carica nulla: elenca cosa manca e da dove verrebbe preso.")
    parser.add_argument("--force", action="store_true", help="Ricarica anche le immagini già raggiungibili.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--article-file", default=None, help="Legge l'articolo da questo file invece che da GitHub.")
    source.add_argument("--all", action="store_true",
                        help="Senza articolo: tutte le immagini degli eventi della serata e tutti i collage della cartella.")
    return parser.parse_args(argv)


def main():
    sys.exit(run(parse_args()))


if __name__ == "__main__":
    main()
