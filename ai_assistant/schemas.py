from pydantic import BaseModel
from typing import Optional
import re


class ChatRequest(BaseModel):
    message: str = ""
    visitor_role: str = ""
    session_id: str = ""
    language: str = ""


class MeetingProgress(BaseModel):
    step: int = 0
    total: int = 8
    field: str = ""
    completed_fields: dict = {}
    confirmation_pending: bool = False
    cancelled: bool = False


class ChatResponse(BaseModel):
    message: str
    session_id: str = ""
    intent: str = "general_query"
    language: str = ""
    meeting_progress: Optional[MeetingProgress] = None


class MeetingData(BaseModel):
    name: Optional[str] = None
    company_name: Optional[str] = None
    company_address: Optional[str] = None
    email: Optional[str] = None
    contact_number: Optional[str] = None
    meeting_purpose: Optional[str] = None
    meeting_date_time: Optional[str] = None
    connection_type: Optional[str] = None
    confirmation_pending: bool = False

    def is_complete(self) -> bool:
        required = [
            self.name, self.company_name, self.company_address,
            self.email, self.contact_number, self.meeting_purpose,
            self.meeting_date_time, self.connection_type
        ]
        return all(r is not None and r.strip() != "" for r in required)

    @staticmethod
    def validate_email(email: str) -> bool:
        email = email.strip()
        if not email or len(email) > 254:
            return False
        pattern = r'^[a-zA-Z0-9][a-zA-Z0-9._%+-]{0,63}@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$'
        if not re.match(pattern, email):
            return False
        local, domain = email.rsplit("@", 1)
        if ".." in domain or local.startswith(".") or local.endswith("."):
            return False
        return True

    @staticmethod
    def validate_phone(phone: str) -> bool:
        cleaned = re.sub(r'[\s\-\(\)]', '', phone.strip())
        # Allow optional leading +
        if cleaned.startswith("+"):
            digits = cleaned[1:]
        else:
            digits = cleaned
        if not digits.isdigit():
            return False
        if 7 <= len(digits) <= 15:
            return True
        return False

    @staticmethod
    def normalize_phone(phone: str) -> str:
        cleaned = re.sub(r'[^\d+]', '', phone.strip())
        if cleaned.startswith("+"):
            return cleaned
        return "+" + cleaned if cleaned else cleaned

    @staticmethod
    def validate_connection_type(value: str) -> Optional[str]:
        val = value.strip().lower()

        # Direct Google Meet keywords -> online
        if any(kw in val for kw in ['google meet', 'gmeet', 'google-meet', 'meet link']):
            return 'online'

        # Direct Phone Call keywords -> offline (phone call)
        if any(kw in val for kw in ['phone call', 'phone', 'mobile call', 'telephonic', 'call on phone', 'phonecall']):
            return 'offline'

        # Generic online keywords
        if any(kw in val for kw in ['online', 'virtual', 'remote', 'video call', 'video', 'zoom']):
            return 'online'

        # Generic offline / in-person keywords
        if any(kw in val for kw in ['offline', 'in-person', 'in person', 'physical', 'face to face', 'onsite']):
            return 'offline'

        # Ambiguous keywords like "call", "by call", "on call", "by on call" without specifying Google Meet vs Phone Call:
        # Return None so the assistant asks to clarify between Google Meet or Phone Call!
        return None

    def missing_fields(self) -> list[str]:
        mapping = {
            "name": "aapka naam",
            "company_name": "company ka naam",
            "company_address": "company ka address",
            "email": "aapki email ID",
            "contact_number": "aapka contact number",
            "meeting_purpose": "meeting ka purpose",
            "meeting_date_time": "meeting ki date aur time",
            "connection_type": "connection type (online ya offline)",
        }
        missing = []
        for field, label in mapping.items():
            val = getattr(self, field, None)
            if val is None or str(val).strip() == "":
                missing.append(label)
        return missing


class ReindexResponse(BaseModel):
    status: str
    documents_indexed: int
