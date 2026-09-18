import asyncio
import re as _re
from datetime import datetime, timedelta
import httpx
from dateutil import parser as dt_parser
from config import settings
from schemas import MeetingData, MeetingProgress
from prompts import (
    get_meeting_fields, get_meeting_labels,
    get_meeting_collected_prefix, get_meeting_confirmation,
    get_meeting_confirmation_summary, get_meeting_validation_error,
)


_TZ_ABBR_MAP = {
    "ist": "+05:30", "utc": "+00:00", "gmt": "+00:00",
    "est": "-05:00", "edt": "-04:00",
    "cst": "-06:00", "cdt": "-05:00",
    "mst": "-07:00", "mdt": "-06:00",
    "pst": "-08:00", "pdt": "-07:00",
    "cet": "+01:00", "cest": "+02:00",
    "eet": "+02:00", "eest": "+03:00",
    "bst": "+01:00", "wat": "+01:00",
    "cat": "+02:00", "eat": "+03:00",
    "msk": "+03:00", "aest": "+10:00", "aedt": "+11:00",
}


_RELATIVE_DAY = {
    "today": 0, "tonight": 0, "tomorrow": 1, "tom": 1,
    "dayaftertomorrow": 2, "nextday": 1,
}


def _resolve_relative_date(s: str) -> str:
    now = datetime.now()
    s_lower = s.lower().strip()
    offset = None
    for kw, days in _RELATIVE_DAY.items():
        if s_lower.startswith(kw):
            offset = days
            rest = s_lower[len(kw):].strip().lstrip(",").strip()
            break
    if s_lower.startswith("next "):
        parts = s_lower.split(None, 2)
        if len(parts) >= 2:
            day_name = parts[1]
            rest = parts[2] if len(parts) > 2 else ""
            day_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                       "friday": 4, "saturday": 5, "sunday": 6}
            target = day_map.get(day_name)
            if target is not None:
                days_ahead = (target - now.weekday()) % 7
                if days_ahead <= 0:
                    days_ahead += 7
                dt = (now + timedelta(days=days_ahead)).replace(hour=0, minute=0, second=0, microsecond=0)
                return dt.strftime("%Y-%m-%d") + (" " + rest if rest else "")
    if offset is not None:
        dt = (now + timedelta(days=offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        return dt.strftime("%Y-%m-%d") + (" " + rest if rest else "")
    return s


def _normalize_datetime_str(raw: str) -> str:
    s = raw.strip()
    s = _resolve_relative_date(s)
    s = _re.sub(r"\s+", " ", s)
    s = s.replace("at ", "").replace("on ", "")
    s = _re.sub(r"(\d)([APap][Mm])", r"\1 \2", s)
    tz_match = _re.search(r"(?i)\b([a-z]{2,5})\b\s*$", s)
    if tz_match:
        abbr = tz_match.group(1).lower()
        if abbr in _TZ_ABBR_MAP:
            s = s[:tz_match.start()].strip() + " " + _TZ_ABBR_MAP[abbr]
    return s


def parse_datetime(text: str) -> str | None:
    """Parse a natural-language date/time string to ISO-8601 format."""
    if not text or not text.strip():
        return text
    text = text.strip()
    # Try normalizing first to substitute timezone abbreviations (IST → +05:30, etc.)
    normalized = _normalize_datetime_str(text)
    try:
        dt = dt_parser.parse(normalized)
        return dt.isoformat()
    except Exception:
        pass
    # Last attempt with the raw text
    try:
        dt = dt_parser.parse(text)
        return dt.isoformat()
    except Exception:
        return text


def _tz_offset_str(dt: datetime) -> str:
    """Format timezone offset as e.g. '+05:30' or empty if naive."""
    try:
        off = dt.utcoffset()
        if off is None:
            return ""
        total_sec = int(off.total_seconds())
        sign = "+" if total_sec >= 0 else "-"
        h, m = divmod(abs(total_sec), 3600)
        return f"GMT{sign}{h:02d}:{m//60:02d}"
    except Exception:
        return ""


def format_datetime_display(iso_str: str | None) -> str:
    """Convert ISO-8601 string to a clean, user-friendly display format for chat."""
    if not iso_str or not iso_str.strip():
        return iso_str or ""
    try:
        dt = datetime.fromisoformat(iso_str)
    except Exception:
        try:
            dt = dt_parser.parse(iso_str)
        except Exception:
            return iso_str
    day = dt.day
    suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    hour = dt.strftime("%I").lstrip("0")
    minute = dt.strftime("%M")
    ampm = dt.strftime("%p")
    month = dt.strftime("%B")
    year = dt.strftime("%Y")
    return f"{day}{suffix} {month} {year}, {hour}:{minute} {ampm}"


def format_n8n_iso_datetime(dt_str: str | None) -> str:
    """
    Converts datetime string into standard ISO-8601 with timezone for n8n payload.
    e.g. '2026-07-20T11:00:00+05:30'
    """
    if not dt_str or not dt_str.strip():
        return dt_str or ""
    try:
        dt = dt_parser.parse(dt_str)
        if dt.tzinfo is None:
            import datetime as _dt
            ist = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
            dt = dt.replace(tzinfo=ist)
        return dt.isoformat()
    except Exception:
        return dt_str


FIELD_ORDER = [
    "name", "company_name", "company_address",
    "email", "contact_number", "meeting_purpose",
    "meeting_date_time", "connection_type",
]


def get_current_field_index(current: MeetingData, language: str = "english") -> int:
    fields = get_meeting_fields(language)
    for idx, (field_name, _) in enumerate(fields):
        val = getattr(current, field_name, None)
        if val is None or str(val).strip() == "":
            return idx
    return len(fields)


def _extract_clean_value(field_name: str, raw_msg: str) -> str:
    """
    Extract the actual value from a natural-language response.
    e.g. "my name is Megha" → "Megha"
         "company name is zzzy ltsd" → "zzzy ltsd"
         "my contact number is 784512045" → "784512045"
         "megha@gmail.com" → "megha@gmail.com"
    """
    msg = raw_msg.strip()

    if field_name == "name":
        # Strip common name prefixes
        prefixes = [
            r"(?i)^(?:my\s+)?(?:full\s+)?name\s+is\s+",
            r"(?i)^(?:i\s+am|i'm|it'?s|this\s+is|mera\s+naam|naam)\s+",
            r"(?i)^(?:main|mera\s+naam\s+hai|naam\s+hai)\s+",
        ]
        for pat in prefixes:
            msg = _re.sub(pat, "", msg).strip()
        # Title case the name
        return msg.title() if msg else msg

    if field_name == "company_name":
        prefixes = [
            r"(?i)^(?:my\s+)?company(?:\s+name)?\s+is\s+",
            r"(?i)^(?:i\s+work\s+(?:for|at|in)|main\s+kaam\s+karta?\s+hoon?)\s+",
            r"(?i)^(?:company\s+ka\s+naam(?:\s+hai)?)\s+",
            r"(?i)^(?:it'?s|it\s+is)\s+",
        ]
        for pat in prefixes:
            msg = _re.sub(pat, "", msg).strip()
        return msg

    if field_name == "company_address":
        prefixes = [
            r"(?i)^(?:my\s+)?(?:company\s+)?address\s+is\s+",
            r"(?i)^(?:it'?s\s+(?:at|in)|located\s+(?:at|in))\s+",
            r"(?i)^(?:company\s+ka\s+address(?:\s+hai)?)\s+",
            r"(?i)^(?:it'?s|it\s+is)\s+",
        ]
        for pat in prefixes:
            msg = _re.sub(pat, "", msg).strip()
        return msg

    if field_name == "email":
        # Try to extract email pattern from the text
        email_match = _re.search(
            r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', msg
        )
        if email_match:
            return email_match.group(0)
        # Fallback: strip common prefixes
        prefixes = [
            r"(?i)^(?:my\s+)?email(?:\s+id)?\s+is\s+",
            r"(?i)^(?:it'?s|it\s+is)\s+",
            r"(?i)^(?:meri\s+email(?:\s+id)?(?:\s+hai)?)\s+",
        ]
        for pat in prefixes:
            msg = _re.sub(pat, "", msg).strip()
        return msg

    if field_name == "contact_number":
        # Extract phone digits from the sentence
        # First try to find a phone-number-like pattern
        phone_match = _re.search(r'[\+]?[\d\s\-\(\)]{7,15}', msg)
        if phone_match:
            return phone_match.group(0).strip()
        # Fallback: strip prefixes
        prefixes = [
            r"(?i)^(?:my\s+)?(?:contact\s+)?(?:number|phone|mobile)(?:\s+(?:is|number\s+is))?\s+",
            r"(?i)^(?:it'?s|it\s+is)\s+",
            r"(?i)^(?:mera\s+(?:contact\s+)?(?:number|phone)(?:\s+hai)?)\s+",
        ]
        for pat in prefixes:
            msg = _re.sub(pat, "", msg).strip()
        return msg

    if field_name == "meeting_date_time":
        prefixes = [
            r"(?i)^(?:(?:meeting|preferred)\s+(?:date\s+(?:and\s+)?)?time\s+is\s+)",
            r"(?i)^(?:let'?s?\s+(?:do|meet|schedule)(?:\s+(?:it|on))?\s+)",
            r"(?i)^(?:it'?s|it\s+is|how\s+about)\s+",
        ]
        for pat in prefixes:
            msg = _re.sub(pat, "", msg).strip()
        return msg

    return msg


def _validate_and_set_field(
    current: MeetingData,
    field_name: str,
    value: str,
    language: str = "english",
) -> tuple[bool, str]:
    """
    Extract clean value from natural language, validate, and set on MeetingData.
    Returns (success, error_message).
    """
    print(f"\n--- [_validate_and_set_field] field: {repr(field_name)}, raw value: {repr(value)} ---")
    value = value.strip()
    if not value:
        return False, ""

    # Extract clean value from natural language
    clean_value = _extract_clean_value(field_name, value)
    print(f"--- [_validate_and_set_field] clean_value: {repr(clean_value)} ---")
    if not clean_value:
        return False, ""

    if field_name == "email":
        if not MeetingData.validate_email(clean_value):
            return False, get_meeting_validation_error("email", language)
        setattr(current, field_name, clean_value)
        return True, ""

    if field_name == "contact_number":
        # Re-extract just digits for validation
        digits_only = _re.sub(r'[\s\-\+\(\)]', '', clean_value)
        if not MeetingData.validate_phone(clean_value):
            return False, get_meeting_validation_error("contact_number", language)
        setattr(current, field_name, clean_value)
        return True, ""

    if field_name == "connection_type":
        parsed = MeetingData.validate_connection_type(value)  # use raw value for keyword matching
        if parsed is None:
            return False, get_meeting_validation_error("connection_type", language)
        setattr(current, field_name, parsed)
        return True, ""

    # For name, company_name, company_address, meeting_date_time
    setattr(current, field_name, clean_value)
    return True, ""


def _build_progress(current: MeetingData, language: str = "english") -> MeetingProgress:
    """Build a MeetingProgress object reflecting current state."""
    fields = get_meeting_fields(language)
    completed = {}
    labels = get_meeting_labels(language)

    for fn, _ in fields:
        val = getattr(current, fn, None)
        if val and str(val).strip():
            completed[labels.get(fn, fn)] = val

    idx = get_current_field_index(current, language)
    current_field = fields[idx][0] if idx < len(fields) else ""

    return MeetingProgress(
        step=idx + 1 if idx < len(fields) else len(fields),
        total=len(fields),
        field=current_field,
        completed_fields=completed,
        confirmation_pending=current.confirmation_pending,
    )


def _clean_history_for_llm(history: list[dict] | None, language: str) -> list[dict] | None:
    if not history:
        return history
    
    prefix = get_meeting_collected_prefix(language).strip()
    
    cleaned = []
    for m in history:
        role = m.get("role")
        content = m.get("content", "")
        if role == "assistant" and content:
            if prefix in content:
                parts = content.split(prefix, 1)
                after_prefix = parts[1]
                subparts = after_prefix.split("\n\n", 1)
                if len(subparts) > 1:
                    content = subparts[1].strip()
                else:
                    lines = after_prefix.split("\n")
                    remaining = []
                    for line in lines:
                        if ":" in line or not line.strip():
                            continue
                        remaining.append(line)
                    content = "\n".join(remaining).strip()
            
            summary_prefix = "Here's a summary of your meeting details:" if language != "hindi" else "Aapki meeting ki details ka summary yeh hai:"
            if summary_prefix in content:
                parts = content.split(summary_prefix, 1)
                after_summary = parts[1]
                subparts = after_summary.split("\n\n", 1)
                if len(subparts) > 1:
                    content = subparts[1].strip()
                else:
                    lines = after_summary.split("\n")
                    remaining = []
                    for line in lines:
                        if ":" in line or not line.strip():
                            continue
                        remaining.append(line)
                    content = "\n".join(remaining).strip()
            
        cleaned.append({"role": role, "content": content})
    return cleaned


async def extract_meeting_fields(
    latest_user_msg: str,
    current: MeetingData | None = None,
    language: str = "english",
    history: list[dict] | None = None,
    portfolio_name: str = "",
) -> tuple[str, MeetingData | None, MeetingProgress | None]:
    """
    Extract/validate the next meeting field from user's message using LLM extraction.
    Returns (response_text, updated_meeting_data, progress).
    """
    from agents.llm_client import call_llm
    
    history = _clean_history_for_llm(history, language)
    pname = portfolio_name.strip() if portfolio_name and portfolio_name.strip() else "the portfolio owner"
    
    if current is None:
        current = MeetingData()

    fields = get_meeting_fields(language)
    labels = get_meeting_labels(language)

    # 1. If latest_user_msg is not empty, run the LLM extraction
    if latest_user_msg:
        extract_tool = {
            "type": "function",
            "function": {
                "name": "update_meeting_details",
                "description": "Extract any meeting details mentioned by the user in their message.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "User's full name"},
                        "company_name": {"type": "string", "description": "User's company name"},
                        "company_address": {"type": "string", "description": "Company address"},
                        "email": {"type": "string", "description": "User's email address"},
                        "contact_number": {"type": "string", "description": "User's contact number"},
                        "meeting_purpose": {"type": "string", "description": "Purpose of the meeting"},
                        "meeting_date_time": {"type": "string", "description": "Preferred meeting date and time"},
                        "connection_type": {"type": "string", "enum": ["online", "offline"], "description": "Connection type (online or offline)"},
                    },
                    "required": [],
                },
            },
        }

        system_prompt = f"""You are Daisy, an exceptionally smart, empathetic, and resilient AI assistant for {pname}'s portfolio.
Current meeting state:
- Name: {current.name or "Not provided"}
- Company: {current.company_name or "Not provided"}
- Address: {current.company_address or "Not provided"}
- Email: {current.email or "Not provided"}
- Phone: {current.contact_number or "Not provided"}
- Purpose: {current.meeting_purpose or "Not provided"}
- Meeting Date/Time: {current.meeting_date_time or "Not provided"}
- Meeting Type: {current.connection_type or "Not provided"}

Analyze the user's latest message and extract any new or updated meeting details.
Resilience & 2000IQ Rules:
1. Handle multi-detail statements, interruptions, typos, informal Hinglish, or casual phrasing intelligently.
2. If the user updates an existing detail (e.g. "actually change my email to x@y.com" or "let's do 5pm instead"), extract the updated field.
3. If the user mentions "call", "on call", or "by call" without specifying Google Meet vs Phone Call, leave `connection_type` empty (do not call tool for connection_type) so we can ask for clarification.
4. Call `update_meeting_details` ONLY with the extracted or updated fields. Do not call the tool if no meeting details are present.
"""
        if history:
            messages = [{"role": "system", "content": system_prompt}] + history[-8:]
        else:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": latest_user_msg}
            ]

        try:
            _, tool_call = await call_llm(messages, tools=[extract_tool])
            if tool_call and tool_call.get("name") == "update_meeting_details":
                args = tool_call.get("arguments", {})
                print(f"[Meeting Agent] Extracted arguments from LLM: {args}")
                validation_errors = []
                
                # Check validation for each extracted field before setting it
                for field, val in args.items():
                    if val is not None and str(val).strip() != "":
                        val_str = str(val).strip()
                        if field == "email":
                            if MeetingData.validate_email(val_str):
                                current.email = val_str
                            else:
                                validation_errors.append(get_meeting_validation_error("email", language))
                        elif field == "contact_number":
                            if MeetingData.validate_phone(val_str):
                                current.contact_number = MeetingData.normalize_phone(val_str)
                            else:
                                validation_errors.append(get_meeting_validation_error("contact_number", language))
                        elif field == "connection_type":
                            parsed = MeetingData.validate_connection_type(val_str)
                            if parsed:
                                current.connection_type = parsed
                            else:
                                validation_errors.append(get_meeting_validation_error("connection_type", language))
                        elif field == "meeting_date_time":
                            parsed = parse_datetime(val_str)
                            current.meeting_date_time = parsed or val_str
                        else:
                            setattr(current, field, val_str)
                
                if validation_errors:
                    # Validation failed — return error message and re-prompt
                    err_msg = "\n\n".join(validation_errors)
                    print(f"[Meeting Agent] Validation errors: {err_msg}")
                    progress = _build_progress(current, language)
                    return err_msg, current, progress

        except Exception as e:
            print(f"[Meeting Agent] LLM extraction failed/errored: {e}")

    # 2. Check if all fields are complete
    if current.is_complete():
        current.confirmation_pending = True
        summary = get_meeting_confirmation_summary(
            language,
            name=current.name or "",
            company_name=current.company_name or "",
            company_address=current.company_address or "",
            email=current.email or "",
            contact_number=current.contact_number or "",
            meeting_purpose=current.meeting_purpose or "",
            meeting_date_time=format_datetime_display(current.meeting_date_time) or "",
            connection_type=current.connection_type or "",
        )
        progress = _build_progress(current, language)
        return summary, current, progress

    # 3. If not complete, let the LLM generate the response requesting missing fields
    collected_summary = ""
    for fn, label in labels.items():
        val = getattr(current, fn, None)
        if val:
            val_display = format_datetime_display(val) if fn == "meeting_date_time" else val
            collected_summary += f"- {label}: {val_display}\n"
    if not collected_summary:
        collected_summary = "None yet."
        
    missing_summary = ""
    for fn, label in labels.items():
        val = getattr(current, fn, None)
        if not val:
            missing_summary += f"- {label} ({fn})\n"

    # Show collected details so far in the response (same as before for visual consistency in UI)
    prefix = get_meeting_collected_prefix(language)
    collected_lines = []
    for fn, label in labels.items():
        val = getattr(current, fn, None)
        if val:
            collected_lines.append(f"{label}: {val}")
    
    collected_header = f"{prefix}\n" + "\n".join(collected_lines) + "\n\n" if collected_lines else ""

    # Generate asking text using LLM
    ask_system = f"""You are Daisy, an exceptionally intelligent, empathetic, and professional AI assistant for {pname}'s portfolio.
You are helping a visitor schedule a meeting. You have collected some details, but still need a few more.

Details collected so far:
{collected_summary}

Missing details:
{missing_summary}

Rules for responding:
1. Language: Always respond fluently in {language}.
2. Tone: Warm, welcoming, human, and concise.
3. Multi-detail Extraction: Acknowledge any new details provided in the user's latest message.
4. Handling Messy Input & Hinglish: Understand typos, informal phrasing, slangs, or mixed statements naturally.
5. Connection Type Clarification: If asking for connection type (connection_type) or if user says "call" / "on call", clearly ask if they prefer an "online" meeting via Google Meet OR a direct "Phone Call". Do not mention internal technical terms like "offline" to the user.
6. CRITICAL: Do NOT list or repeat the details already collected (such as name, email, phone, etc.). The system automatically displays the collected list. You must ONLY acknowledge new additions (if any) and naturally ask for missing details.
7. CRITICAL: Plain text ONLY! Do NOT use any markdown formatting (no bold **, no italic *, no backticks).
8. CRITICAL EMAIL & PHONE INSTRUCTION: Whenever asking for Email (email) or Phone Number (contact_number), ALWAYS explicitly tell the user to provide their real and exact email address / phone number so they can receive their interview confirmation, Google Meet link, and notification details.
"""
    
    history_msgs = []
    if history:
        # Include last 4 messages for context
        history_msgs = history[-4:]
    else:
        history_msgs = [{"role": "user", "content": latest_user_msg or "Hello"}]
        
    messages = [{"role": "system", "content": ask_system}] + history_msgs
    
    try:
        response_text, _ = await call_llm(messages)
    except Exception as e:
        print(f"[Meeting Agent] LLM response generation failed, falling back to static questions: {e}")
        # Fallback to static questions
        current_field_idx = get_current_field_index(current, language)
        _, question = fields[current_field_idx]
        response_text = question

    final_resp = f"{collected_header}{response_text}"
    progress = _build_progress(current, language)
    return final_resp, current, progress


