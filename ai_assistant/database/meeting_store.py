from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from models import MeetingRequest


class MeetingStore:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_request(self, data: dict) -> MeetingRequest:
        record = MeetingRequest(
            session_id=data.get('session_id', ''),
            name=data.get('name', ''),
            company_name=data.get('company_name', ''),
            company_address=data.get('company_address', ''),
            email=data.get('email', ''),
            contact_number=data.get('contact_number', ''),
            meeting_purpose=data.get('meeting_purpose'),
            meeting_date_time=data.get('meeting_date_time', ''),
            connection_type=data.get('connection_type', ''),
            meet_link=data.get('meet_link'),
            status=data.get('status', 'pending'),
            n8n_webhook_status=data.get('n8n_webhook_status'),
        )
        self.session.add(record)
        await self.session.flush()
        await self.session.refresh(record)
        await self.session.commit()
        return record

    async def get_by_session(self, session_id: str) -> MeetingRequest | None:
        stmt = (
            select(MeetingRequest)
            .where(MeetingRequest.session_id == session_id)
            .order_by(MeetingRequest.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_meet_link(self, record_id: int, meet_link: str, status: str = 'confirmed'):
        stmt = (
            update(MeetingRequest)
            .where(MeetingRequest.id == record_id)
            .values(meet_link=meet_link, status=status, n8n_webhook_status='success')
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def mark_failed(self, record_id: int):
        stmt = (
            update(MeetingRequest)
            .where(MeetingRequest.id == record_id)
            .values(n8n_webhook_status='failed')
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def get_latest_by_session(self, session_id: str) -> MeetingRequest | None:
        return await self.get_by_session(session_id)

    async def cancel_active_request(self, session_id: str):
        stmt = (
            update(MeetingRequest)
            .where(MeetingRequest.session_id == session_id)
            .where(MeetingRequest.status == 'pending')
            .values(status='cancelled')
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def save_or_update_pending(self, session_id: str, data) -> MeetingRequest:
        stmt = (
            select(MeetingRequest)
            .where(MeetingRequest.session_id == session_id)
            .where(MeetingRequest.status == 'pending')
            .order_by(MeetingRequest.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()

        if record:
            record.name = data.name
            record.company_name = data.company_name
            record.company_address = data.company_address
            record.email = data.email
            record.contact_number = data.contact_number
            record.meeting_purpose = data.meeting_purpose
            record.meeting_date_time = data.meeting_date_time
            record.connection_type = data.connection_type
        else:
            record = MeetingRequest(
                session_id=session_id,
                name=data.name,
                company_name=data.company_name,
                company_address=data.company_address,
                email=data.email,
                contact_number=data.contact_number,
                meeting_purpose=data.meeting_purpose,
                meeting_date_time=data.meeting_date_time,
                connection_type=data.connection_type,
                status='pending',
            )
            self.session.add(record)

        await self.session.flush()
        if not record.id:
            await self.session.refresh(record)
        await self.session.commit()
        return record


