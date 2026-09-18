import re
import time
from collections import defaultdict
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db import get_session
from schemas import ChatRequest, ChatResponse, MeetingData, MeetingProgress
from database.chat_store import ChatStore
from database.meeting_store import MeetingStore
from memory import session_manager
from models import HeroInfo
from agents.router import classify_intent
from agents.meeting_agent import (
    extract_meeting_fields, send_to_n8n, format_meeting_response,
    resolve_edit_field, get_current_field_index, _build_progress,
    format_datetime_display, parse_datetime, send_interview_email_notification,
)
from agents.answer_agent import generate_answer
from prompts import (
    get_greeting, get_meeting_fields,
    get_meeting_cancel_message, get_meeting_edit_prompt,
    get_meeting_confirmation_summary, get_meeting_start_message,
)
from config import settings

router = APIRouter()

# ── Security Tracking (In-memory) ───────────────────────────────────────────

_ip_request_timestamps = defaultdict(list)
_session_message_counts = defaultdict(int)


def check_ip_rate_limit(client_ip: str) -> bool:
    """Returns True if request allowed, False if IP rate limit exceeded (max 10 req/min)."""
    now = time.time()
    cutoff = now - 60.0
    timestamps = [t for t in _ip_request_timestamps[client_ip] if t > cutoff]
    _ip_request_timestamps[client_ip] = timestamps
    if len(timestamps) >= settings.MAX_IP_REQUESTS_PER_MIN:
        return False
    _ip_request_timestamps[client_ip].append(now)
    return True


import hashlib
import secrets

def verify_internal_api_key(
    request: Request,
    x_internal_api_key: str = Header(None, alias="X-Internal-API-Key")
):
    """Verify internal API key header for FastAPI Firewall using SHA-256 hash comparison."""
    if request.method == "OPTIONS":
        return
    if not x_internal_api_key or not settings.INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing internal API key")
    
    hashed_incoming = hashlib.sha256(x_internal_api_key.encode()).hexdigest()
    if (
        secrets.compare_digest(x_internal_api_key, settings.INTERNAL_API_KEY) or
        secrets.compare_digest(hashed_incoming, settings.INTERNAL_API_KEY)
    ):
        return
    raise HTTPException(status_code=403, detail="Invalid or missing internal API key")

# ── Cancel / Confirm keyword detection ──────────────────────────────────────

CANCEL_KEYWORDS = [
    "cancel", "exit", "quit", "stop", "nahi", "nahi chahiye",
    "band karo", "ruko", "mat karo", "no thanks", "nevermind", "never mind",
]

CONFIRM_KEYWORDS = [
    "confirm", "yes", "haan", "okay", "theek hai",
    "thik hai", "schedule karo", "book karo", "done", "proceed",
    "confirmed", "sure", "bilkul",
]

EDIT_KEYWORDS = [
    "edit", "change", "modify", "update", "badlo", "correct",
    "galat hai", "wrong", "fix",
]


def _detect_cancel(msg: str) -> bool:
    """Check if user wants to cancel (works at any time)."""
    lower = msg.strip().lower()
    for kw in CANCEL_KEYWORDS:
        if kw == lower or lower.startswith(kw + " "):
            return True
    return False


def _is_confirm(msg: str) -> bool:
    """Check if user explicitly confirms (only valid during confirmation-pending)."""
    lower = msg.strip().lower()
    for kw in CONFIRM_KEYWORDS:
        if kw == lower or lower.startswith(kw + " "):
            return True
    return False


def _is_edit(msg: str) -> bool:
    """Check if user wants to edit (only valid during confirmation-pending)."""
    lower = msg.strip().lower()
    for kw in EDIT_KEYWORDS:
        if kw == lower or lower.startswith(kw + " "):
            return True
    return False


def _clean(text: str) -> str:
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'`(.+?)`', r'\1', text)
    return text.strip()


