"""Add meeting_purpose column to PostgreSQL meeting_requests table."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from config import settings
from sqlalchemy import create_engine, text

engine = create_engine(settings.DATABASE_URL_SYNC)
with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TABLE meeting_requests ADD COLUMN meeting_purpose TEXT NULL"))
        conn.commit()
        print("Migration: added meeting_purpose column")
    except Exception as e:
        if "already exists" in str(e).lower():
            print("Migration: meeting_purpose column already exists")
        else:
            print(f"Migration error: {e}")
