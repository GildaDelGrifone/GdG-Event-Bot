"""Booking/unbooking notices, same-day conflict warnings, admin seat actions and status notices."""
import html


POPUP_TABLE_FULL = "I posti per questo tavolo sono esauriti!"


def format_status_notice(icon, status_word, event_link, subscribers_label=None, tags=None):
    text = f"{icon} <b>ATTENZIONE:</b> L'evento {event_link} è stato <b>{status_word}</b>!"
    if tags:
        text += f"\n\n{subscribers_label}: {tags}"
    return text


CONFLICT_WARNING_FOOTER = (
    "\n\n<i>La tua prenotazione è stata registrata regolarmente. "
    "Se necessario, ricordati di liberare il posto dall'evento a cui non parteciperai!</i>"
)


def format_conflict_warning(user_tag, count, items):
    if count == 1:
        header = f"⚠️ <b>Attenzione {user_tag}:</b> risulti già iscritto a un altro evento per la stessa data:\n"
    else:
        header = f"⚠️ <b>Attenzione {user_tag}:</b> risulti già iscritto ad altri {count} eventi per la stessa data:\n"
    return header + "\n".join(items) + CONFLICT_WARNING_FOOTER


def format_conflict_item(event_link, system=None):
    system_str = f" (<i>{html.escape(system)}</i>)" if system else ""
    return f"• {event_link}{system_str}"


def format_booking_notice(user_mention, event_link):
    return f"✅ {user_mention} ha prenotato 1 posto per: {event_link}"


def format_unbooking_notice(user_mention, event_link):
    return f"❌ {user_mention} ha liberato 1 posto per: {event_link}"


def format_admin_action_notice(admin_suffix, icon, verb, user_tag, event_link):
    return (
        f"🛠️ <b>Operazione effettuata da un admin degli eventi{admin_suffix}:</b>\n"
        f"{icon} {verb} per {user_tag} per: {event_link}"
    )


def format_seats_added_verb(seats):
    return "Aggiunto 1 posto" if seats == 1 else f"Aggiunti {seats} posti"


def format_seats_removed_verb(seats):
    return "Rimosso 1 posto" if seats == 1 else f"Rimossi {seats} posti"


SEATS_ADDED_ICON = "✅"


SEATS_REMOVED_ICON = "❌"


NOTICE_CANCELLED = ("⚠️", "ANNULLATO", "Iscritti avvisati")


NOTICE_REACTIVATED = ("✅", "RIATTIVATO", "Iscritti prenotati")