async def _get_hero(db: AsyncSession) -> dict:
    try:
        r = await db.execute(select(HeroInfo).limit(1))
        h = r.scalar_one_or_none()
        if h:
            return {"name": h.name or "", "location": h.location or "", "phone": h.phone or ""}
    except Exception:
        pass
    return {"name": "", "location": "", "phone": ""}


async def _finalize_meeting(
    m: MeetingData, sid: str, store: ChatStore, ms: MeetingStore,
    hero: dict, lang: str = "",
) -> ChatResponse:
    ok, link_or_code, reason = await send_to_n8n(m, sid)

    # Handle slot unavailable from n8n
    if not ok and link_or_code == "SLOT_UNAVAILABLE":
        time_display = format_datetime_display(m.meeting_date_time) or m.meeting_date_time or "the selected time"
        m.meeting_date_time = ""  # Reset date/time field so candidate can enter a new slot
        m.confirmation_pending = False
        session_manager.set_pending_meeting(sid, m)
        session_manager.set_confirmation_pending(sid, False)

        # Update DB pending record so re-loads don't revive the unavailable date/time
        pending_rec = await ms.get_by_session(sid)
        if pending_rec:
            pending_rec.meeting_date_time = ""
            pending_rec.status = "pending"
            await ms.session.commit()

        if lang == "hindi":
            msg = f"Aapka chuna hua time slot ({time_display}) filhal available nahi hai. {reason}\n\nKripya koi dusri date ya time batayein jo aapke liye comfortable ho."
        else:
            msg = f"The selected time slot ({time_display}) is currently unavailable. {reason}\n\nPlease choose a different date and time that works best for you!"

        msg = _clean(msg)
        await store.add_message(sid, "assistant", msg)

        # Build progress bar resetting to time selection
        progress = _build_progress(m, lang)
        return ChatResponse(
            message=msg,
            session_id=sid,
            intent="meeting",
            meeting_progress=progress,
            suggested_questions=[],
            context_retrieved=False,
            meeting_confirmed=False
        )

    link = link_or_code if ok else ""
    pending_rec = await ms.get_by_session(sid)
    if pending_rec and pending_rec.status == 'pending':
        pending_rec.name = m.name
        pending_rec.company_name = m.company_name
        pending_rec.company_address = m.company_address
        pending_rec.email = m.email
        pending_rec.contact_number = m.contact_number
        pending_rec.meeting_purpose = m.meeting_purpose
        pending_rec.meeting_date_time = m.meeting_date_time
        pending_rec.connection_type = m.connection_type
        pending_rec.meet_link = link if ok else None
        pending_rec.status = "confirmed" if ok else "pending"
        pending_rec.n8n_webhook_status = "success" if ok else "failed"
        await ms.session.commit()
        rec = pending_rec
    else:
        rec = await ms.save_request({
            "session_id": sid, "name": m.name, "company_name": m.company_name,
            "company_address": m.company_address, "email": m.email,
            "contact_number": m.contact_number,
            "meeting_purpose": m.meeting_purpose,
            "meeting_date_time": m.meeting_date_time,
            "connection_type": m.connection_type,
            "meet_link": link if ok else None,
            "status": "confirmed" if ok else "pending",
            "n8n_webhook_status": "success" if ok else "failed",
        })
    session_manager.set_meeting_result(sid, rec.id, link if ok else None)
    session_manager.set_pending_intent(sid, "")
    session_manager.set_confirmation_pending(sid, False)
    if not ok:
        await ms.mark_failed(rec.id)

    msg = format_meeting_response(
        m, location=hero.get("location", ""),
        portfolio_name=hero.get("name", "Sahil Thakur"),
        portfolio_phone=hero.get("phone", ""),
        meet_link=link if ok else "", language=lang,
    )
    msg = _clean(msg)
    await store.add_message(sid, "assistant", msg)

    # Trigger background email notification (to Sahil & Candidate)
    try:
        import asyncio
        asyncio.create_task(
            send_interview_email_notification(
                meeting=m,
                meet_link=link if ok else "",
                portfolio_name=hero.get("name", "Sahil Thakur"),
                portfolio_phone=hero.get("phone", ""),
            )
        )
    except Exception as e:
        print(f"[Meeting Email Trigger Error]: {e}")

    # Build final success progress
    progress = MeetingProgress(
        step=8, total=8, field="",
        completed_fields={},
        confirmation_pending=False,
        cancelled=False,
    )

    return ChatResponse(
        message=msg, session_id=sid, intent="meeting_confirmed",
        language=lang, meeting_progress=progress,
    )


