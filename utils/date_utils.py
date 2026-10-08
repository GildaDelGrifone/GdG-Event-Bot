import re
from datetime import datetime, date, timedelta

DAYS_IT = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]

WEEKDAYS_MAP = {
    # Italian
    "lunedì": 0, "lunedi": 0,
    "martedì": 1, "martedi": 1,
    "mercoledì": 2, "mercoledi": 2,
    "giovedì": 3, "giovedi": 3,
    "venerdì": 4, "venerdi": 4,
    "sabato": 5,
    "domenica": 6,
    # English
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

KEYWORD_WEEKDAYS = {
    "lun": 0, "lunedì": 0, "lunedi": 0, "monday": 0, "mon": 0,
    "mar": 1, "martedì": 1, "martedi": 1, "tuesday": 1, "tue": 1,
    "mer": 2, "mercoledì": 2, "mercoledi": 2, "wednesday": 2, "wed": 2,
    "gio": 3, "giovedì": 3, "giovedi": 3, "thursday": 3, "thu": 3,
    "ven": 4, "venerdì": 4, "venerdi": 4, "friday": 4, "fri": 4,
    "sab": 5, "sabato": 5, "saturday": 5, "sat": 5,
    "dom": 6, "domenica": 6, "sunday": 6, "sun": 6,
}

def parse_user_date(date_str: str, reference_date: date | datetime | None = None) -> tuple[datetime, bool] | None:
    """
    Parses a user-supplied date string.
    Accepted formats:
    - DD-MM-YYYY or DD/MM/YYYY
    - DD-MM-YYYY HH:MM or DD/MM/YYYY HH:MM
    - "oggi" / "today" [HH:MM] (sets to today's date)
    - "LUN", "MER", "VEN" (or full weekday name) [HH:MM] (sets to the next occurrence of that weekday,
      starting from today; if today is that weekday, sets to next week's occurrence).
    Allows single or double digits for day, month, and hour.
    
    Returns (datetime_obj, has_time) or None if format is invalid or date does not exist.
    """
    if not date_str or not isinstance(date_str, str):
        return None
        
    s = date_str.strip()

    # Check for keywords: "oggi" or weekdays (e.g., LUN, MER, VEN)
    m_kw = re.match(r'^([a-zA-ZàèéìòùÀÈÉÌÒÙ]+)(?:\s+(\d{1,2}):(\d{2}))?$', s)
    if m_kw:
        kw = m_kw.group(1).lower()
        has_time = m_kw.group(2) is not None
        hour = int(m_kw.group(2)) if has_time else 0
        minute = int(m_kw.group(3)) if has_time else 0

        ref_dt = datetime.now()
        if reference_date is not None:
            if isinstance(reference_date, datetime):
                ref_dt = reference_date
            else:
                ref_dt = datetime.combine(reference_date, datetime.min.time())

        target_date = None
        if kw in ["oggi", "today"]:
            target_date = ref_dt.date()
        elif kw in KEYWORD_WEEKDAYS:
            target_weekday = KEYWORD_WEEKDAYS[kw]
            days_ahead = (target_weekday - ref_dt.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            target_date = ref_dt.date() + timedelta(days=days_ahead)

        if target_date is not None:
            try:
                dt = datetime(target_date.year, target_date.month, target_date.day, hour, minute)
                return dt, has_time
            except ValueError:
                return None

    # Check for standard calendar date formats: DD-MM-YYYY or DD/MM/YYYY [HH:MM]
    m = re.match(r'^(\d{1,2})[-/](\d{1,2})[-/](\d{4})(?:\s+(\d{1,2}):(\d{2}))?$', s)
    if not m:
        return None
        
    day = int(m.group(1))
    month = int(m.group(2))
    year = int(m.group(3))
    has_time = m.group(4) is not None
    hour = int(m.group(4)) if has_time else 0
    minute = int(m.group(5)) if has_time else 0
    
    try:
        dt = datetime(year, month, day, hour, minute)
        return dt, has_time
    except ValueError:
        return None

def format_standard_event_date(dt: datetime, has_time: bool) -> tuple[str, str]:
    """
    Given a datetime and has_time flag:
    Returns (display_date, normalized_date).
    Example:
    ("Venerdì 05-09-2026 21:00", "05-09-2026") or ("Venerdì 05-09-2026", "05-09-2026")
    """
    weekday_str = DAYS_IT[dt.weekday()]
    norm_date = dt.strftime("%d-%m-%Y")
    if has_time:
        display_date = f"{weekday_str} {dt.strftime('%d-%m-%Y %H:%M')}"
    else:
        display_date = f"{weekday_str} {dt.strftime('%d-%m-%Y')}"
    return display_date, norm_date

def parse_date_tuple_from_str(date_str: str) -> tuple[int, int, int] | None:
    """
    Extracts (year, month, day) from a date string (handles DD-MM-YYYY, YYYY-MM-DD, slashes, dots).
    """
    if not date_str or not isinstance(date_str, str):
        return None
    s = date_str.strip()
    m = re.search(r'\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b', s)
    if m:
        try:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            datetime(y, mo, d)
            return (y, mo, d)
        except ValueError:
            pass
    m = re.search(r'\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b', s)
    if m:
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            datetime(y, mo, d)
            return (y, mo, d)
        except ValueError:
            pass
    return None

def validate_event_date_anomalies(event_data: dict, raw_text: str = None, reference_date: date = None) -> list[str]:
    """
    Validates event date logic:
    1. Checks if date is in the past compared to reference_date (default: today).
    2. Checks if there is a weekday mismatch between text and the actual calendar day.
    3. Checks if a valid date is present.
    
    Returns a list of warning messages (empty if valid).
    """
    warnings = []
    if reference_date is None:
        reference_date = date.today()
        
    date_field = str(event_data.get('date') or '').strip()
    norm_field = str(event_data.get('normalized_date') or '').strip()
    
    parsed_tuple = parse_date_tuple_from_str(norm_field) or parse_date_tuple_from_str(date_field)
    
    if not parsed_tuple:
        warnings.append("⚠️ ATTENZIONE: Impossibile determinare una data valida per l'evento!")
        return warnings
        
    y, mo, d = parsed_tuple
    try:
        ev_date = date(y, mo, d)
    except ValueError:
        warnings.append("⚠️ ATTENZIONE: Data inesistente nel calendario!")
        return warnings
        
    formatted_d = f"{d:02d}-{mo:02d}-{y}"

    # Check Past Date
    if ev_date < reference_date:
        warnings.append(f"⚠️ ATTENZIONE: La data rilevata ({formatted_d}) risulta essere nel PASSATO!")
        
    # Check Weekday Mismatch
    text_to_check = date_field.lower()
    m_day = re.search(r'\b(luned[iì]|marted[iì]|mercoled[iì]|gioved[iì]|venerd[iì]|sabato|domenica|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', text_to_check)
    if not m_day and raw_text:
        m_day = re.search(r'\b(luned[iì]|marted[iì]|mercoled[iì]|gioved[iì]|venerd[iì]|sabato|domenica|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', raw_text.lower())
        
    if m_day:
        word = m_day.group(1).lower()
        if word in WEEKDAYS_MAP:
            expected_weekday_idx = WEEKDAYS_MAP[word]
            actual_weekday_idx = ev_date.weekday()
            if expected_weekday_idx != actual_weekday_idx:
                mentioned_name = DAYS_IT[expected_weekday_idx]
                actual_name = DAYS_IT[actual_weekday_idx]
                warnings.append(
                    f"⚠️ ATTENZIONE: Incongruenza data/giorno! Il testo menziona '{mentioned_name}', ma il {formatted_d} è {actual_name}."
                )
                
    return warnings


def event_date_tuple(event):
    return parse_date_tuple_from_str(event.get('normalized_date')) or parse_date_tuple_from_str(event.get('date'))


def are_events_on_same_day(ev1, ev2):
    if not ev1 or not ev2:
        return False
    norm1 = ev1.get('normalized_date')
    norm2 = ev2.get('normalized_date')
    if norm1 and norm2:
        d1, d2 = parse_date_tuple_from_str(norm1), parse_date_tuple_from_str(norm2)
        if d1 and d2:
            return d1 == d2
        if norm1.strip() and norm2.strip():
            return norm1.strip().lower() == norm2.strip().lower()

    date1 = ev1.get('date')
    date2 = ev2.get('date')
    d1 = parse_date_tuple_from_str(norm1 or date1)
    d2 = parse_date_tuple_from_str(norm2 or date2)
    if d1 and d2:
        return d1 == d2

    if date1 and date2 and date1.strip() and date2.strip():
        return date1.strip().lower() == date2.strip().lower()
    return False
