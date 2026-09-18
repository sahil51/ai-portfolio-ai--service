from dataclasses import dataclass, field
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from database.chat_store import ChatStore
from database.meeting_store import MeetingStore
from schemas import MeetingData


@dataclass
class SessionMemory:
    session_id: str
    visitor_role: str = ""
    language: str = ""
    pending_meeting: Optional[MeetingData] = None
    last_meeting_request_id: Optional[int] = None
    last_meet_link: Optional[str] = None
    pending_intent: str = ""
    meeting_confirmation_pending: bool = False


class SessionManager:
    _sessions: dict[str, SessionMemory] = {}

    def get_or_create(self, session_id: str) -> SessionMemory:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionMemory(session_id=session_id)
        return self._sessions[session_id]

    def set_language(self, session_id: str, language: str):
        mem = self.get_or_create(session_id)
        mem.language = language

    def get_language(self, session_id: str) -> str:
        mem = self.get_or_create(session_id)
        return mem.language or "english"

    def update_role(self, session_id: str, role: str):
        mem = self.get_or_create(session_id)
        mem.visitor_role = role

    def set_pending_meeting(self, session_id: str, meeting: MeetingData):
        mem = self.get_or_create(session_id)
        mem.pending_meeting = meeting

    def get_pending_meeting(self, session_id: str) -> Optional[MeetingData]:
        mem = self.get_or_create(session_id)
        return mem.pending_meeting

    def set_meeting_result(self, session_id: str, request_id: int, meet_link: Optional[str] = None):
        mem = self.get_or_create(session_id)
        mem.last_meeting_request_id = request_id
        mem.last_meet_link = meet_link
        mem.pending_meeting = None

    def set_pending_intent(self, session_id: str, intent: str):
        mem = self.get_or_create(session_id)
        mem.pending_intent = intent

    def get_pending_intent(self, session_id: str) -> str:
        mem = self.get_or_create(session_id)
        return mem.pending_intent

    def set_confirmation_pending(self, session_id: str, pending: bool):
        mem = self.get_or_create(session_id)
        mem.meeting_confirmation_pending = pending

    def is_confirmation_pending(self, session_id: str) -> bool:
        mem = self.get_or_create(session_id)
        return mem.meeting_confirmation_pending

    def clear_meeting(self, session_id: str):
        """Fully reset meeting state (for cancel flow)."""
        mem = self.get_or_create(session_id)
        mem.pending_meeting = None
        mem.pending_intent = ""
        mem.meeting_confirmation_pending = False

    async def load_from_db(self, session: AsyncSession, session_id: str):
        mem = self.get_or_create(session_id)
        meeting_store = MeetingStore(session)
        meeting = await meeting_store.get_by_session(session_id)
        if meeting:
            mem.last_meeting_request_id = meeting.id
            mem.last_meet_link = meeting.meet_link
            if meeting.status == 'pending':
                m = MeetingData(
                    name=meeting.name,
                    company_name=meeting.company_name,
                    company_address=meeting.company_address,
                    email=meeting.email,
                    contact_number=meeting.contact_number,
                    meeting_purpose=meeting.meeting_purpose,
                    meeting_date_time=meeting.meeting_date_time,
                    connection_type=meeting.connection_type,
                )
                mem.pending_meeting = m
                if m.is_complete():
                    mem.pending_intent = "meeting_confirmation"
                    mem.meeting_confirmation_pending = True
                    m.confirmation_pending = True
                else:
                    mem.pending_intent = "meeting"


    async def format_history(self, session: AsyncSession, session_id: str) -> list[dict]:
        store = ChatStore(session)
        messages = await store.get_history(session_id)
        return [
            {"role": m.role, "content": m.content}
            for m in messages
        ]


session_manager = SessionManager()
