"""Recap approval and WordPress article texts."""

RECAP_PUBLISHED_SUFFIX = "\n\n✅ RECAP PUBLISHED"


RECAP_DISCARDED_SUFFIX = "\n\n❌ RECAP SCARTATO"


ARTICLE_PUBLISHED_SUFFIX = "\n\n✅ ARTICOLO PUBBLICATO PUBBLICAMENTE!"


ARTICLE_PUBLISH_ERROR_SUFFIX = "\n\n❌ Errore durante la pubblicazione dell'articolo."


WORDPRESS_CREATE_ERROR = "❌ Errore durante la creazione dell'articolo su WordPress."


WORDPRESS_DRAFT_PROGRESS = "⏳ Generazione della bozza su WordPress in corso..."


RECAP_STORY_CAPTION = "✅ Immagine Storia RECAP generata (Pubblicazione IG disabilitata temporaneamente per test)."


RECAP_STORY_ERROR = "❌ Errore durante la generazione della Storia Recap."


def format_wordpress_draft_created(wp_link):
    return f"✅ Bozza articolo creata su WordPress:\n{wp_link}\n\nClicca qui sotto per pubblicarla pubblicamente."