def resolve_edit_field(user_msg: str) -> str | None:
    """Map user's edit request to a field name."""
    msg = user_msg.strip().lower()
    mappings = {
        "name": ["name", "naam", "my name"],
        "company_name": ["company", "company name", "company ka naam"],
        "company_address": ["address", "company address", "pata"],
        "email": ["email", "email id", "mail"],
        "contact_number": ["phone", "contact", "number", "mobile", "contact number"],
        "meeting_purpose": ["purpose", "meeting purpose", "agenda", "reason", "kya kaam"],
        "meeting_date_time": ["date", "time", "date/time", "date time", "schedule", "when"],
        "connection_type": ["type", "meeting type", "online", "offline", "mode"],
    }
    for field, keywords in mappings.items():
        for kw in keywords:
            if kw in msg:
                return field
    return None


def parse_n8n_response(data) -> tuple[bool, str, str]:
    """
    Parses n8n webhook response JSON.
    Returns (is_success_or_available, meet_link_or_code, message_or_suggestion)
    """
    item = {}
    if isinstance(data, list) and len(data) > 0:
        item = data[0] if isinstance(data[0], dict) else {}
    elif isinstance(data, dict):
        item = data

    # Check explicit availability or success flags
    avail = item.get("available")
    succ = item.get("success")

    # If marked unavailable or failed
    if (avail is not None and str(avail).lower() in ("false", "0", "no", "unavailable")) or \
       (succ is not None and str(succ).lower() in ("false", "0", "no", "failed")):
        msg = item.get("message") or "The selected time slot is unavailable."
        sugg = item.get("suggestion") or ""
        full_reason = f"{msg} {sugg}".strip()
        return False, "SLOT_UNAVAILABLE", full_reason

    # Find Meet link if present
    meet_link = ""
    for k in ["meet_link", "google_meet_link", "meet_url", "link", "join_url", "url", "meetLink"]:
        v = item.get(k)
        if v and isinstance(v, str) and "http" in v:
            meet_link = v.strip()
            break

    return True, meet_link, ""


