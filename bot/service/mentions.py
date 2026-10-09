import html


def _clean_str(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def get_user_display_name_and_username(user):
    username = _clean_str(getattr(user, 'username', None))
    clean_username = username.lstrip('@') if username else None

    full_name = _clean_str(getattr(user, 'full_name', None))
    if not full_name:
        first_name = _clean_str(getattr(user, 'first_name', None))
        last_name = _clean_str(getattr(user, 'last_name', None))
        full_name = f"{first_name} {last_name}" if first_name and last_name else first_name

    return clean_username, full_name


def _user_link(user_id, label):
    return f'<a href="tg://user?id={user_id}">{label}</a>'


def format_user_mention(user):
    clean_username, full_name = get_user_display_name_and_username(user)
    if clean_username:
        return f"@{clean_username}"
    user_id = getattr(user, 'id', None)
    has_id = isinstance(user_id, (int, str))
    if full_name:
        name = html.escape(full_name)
        return _user_link(user_id, name) if has_id else name
    return _user_link(user_id, "Utente") if has_id else "Utente"


def format_subscriber_tag(username=None, full_name=None, user_id=None):
    """HTML mention for a stored reservation/target user, or None when nothing identifies them."""
    uname = (username or '').strip()
    fname = (full_name or '').strip()
    # Legacy rows stored display names (with spaces) in the username column
    if uname and " " in uname and not fname:
        fname, uname = uname, ""

    clean_uname = uname.lstrip('@')
    if clean_uname:
        return f"@{clean_uname}"
    if user_id and fname:
        return _user_link(user_id, html.escape(fname))
    if user_id:
        return _user_link(user_id, "Utente")
    if fname:
        return html.escape(fname)
    return None


def describe_telegram_user(user):
    """Log identifier for end users: "User <id> (@username)" or "User <id> (<name>)"."""
    clean_username, full_name = get_user_display_name_and_username(user)
    if clean_username:
        return f"User {user.id} (@{clean_username})"
    return f"User {user.id} ({full_name or 'no-name'})"