async def _handle_cancel(
    sid: str, store: ChatStore, ms: MeetingStore, lang: str = "",
) -> ChatResponse:
    session_manager.clear_meeting(sid)
    await ms.cancel_active_request(sid)
    msg = _clean(get_meeting_cancel_message(lang))
    await store.add_message(sid, "assistant", msg)

    progress = MeetingProgress(
        step=0, total=7, field="", completed_fields={},
        confirmation_pending=False, cancelled=True,
    )
    return ChatResponse(
        message=msg, session_id=sid, intent="meeting_cancelled",
        language=lang, meeting_progress=progress,
    )


def _detect_resend_email(msg: str) -> bool:
    m = msg.lower().strip()
    keywords = [
        "resend", "reshare", "send again", "send email again",
        "send mail again", "email again", "mail again", "dobara email", "dobara mail",
        "phirse email", "phirse mail", "email dobara", "mail dobara", "mail nahi aaya",
        "email nahi aaya", "confirmation email", "confirmation mail"
    ]
    if any(k in m for k in keywords):
        return True

    has_action = any(w in m for w in ["send", "resend", "reshare", "bhej", "dobara", "phirse"])
    has_target = any(w in m for w in ["email", "mail", "confirmation", "again"])
    return has_action and has_target


async def _handle_resend_email(
    sid: str, store: ChatStore, ms: MeetingStore, hero: dict, lang: str = ""
) -> ChatResponse:
    rec = await ms.get_by_session(sid)
    if not rec:
        msg = (
            "I couldn't find a scheduled interview for your current session. Please schedule an interview first!"
            if lang != "hindi"
            else "Aapke iss session me koi scheduled interview nahi mila. Kripya pehle interview schedule karein!"
        )
        msg = _clean(msg)
        await store.add_message(sid, "assistant", msg)
        return ChatResponse(message=msg, session_id=sid, intent="resend_email_failed", language=lang)

    m = MeetingData(
        name=rec.name,
        company_name=rec.company_name,
        company_address=rec.company_address,
        email=rec.email,
        contact_number=rec.contact_number,
        meeting_purpose=rec.meeting_purpose,
        meeting_date_time=rec.meeting_date_time,
        connection_type=rec.connection_type,
    )

    import asyncio
    asyncio.create_task(
        send_interview_email_notification(
            meeting=m,
            meet_link=rec.meet_link or "",
            portfolio_name=hero.get("name", "Sahil Thakur"),
            portfolio_phone=hero.get("phone", ""),
        )
    )

    recipient_email = rec.email or "your email address"
    msg = (
        f"I have successfully resent the interview confirmation email to {recipient_email}! Please check your inbox (and spam folder)."
        if lang != "hindi"
        else f"Maine interview ki confirmation email {recipient_email} par dobara bhej di hai! Kripya apna inbox (aur spam folder) check karein."
    )
    msg = _clean(msg)
    await store.add_message(sid, "assistant", msg)
    return ChatResponse(message=msg, session_id=sid, intent="resend_email_success", language=lang)