async def send_to_n8n(meeting: MeetingData, session_id: str = "") -> tuple[bool, str, str]:
    """
    Triggers n8n meeting creation webhook.
    Returns tuple: (is_ok, link_or_code, msg_or_reason)
    """
    iso_dt_n8n = format_n8n_iso_datetime(meeting.meeting_date_time)

    payload = {
        "name": meeting.name or "",
        "company_name": meeting.company_name or "",
        "company_address": meeting.company_address or "",
        "email": meeting.email or "",
        "contact_number": meeting.contact_number or "",
        "meeting_purpose": meeting.meeting_purpose or "",
        "meeting_date_time": iso_dt_n8n,
        "preferred_time": iso_dt_n8n,
        "connection_type": meeting.connection_type or "",
        "session_id": session_id,
    }

    webhook_url = settings.N8N_MEETING_WEBHOOK_URL
    if not webhook_url:
        print("[n8n Webhook] Error: N8N_MEETING_WEBHOOK_URL is not set.")
        return False, "ERROR", "n8n webhook URL not configured"

    print(f"\n[n8n Webhook] Triggering webhook: {webhook_url}")
    print(f"[n8n Webhook] Payload: {payload}")

    last_error = ""
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(webhook_url, json=payload)
                print(f"[n8n Webhook] Attempt {attempt + 1} response status: {resp.status_code}")
                if resp.status_code in (200, 201, 202):
                    try:
                        data = resp.json()
                        print(f"[n8n Webhook] Response data: {data}")
                        return parse_n8n_response(data)
                    except Exception as json_err:
                        print(f"[n8n Webhook] Response JSON parsing error: {json_err}. Raw text: {resp.text[:300]}")
                        return True, "", ""
                
                last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                print(f"[n8n Webhook] Attempt {attempt + 1} failed: {last_error}")
        except Exception as e:
            last_error = str(e)[:300]
            print(f"[n8n Webhook] Attempt {attempt + 1} exception: {last_error}")

    print(f"[n8n Webhook] Error: All attempts failed. Last error: {last_error}")
    return False, "ERROR", last_error


