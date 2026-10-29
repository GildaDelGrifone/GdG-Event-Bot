"""Recap approval and article (WordPress / Astro site) texts."""
import html

RECAP_PUBLISHED_SUFFIX = "\n\n✅ RECAP PUBLISHED"


RECAP_DISCARDED_SUFFIX = "\n\n❌ RECAP SCARTATO"


ARTICLE_PUBLISHED_SUFFIX = "\n\n✅ ARTICOLO PUBBLICATO PUBBLICAMENTE!"


ARTICLE_PUBLISH_ERROR_SUFFIX = "\n\n❌ Errore durante la pubblicazione dell'articolo."


ARTICLE_DISCARDED_SUFFIX = "\n\n🗑️ ARTICOLO SCARTATO"
ARTICLE_ALREADY_PUBLISHED_SUFFIX = "\n\n⚠️ L'articolo è già stato pubblicato: non può essere scartato."
ARTICLE_DISCARD_ERROR_SUFFIX = "\n\n❌ Errore durante l'eliminazione della bozza."
WORDPRESS_CREATE_ERROR = "❌ Errore durante la creazione dell'articolo su WordPress."


WORDPRESS_DRAFT_PROGRESS = "⏳ Generazione della bozza su WordPress in corso..."


RECAP_STORY_CAPTION = "✅ Immagine Storia RECAP generata (Pubblicazione IG disabilitata temporaneamente per test)."


RECAP_STORY_ERROR = "❌ Errore durante la generazione della Storia Recap."


def format_wordpress_draft_created(wp_link):
    return f"✅ Bozza articolo creata su WordPress:\n{wp_link}\n\nClicca qui sotto per pubblicarla pubblicamente."

ASTRO_DRAFT_PROGRESS = "⏳ Generazione della bozza sul sito in corso..."
ASTRO_CREATE_ERROR = "❌ Errore durante la creazione dell'articolo sul sito."


def format_astro_draft_created(draft_link, public_link):
    """One HTML line with the draft and the final page as short links (send with parse_mode="HTML")."""
    draft, public = (html.escape(link, quote=True) for link in (draft_link, public_link))
    return f'✅ Bozza creata: <a href="{draft}">Vedi bozza</a> · <a href="{public}">Pagina finale</a>'


def format_astro_article_published(public_link):
    return (
        f"\n\n✅ ARTICOLO PUBBLICATO!\n{public_link}\n"
        "Sarà online dopo il deploy di Cloudflare (circa 1-2 minuti)."
    )
