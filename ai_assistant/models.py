import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, JSON, Index
from sqlalchemy.orm import relationship
from db import Base


def utcnow():
    return datetime.now(timezone.utc)


# ── Read-only models mirroring Django portfolio tables ──────────────────────

class HeroInfo(Base):
    __tablename__ = 'portfolio_heroinfo'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(150), default='Sahil Thakur')
    location = Column(String(200))
    current_company = Column(String(200))
    short_intro = Column(Text)
    email = Column(String(254))
    linkedin_url = Column(String(200))
    github_url = Column(String(200))
    portfolio_url = Column(String(200))
    role = Column(String(150))
    tech_stack = Column(String(255))
    ai_expertise = Column(String(255))
    about_me = Column(Text)
    phone = Column(String(50))
    contact_description = Column(Text)
    open_to_work = Column(Boolean, default=True)
    experience_years = Column(Integer, default=2)
    ai_agents_built = Column(Integer, default=5)
    projects_completed = Column(Integer, default=10)
    resume = Column(String(500), nullable=True)

    def get_tech_stack_list(self):
        return [t.strip() for t in (self.tech_stack or '').split(',') if t.strip()]

    def get_ai_expertise_list(self):
        return [t.strip() for t in (self.ai_expertise or '').split(',') if t.strip()]


class SkillCategory(Base):
    __tablename__ = 'portfolio_skillcategory'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100))
    icon_class = Column(String(100), default='fa-solid fa-code')

    skills = relationship('Skill', back_populates='category', lazy='selectin')


class Skill(Base):
    __tablename__ = 'portfolio_skill'

    id = Column(Integer, primary_key=True, autoincrement=True)
    category_id = Column(Integer, ForeignKey('portfolio_skillcategory.id'))
    name = Column(String(100))

    category = relationship('SkillCategory', back_populates='skills', lazy='selectin')


class Experience(Base):
    __tablename__ = 'portfolio_experience'

    id = Column(Integer, primary_key=True, autoincrement=True)
    company = Column(String(150))
    location = Column(String(150))
    role = Column(String(150))
    start_date = Column(String(50))
    end_date = Column(String(50), default='Present')
    is_present = Column(Boolean, default=False)
    intro = Column(Text)
    key_contributions = Column(Text)
    company_projects = Column(Text, default='')
    technologies = Column(String(255))

    def get_key_contributions_list(self):
        return [line.strip() for line in (self.key_contributions or '').split('\n') if line.strip()]

    def get_company_projects_list(self):
        return [line.strip() for line in (self.company_projects or '').split('\n') if line.strip()]

    def get_technologies_list(self):
        return [t.strip() for t in (self.technologies or '').split(',') if t.strip()]


class Project(Base):
    __tablename__ = 'portfolio_project'

    id = Column(Integer, primary_key=True, autoincrement=True)
    number = Column(Integer)
    title = Column(String(150))
    description = Column(Text)
    icon_class = Column(String(100), default='fa-solid fa-rocket')
    technologies = Column(String(255))
    link = Column(String(500), nullable=True)
    blog_post_id = Column(Integer, ForeignKey('portfolio_blogpost.id'), nullable=True)

    blog_post = relationship('BlogPost', lazy='selectin')

    def get_technologies_list(self):
        return [t.strip() for t in (self.technologies or '').split(',') if t.strip()]


class AutomationWorkflow(Base):
    __tablename__ = 'portfolio_automationworkflow'

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200))
    category = Column(String(100))
    description = Column(Text)
    technologies = Column(String(255))
    icon_class = Column(String(100), default='fa-solid fa-gears')
    link = Column(String(500), nullable=True)
    order = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)

    images = relationship('WorkflowImage', back_populates='workflow', lazy='selectin')

    def get_technologies_list(self):
        return [t.strip() for t in (self.technologies or '').split(',') if t.strip()]


class WorkflowImage(Base):
    __tablename__ = 'portfolio_workflowimage'

    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_id = Column(Integer, ForeignKey('portfolio_automationworkflow.id'), nullable=False)
    image = Column(String(500), nullable=True)
    image_url = Column(String(500), nullable=True)
    caption = Column(String(255), nullable=True)
    order = Column(Integer, default=0)

    workflow = relationship('AutomationWorkflow', back_populates='images')


class Education(Base):
    __tablename__ = 'portfolio_education'

    id = Column(Integer, primary_key=True, autoincrement=True)
    institution = Column(String(150))
    degree = Column(String(150))
    duration = Column(String(100))
    location = Column(String(150))
    scores = Column(Text)

    def get_scores_list(self):
        return [line.strip() for line in (self.scores or '').split('\n') if line.strip()]


class BlogPost(Base):
    __tablename__ = 'portfolio_blogpost'

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200))
    slug = Column(String(200))
    summary = Column(Text)
    content = Column(Text)
    image = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    status = Column(String(10), default='Published')


class ContactMethod(Base):
    __tablename__ = 'portfolio_contactmethod'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100))
    value = Column(String(255))
    link = Column(String(255))
    icon_class = Column(String(100))
    order = Column(Integer, default=0)
    is_full_width = Column(Boolean, default=False)


# ── Microservice-specific tables ────────────────────────────────────────────

class ChatMessage(Base):
    __tablename__ = 'chat_messages'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(100), nullable=False, index=True)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    metadata_ = Column('metadata', JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)

    __table_args__ = (
        Index('idx_chat_messages_session_ts', 'session_id', 'created_at'),
    )


class MeetingRequest(Base):
    __tablename__ = 'meeting_requests'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(100), nullable=False, index=True)
    name = Column(String(200))
    company_name = Column(String(200))
    company_address = Column(Text)
    email = Column(String(200))
    contact_number = Column(String(50))
    meeting_purpose = Column(Text, nullable=True)
    meeting_date_time = Column(String(100))
    connection_type = Column(String(20))
    meet_link = Column(Text, nullable=True)
    status = Column(String(20), default='pending')
    n8n_webhook_status = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