def format_meeting_response(
    meeting: MeetingData,
    location: str = "",
    portfolio_name: str = "Sahil Thakur",
    portfolio_phone: str = "",
    meet_link: str = "",
    language: str = "english",
) -> str:
    meeting_date_time = format_datetime_display(meeting.meeting_date_time) or "to be confirmed"
    connection_type = (meeting.connection_type or "online").lower()
    phone_display = portfolio_phone.strip() if portfolio_phone and portfolio_phone.strip() else "+91 78451265"
    clean_link = meet_link.strip() if meet_link and isinstance(meet_link, str) else ""

    return get_meeting_confirmation(
        connection_type, bool(clean_link), language,
        meeting_date_time=meeting_date_time,
        meet_link=clean_link,
        location=location or meeting.company_address or "Location to be shared",
        portfolio_name=portfolio_name or "Sahil Thakur",
        portfolio_phone=phone_display,
    )


def build_email_html(
    badge_text: str,
    heading: str,
    intro_text: str,
    details: list[tuple[str, str]],
    cta_link: str = "",
    cta_label: str = "",
    closing_note: str = ""
) -> str:
    """Builds a responsive, high-end HTML email template matching the portfolio theme."""
    rows_html = ""
    for label, val in details:
        rows_html += f"""
        <tr>
          <td style="padding: 10px 0; border-bottom: 1px dashed rgba(255,255,255,0.08); font-size: 14px; color: #94a3b8; width: 38%; font-weight: 600;">{label}</td>
          <td style="padding: 10px 0; border-bottom: 1px dashed rgba(255,255,255,0.08); font-size: 14px; color: #ffffff; width: 62%; font-weight: 500;">{val}</td>
        </tr>
        """

    cta_html = ""
    if cta_link and cta_link.startswith("http"):
        lbl = cta_label or "JOIN GOOGLE MEET"
        cta_html = f"""
        <div style="text-align: center; margin: 28px 0 18px 0;">
          <a href="{cta_link}" target="_blank" style="display: inline-block; background: linear-gradient(135deg, #00f2fe 0%, #4facfe 100%); color: #0a0f1d; font-weight: 800; font-size: 15px; text-decoration: none; padding: 14px 34px; border-radius: 50px; box-shadow: 0 4px 18px rgba(0, 242, 254, 0.4); text-transform: uppercase; letter-spacing: 0.5px;">
            {lbl}
          </a>
        </div>
        """

    closing_html = f'<p style="margin: 18px 0 0 0; font-size: 14px; color: #94a3b8; line-height: 1.5;">{closing_note}</p>' if closing_note else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{badge_text}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #0a0f1d; font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #e2e8f0; line-height: 1.6;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color: #0a0f1d; padding: 30px 15px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width: 600px; background-color: #141c2e; border: 1px solid rgba(0, 242, 254, 0.25); border-radius: 16px; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.5);" cellspacing="0" cellpadding="0" border="0">
          
          <!-- Top Accent Banner -->
          <tr>
            <td style="background: linear-gradient(135deg, #00f2fe 0%, #4facfe 100%); padding: 22px 30px; text-align: left;">
              <h1 style="margin: 0; font-size: 20px; font-weight: 800; color: #0a0f1d; text-transform: uppercase; letter-spacing: 1px;">
                {badge_text}
              </h1>
              <p style="margin: 3px 0 0 0; font-size: 12px; color: #0a0f1d; font-weight: 700; opacity: 0.9;">
                SAHIL THAKUR | AI PORTFOLIO
              </p>
            </td>
          </tr>

          <!-- Email Content Body -->
          <tr>
            <td style="padding: 28px 30px;">
              <h2 style="margin: 0 0 14px 0; font-size: 20px; font-weight: 700; color: #ffffff;">
                {heading}
              </h2>
              
              <p style="margin: 0 0 20px 0; font-size: 15px; color: #cbd5e1;">
                {intro_text}
              </p>

              <!-- Details Box -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color: #0b1120; border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 12px; padding: 18px 20px; margin-bottom: 20px;">
                {rows_html}
              </table>

              {cta_html}
              {closing_html}
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color: #0d1424; padding: 18px 30px; border-top: 1px solid rgba(255,255,255,0.06); text-align: center;">
              <p style="margin: 0; font-size: 12px; color: #64748b;">
                Sent automatically by <strong style="color: #00f2fe;">Sahil Thakur's AI Assistant (Daisy)</strong>
              </p>
              <p style="margin: 4px 0 0 0; font-size: 11px; color: #475569;">
                © 2026 Sahil Thakur. All rights reserved.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _send_email_sync(subject: str, text_body: str, html_body: str, recipient_email: str):
    """Synchronous helper to send HTML + Plain Text email via SMTP."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from config import settings

    user = settings.EMAIL_HOST_USER.strip()
    pwd = settings.EMAIL_HOST_PASSWORD.strip().replace(" ", "")
    from_email = settings.DEFAULT_FROM_EMAIL.strip() or user

    if not user or not pwd or not recipient_email.strip():
        print("[Meeting Agent Email] SMTP credentials or recipient missing, skipping email send.")
        return

    msg = MIMEMultipart('alternative')
    msg['From'] = from_email
    msg['To'] = recipient_email.strip()
    msg['Subject'] = subject

    msg.attach(MIMEText(text_body, 'plain'))
    if html_body:
        msg.attach(MIMEText(html_body, 'html'))

    try:
        if settings.EMAIL_USE_TLS:
            server = smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT, timeout=15)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(settings.EMAIL_HOST, settings.EMAIL_PORT, timeout=15)

        server.login(user, pwd)
        server.send_message(msg)
        server.quit()
        print(f"[Meeting Agent Email] Successfully sent HTML email to {recipient_email}")
    except Exception as e:
        print(f"[Meeting Agent Email] Failed to send email to {recipient_email}: {e}")


async def send_interview_email_notification(
    meeting: MeetingData,
    meet_link: str = "",
    portfolio_name: str = "Sahil Thakur",
    portfolio_phone: str = "",
):
    """
    Asynchronously triggers HTML email notifications when an interview is scheduled.
    Sends styled HTML emails to Sahil (NOTIFICATION_EMAIL) and Recruiter (meeting.email).
    Runs non-blocking in background thread.
    """
    from config import settings

    sahil_name = portfolio_name.strip() if portfolio_name and portfolio_name.strip() else "Sahil Thakur"
    phone_display = portfolio_phone.strip() if portfolio_phone and portfolio_phone.strip() else "+91 78451265"
    meeting_time = format_datetime_display(meeting.meeting_date_time) or "To be confirmed"
    interviewer_name = meeting.name or "Recruiter / Visitor"
    company_name = meeting.company_name or "Not specified"
    conn_type = (meeting.connection_type or "online").lower()

    if conn_type == "online":
        # Admin / Owner Email (Google Meet) -> Sent to Sahil Thakur
        subject_admin = f"New Interview Scheduled by {interviewer_name} ({company_name})"
        text_admin = f"Hello {sahil_name},\n\n{interviewer_name} from {company_name} has scheduled an interview to interview you on {meeting_time}.\nGoogle Meet Link: {meet_link or 'Link to be shared'}\n"
        html_admin = build_email_html(
            badge_text="NEW INTERVIEW REQUEST FOR YOU",
            heading=f"New Google Meet Interview Scheduled",
            intro_text=f"Hello <strong>{sahil_name}</strong>, <strong>{interviewer_name}</strong> from <strong>{company_name}</strong> has scheduled an online interview to interview you!",
            details=[
                ("Interviewer Name", interviewer_name),
                ("Company Name", company_name),
                ("Company Address", meeting.company_address or 'Not specified'),
                ("Interviewer Email", meeting.email or 'Not specified'),
                ("Interviewer Phone", meeting.contact_number or 'Not specified'),
                ("Purpose / Position", meeting.meeting_purpose or 'Interview'),
                ("Date & Time", meeting_time),
                ("Interview Mode", "Google Meet (Online)"),
                ("Google Meet Link", f'<a href="{meet_link}" style="color:#00f2fe;font-weight:700;">{meet_link}</a>' if meet_link else 'Link to be shared')
            ],
            cta_link=meet_link if meet_link and meet_link.startswith("http") else "",
            cta_label="JOIN GOOGLE MEET ROOM",
            closing_note="Please check your calendar to ensure you are ready for the interview at the scheduled time."
        )

        # Recruiter Email (Google Meet) -> Sent to Recruiter/Employer
        subject_candidate = f"Interview Confirmed with Candidate {sahil_name} (Google Meet)"
        text_candidate = f"Hello {interviewer_name},\n\nYour interview with candidate {sahil_name} has been scheduled for {meeting_time}.\nGoogle Meet Link: {meet_link or 'Link will be sent shortly'}\n"
        html_candidate = build_email_html(
            badge_text="CONFIRMATION: INTERVIEW SCHEDULED",
            heading=f"Your Interview with Candidate {sahil_name} is Confirmed",
            intro_text=f"Hello <strong>{interviewer_name}</strong>, your Google Meet interview with candidate <strong>{sahil_name}</strong> has been successfully scheduled!",
            details=[
                ("Candidate Name", sahil_name),
                ("Interviewer Name", interviewer_name),
                ("Company", company_name),
                ("Position / Purpose", meeting.meeting_purpose or 'Interview'),
                ("Date & Time", meeting_time),
                ("Google Meet Link", f'<a href="{meet_link}" style="color:#00f2fe;font-weight:700;">{meet_link}</a>' if meet_link else 'Link will be sent shortly')
            ],
            cta_link=meet_link if meet_link and meet_link.startswith("http") else "",
            cta_label="JOIN GOOGLE MEET",
            closing_note=f"Thank you for scheduling an interview with {sahil_name}. If you need to make any changes, please reply to this email."
        )
    else:
        # Admin / Owner Email (Phone Call) -> Sent to Sahil Thakur
        subject_admin = f"New Direct Phone Call Interview Scheduled by {interviewer_name} ({company_name})"
        text_admin = f"Hello {sahil_name},\n\n{interviewer_name} from {company_name} scheduled a direct phone call interview with you for {meeting_time}.\nRecruiter Phone: {meeting.contact_number}\n"
        html_admin = build_email_html(
            badge_text="NEW INTERVIEW REQUEST FOR YOU (PHONE CALL)",
            heading=f"New Direct Phone Call Interview Scheduled",
            intro_text=f"Hello <strong>{sahil_name}</strong>, <strong>{interviewer_name}</strong> from <strong>{company_name}</strong> has scheduled a direct phone call interview with you!",
            details=[
                ("Interviewer Name", interviewer_name),
                ("Company Name", company_name),
                ("Company Address", meeting.company_address or 'Not specified'),
                ("Interviewer Email", meeting.email or 'Not specified'),
                ("Interviewer Phone", meeting.contact_number or 'Not specified'),
                ("Purpose / Position", meeting.meeting_purpose or 'Interview'),
                ("Date & Time", meeting_time),
                ("Interview Mode", "Direct Phone Call"),
                ("Your Phone Shared", phone_display)
            ],
            closing_note=f"<strong>Note:</strong> {interviewer_name} will call you at <strong>{phone_display}</strong> or you can reach them at <strong>{meeting.contact_number or 'their provided number'}</strong> at {meeting_time}."
        )

        # Recruiter Email (Phone Call) -> Sent to Recruiter/Employer
        subject_candidate = f"Phone Call Interview Confirmed with Candidate {sahil_name}"
        text_candidate = f"Hello {interviewer_name},\n\nYour phone call interview with candidate {sahil_name} has been scheduled for {meeting_time}.\n"
        html_candidate = build_email_html(
            badge_text="CONFIRMATION: INTERVIEW SCHEDULED",
            heading=f"Your Phone Call Interview is Confirmed",
            intro_text=f"Hello <strong>{interviewer_name}</strong>, your phone call interview with candidate <strong>{sahil_name}</strong> has been successfully scheduled!",
            details=[
                ("Candidate Name", sahil_name),
                ("Interviewer Name", interviewer_name),
                ("Company", company_name),
                ("Position / Purpose", meeting.meeting_purpose or 'Interview'),
                ("Date & Time", meeting_time),
                ("Candidate Phone", phone_display)
            ],
            closing_note=f"You can call candidate <strong>{sahil_name}</strong> at <strong>{phone_display}</strong> or expect a call at <strong>{meeting.contact_number}</strong> at the scheduled time."
        )

    # Send to Sahil (NOTIFICATION_EMAIL or EMAIL_HOST_USER)
    admin_recipient = settings.NOTIFICATION_EMAIL.strip() or settings.EMAIL_HOST_USER.strip()
    if admin_recipient:
        asyncio.create_task(asyncio.to_thread(_send_email_sync, subject_admin, text_admin, html_admin, admin_recipient))

    # Send to Candidate (meeting.email)
    candidate_recipient = (meeting.email or "").strip()
    if candidate_recipient:
        asyncio.create_task(asyncio.to_thread(_send_email_sync, subject_candidate, text_candidate, html_candidate, candidate_recipient))