async def _handle_meeting(
    m: MeetingData, user_msg: str, sid: str,
    store: ChatStore, ms: MeetingStore, hero: dict, lang: str = "",
    history: list[dict] | None = None,
) -> ChatResponse:
    pname = hero.get("name", "")
    print(f"\n--- [handle_meeting] user_msg: {repr(user_msg)} ---")
    # Cancel works at any point during meeting flow
    if _detect_cancel(user_msg):
        print("--- [handle_meeting] canceling active meeting ---")
        return await _handle_cancel(sid, store, ms, lang)

    # Confirm/edit keywords ONLY work when all details are filled
    if session_manager.is_confirmation_pending(sid):
        if _is_confirm(user_msg):
            session_manager.set_pending_meeting(sid, None)
            session_manager.set_confirmation_pending(sid, False)
            return await _finalize_meeting(m, sid, store, ms, hero, lang)

        if _is_edit(user_msg):
            # Check if user specified which field to edit inline
            field = resolve_edit_field(user_msg)
            if field:
                # Clear that field so it gets re-asked
                setattr(m, field, None)
                m.confirmation_pending = False
                session_manager.set_confirmation_pending(sid, False)
                session_manager.set_pending_meeting(sid, m)
                await ms.save_or_update_pending(sid, m)
                # Now extract will ask for the cleared field
                resp, updated, progress = await extract_meeting_fields("", m, lang, history, portfolio_name=pname)
                resp = _clean(resp)
                await store.add_message(sid, "assistant", resp)
                return ChatResponse(
                    message=resp, session_id=sid, intent="meeting",
                    language=lang, meeting_progress=progress,
                )
            else:
                # Ask which field to edit
                edit_prompt = _clean(get_meeting_edit_prompt(lang))
                await store.add_message(sid, "assistant", edit_prompt)
                progress = _build_progress(m, lang)
                return ChatResponse(
                    message=edit_prompt, session_id=sid, intent="meeting_edit",
                    language=lang, meeting_progress=progress,
                )

        # User might be specifying which field to edit (after "edit" was said before)
        field = resolve_edit_field(user_msg)
        if field:
            setattr(m, field, None)
            m.confirmation_pending = False
            session_manager.set_confirmation_pending(sid, False)
            session_manager.set_pending_meeting(sid, m)
            await ms.save_or_update_pending(sid, m)
            resp, updated, progress = await extract_meeting_fields("", m, lang, history, portfolio_name=pname)
            resp = _clean(resp)
            await store.add_message(sid, "assistant", resp)
            return ChatResponse(
                message=resp, session_id=sid, intent="meeting",
                language=lang, meeting_progress=progress,
            )

        # User sent a message with new/updated details (e.g. new date/time)
        resp, updated, progress = await extract_meeting_fields(user_msg, m, lang, history, portfolio_name=pname)
        if updated and updated.is_complete() and updated.confirmation_pending:
            await ms.save_or_update_pending(sid, updated)
            return await _finalize_meeting(updated, sid, store, ms, hero, lang)

        session_manager.set_pending_intent(sid, "meeting")
        session_manager.set_pending_meeting(sid, updated)
        await ms.save_or_update_pending(sid, updated)
        resp = _clean(resp)
        await store.add_message(sid, "assistant", resp)
        return ChatResponse(
            message=resp, session_id=sid, intent="meeting",
            language=lang, meeting_progress=progress,
        )

    # Normal field collection
    resp, updated, progress = await extract_meeting_fields(user_msg, m, lang, history, portfolio_name=pname)

    if updated and updated.is_complete() and updated.confirmation_pending:
        # Auto-finalize: all 8 fields collected, save & send to n8n directly
        await ms.save_or_update_pending(sid, updated)
        return await _finalize_meeting(updated, sid, store, ms, hero, lang)

    session_manager.set_pending_intent(sid, "meeting")
    session_manager.set_pending_meeting(sid, updated)
    await ms.save_or_update_pending(sid, updated)
    resp = _clean(resp)
    await store.add_message(sid, "assistant", resp)
    return ChatResponse(
        message=resp, session_id=sid, intent="meeting",
        language=lang, meeting_progress=progress,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    req: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_session),
    _key: None = Depends(verify_internal_api_key),
):
    sid = req.session_id or "anon"
    msg = req.message.strip()
    lang = req.language.strip().lower() if req.language.strip() else ""
    client_ip = request.client.host if request.client else "127.0.0.1"

    # 1. IP Rate Limiting Check (Max 10 requests / min)
    if not check_ip_rate_limit(client_ip):
        limit_msg = (
            "Security Notice: Rate limit exceeded (max 10 requests/min). Please wait a moment before sending another message."
            if lang != "hindi"
            else "Suraksha Notice: Rate limit exceed ho gaya hai (max 10 requests/min). Kripya thoda wait karke dobara message karein."
        )
        return ChatResponse(message=limit_msg, session_id=sid, intent="security_notice", language=lang)

    # 2. Input Length Check (Max 350 characters)
    if len(msg) > settings.MAX_MESSAGE_LENGTH:
        len_msg = (
            f"Security Notice: Your message exceeds the maximum allowed length ({settings.MAX_MESSAGE_LENGTH} characters). To prevent token abuse, please keep your query concise."
            if lang != "hindi"
            else f"Suraksha Notice: Aapka message maximum allowed length ({settings.MAX_MESSAGE_LENGTH} characters) se bada hai. Token save karne ke liye message chhota likhein."
        )
        return ChatResponse(message=len_msg, session_id=sid, intent="security_notice", language=lang)

    # 3. Session Message Count Check (Max 20 messages per session)
    if msg:
        if _session_message_counts[sid] >= settings.MAX_SESSION_MESSAGES:
            sess_msg = (
                f"Security Notice: You have reached the maximum message limit ({settings.MAX_SESSION_MESSAGES} messages per session) for this chat. This rate-limiting rule is active to protect Sahil's AI Assistant tokens and server resources from automated abuse. Please refresh the page or start a new session to continue."
                if lang != "hindi"
                else f"Suraksha Notice: Aapne is session ki maximum message limit ({settings.MAX_SESSION_MESSAGES} messages) reach kar li hai. Tokens aur server resources ko protect karne ke liye yeh security rule active hai. Kripya naya session shuru karne ke liye page refresh karein."
            )
            return ChatResponse(message=sess_msg, session_id=sid, intent="security_notice", language=lang)
        _session_message_counts[sid] += 1

    hero = await _get_hero(db)
    pname = hero.get("name", "")

    store = ChatStore(db)
    ms = MeetingStore(db)
    mem = session_manager.get_or_create(sid)

    if lang in ("english", "hindi") and not msg:
        session_manager.set_language(sid, lang)
        g = _clean(get_greeting(lang, portfolio_name=pname))
        await store.add_message(sid, "assistant", g)
        return ChatResponse(message=g, session_id=sid, intent="language_set", language=lang)

    if not lang:
        lang = session_manager.get_language(sid)
    if lang:
        session_manager.set_language(sid, lang)

    if not msg:
        g = _clean(get_greeting(lang, portfolio_name=pname))
        return ChatResponse(message=g, session_id=sid, intent="greeting", language=lang)

    await store.add_message(sid, "user", msg)
    history = await session_manager.format_history(db, sid)
    await session_manager.load_from_db(db, sid)

    # ── Check for Resend Email Intent ───────────────────────────────────────
    if _detect_resend_email(msg):
        return await _handle_resend_email(sid, store, ms, hero, lang)

    # ── Active meeting flow (pending intent or pending meeting data) ────────
    pi = session_manager.get_pending_intent(sid)
    
    if pi == "meeting_clarify":
        if _is_confirm(msg):
            m = MeetingData()
            fields = get_meeting_fields(lang)
            first_q = _clean(fields[0][1])
            resp = get_meeting_start_message(first_q, lang, portfolio_name=pname)
            await store.add_message(sid, "assistant", resp)
            session_manager.set_pending_intent(sid, "meeting")
            session_manager.set_pending_meeting(sid, m)

            progress = MeetingProgress(
                step=1, total=len(fields), field=fields[0][0],
                completed_fields={},
            )
            return ChatResponse(
                message=resp, session_id=sid, intent="meeting",
                language=lang, meeting_progress=progress,
            )
        elif _detect_cancel(msg):
            session_manager.set_pending_intent(sid, "")
            resp = "No problem! Let me know if you need help with anything else." if lang != "hindi" else "Koi baat nahi! Agar aapko kisi aur cheez mein madad chahiye toh batayein."
            await store.add_message(sid, "assistant", resp)
            return ChatResponse(message=resp, session_id=sid, intent="general", language=lang)
        else:
            session_manager.set_pending_intent(sid, "")
            pi = ""

    if pi in ("meeting", "meeting_confirmation") or mem.pending_meeting is not None:
        m = mem.pending_meeting or MeetingData()
        return await _handle_meeting(m, msg, sid, store, ms, hero, lang, history)

    # ── Router classification ───────────────────────────────────────────────
    intent, args = await classify_intent(history, pname)

    if intent == "meeting":
        # Check if the initial message is a vague single-word keyword
        msg_lower = msg.lower().strip()
        is_single_word_meeting = len(msg_lower.split()) == 1 and any(w in msg_lower for w in ["meeting", "appoint", "call", "schedule", "book"])
        
        if is_single_word_meeting:
            resp = f"What do you mean by interview? Would you like to schedule an interview with {pname or 'the portfolio owner'}?" if lang != "hindi" else f"Aapka interview se kya matlab hai? Kya aap {pname or 'portfolio owner'} ke saath interview schedule karna chahte hain?"
            await store.add_message(sid, "assistant", resp)
            session_manager.set_pending_intent(sid, "meeting_clarify")
            return ChatResponse(message=resp, session_id=sid, intent="meeting_clarify", language=lang)

        m = MeetingData(**{k: v for k, v in args.items() if v})

        # Validate and clean fields extracted by the router
        if m.email and not MeetingData.validate_email(m.email):
            m.email = None
        if m.contact_number:
            if MeetingData.validate_phone(m.contact_number):
                m.contact_number = MeetingData.normalize_phone(m.contact_number)
            else:
                m.contact_number = None
        if m.meeting_date_time:
            parsed = parse_datetime(m.meeting_date_time)
            if parsed:
                m.meeting_date_time = parsed

        # Check if router already extracted some fields from the first message
        has_extracted = any(getattr(m, f, None) for f in [
            "name", "company_name", "company_address",
            "email", "contact_number", "meeting_purpose",
            "meeting_date_time", "connection_type",
        ])

        if has_extracted:
            # Router extracted some data — continue from where we are
            return await _handle_meeting(m, "", sid, store, ms, hero, lang, history)
        else:
            # No fields extracted — start fresh, ask first question
            fields = get_meeting_fields(lang)
            first_q = _clean(fields[0][1])
            resp = get_meeting_start_message(first_q, lang, portfolio_name=pname)
            await store.add_message(sid, "assistant", resp)
            session_manager.set_pending_intent(sid, "meeting")
            session_manager.set_pending_meeting(sid, m)
            
            progress = MeetingProgress(
                step=1, total=len(fields), field=fields[0][0],
                completed_fields={},
            )
            return ChatResponse(
                message=resp, session_id=sid, intent="meeting",
                language=lang, meeting_progress=progress,
            )

    # ── General query ───────────────────────────────────────────────────────
    ans = await generate_answer(query=msg, history=history, portfolio_name=pname, language=lang)
    ans = _clean(ans)
    await store.add_message(sid, "assistant", ans)
    return ChatResponse(message=ans, session_id=sid, intent="general_query", language=lang)
