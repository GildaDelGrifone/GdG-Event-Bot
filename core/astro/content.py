import json
import logging
import re
import unicodedata
from datetime import datetime

from core import config
from core.astro import github
from core.astro.client import github_credentials
from utils.date_utils import DAYS_IT

logger = logging.getLogger(__name__)

EXCERPT_LIMIT = 160


def _parse_date(date_str):
    return datetime.strptime(date_str, "%d-%m-%Y")


def article_slug(date_str):
    """'23-10-2026' -> 'eventi-della-serata-venerdi-23-10-2026'."""
    weekday = DAYS_IT[_parse_date(date_str).weekday()]
    weekday = unicodedata.normalize("NFKD", weekday).encode("ascii", "ignore").decode("ascii").lower()
    return f"eventi-della-serata-{weekday}-{date_str}"


def file_stem(date_str, slug):
    return f"{_parse_date(date_str):%Y-%m-%d}-{slug}"


def public_url(date_str, slug):
    """The page on the site: it strips the date from the file name, so the URL is just /serate/<slug>/.
    `slug` must be the bare slug (see article_slug), never the dated file stem."""
    return f"{config.ASTRO_BASE_URL}/serate/{slug}/"


def make_excerpt(markdown, limit=EXCERPT_LIMIT):
    """Plain-text start of the article, cut at a word boundary with '…' when longer than `limit`."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", markdown)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[#*_`>]", "", text)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0] if " " in text[:limit] else text[:limit]
    return f"{cut.rstrip(' ,.;:-')}…"


def _quote(value):
    """A YAML double-quoted scalar (JSON strings are valid YAML)."""
    return json.dumps(str(value), ensure_ascii=False)


def build_front_matter(title, date_iso, cover_url, excerpt, tavoli):
    """The Astro content-collection front matter; `tavoli` items are {'gioco', 'tipo', 'immagine'?}."""
    lines = ["---", f"title: {_quote(title)}", f"date: {date_iso}"]
    if cover_url:
        lines.append(f"cover: {_quote(cover_url)}")
    lines.append(f"excerpt: {_quote(excerpt)}")
    if tavoli:
        lines.append("tavoli:")
        for tavolo in tavoli:
            fields = [f"gioco: {_quote(tavolo['gioco'])}", f"tipo: {tavolo['tipo']}"]
            if tavolo.get("immagine"):
                fields.append(f"immagine: {_quote(tavolo['immagine'])}")
            lines.append(f"  - {{ {', '.join(fields)} }}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _branch_name(slug):
    return f"serata/{slug}"


def publish_article(title, markdown_body, date, slug, cover_url, excerpt, tavoli):
    """Creates the draft: a branch with the article file. Returns (draft_link, branch) or (False, None)."""
    creds = github_credentials()
    if not creds:
        logger.warning("Astro GitHub credentials not fully configured for article draft.")
        return False, None
    repo, _ = creds

    branch = _branch_name(slug)
    path = f"{config.ASTRO_CONTENT_DIR.strip('/')}/{file_stem(date, slug)}.md"
    front_matter = build_front_matter(title, f"{_parse_date(date):%Y-%m-%d}", cover_url, excerpt, tavoli)
    try:
        if not github.create_branch(branch, config.ASTRO_GITHUB_BRANCH):
            return False, None
        if not github.put_file(path, f"{front_matter}\n{markdown_body.strip()}\n", f"Bozza serata {date}", branch):
            return False, None
    except Exception as e:
        logger.error(f"Astro: Exception creating article draft: {e}")
        return False, None
    return f"https://github.com/{repo}/blob/{branch}/{path}", branch


def update_article_status(draft_id, status="publish"):
    """Publishing merges the draft branch into the site branch (Cloudflare then deploys) and deletes it."""
    if status != "publish" or not github_credentials():
        return False
    try:
        if not github.merge_branch(draft_id, config.ASTRO_GITHUB_BRANCH, f"Pubblica {draft_id}"):
            return False
        github.delete_branch(draft_id)
        return True
    except Exception as e:
        logger.error(f"Astro: Exception publishing article '{draft_id}': {e}")
        return False


def discard_article(draft_id):
    """Deletes the draft branch. Returns True, False on error, or "published" when the branch is gone (publishing deletes it)."""
    if not github_credentials():
        return False
    try:
        if github.get_ref_sha(draft_id) is None:
            return "published"
        return github.delete_branch(draft_id)
    except Exception as e:
        logger.error(f"Astro: Exception discarding article '{draft_id}': {e}")
        return False
