from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from models import ChatMessage, utcnow
from config import settings


class ChatStore:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_message(self, session_id: str, role: str, content: str, metadata: dict | None = None) -> ChatMessage:
        msg = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            metadata_=metadata,
        )
        self.session.add(msg)
        await self.session.flush()
        await self._prune(session_id)
        await self.session.commit()
        return msg

    async def get_history(self, session_id: str, limit: int | None = None) -> list[ChatMessage]:
        if limit is None:
            limit = settings.MAX_HISTORY_MESSAGES
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_messages(self, session_id: str) -> int:
        stmt = select(func.count()).select_from(ChatMessage).where(ChatMessage.session_id == session_id)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def _prune(self, session_id: str):
        count = await self.count_messages(session_id)
        if count > settings.MAX_HISTORY_MESSAGES:
            excess = count - settings.MAX_HISTORY_MESSAGES
            subq = (
                select(ChatMessage.id)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at.asc())
                .limit(excess)
            ).subquery()
            stmt = delete(ChatMessage).where(ChatMessage.id.in_(select(subq.c.id)))
            await self.session.execute(stmt)

    async def clear_session(self, session_id: str):
        stmt = delete(ChatMessage).where(ChatMessage.session_id == session_id)
        await self.session.execute(stmt)
        await self.session.commit()
