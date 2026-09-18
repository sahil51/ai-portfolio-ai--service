import os
from pathlib import Path
from urllib.parse import quote_plus
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env', override=True)


class Settings:
    # Database
    DB_NAME: str = os.getenv('DB_NAME', 'postgres')
    DB_USER: str = os.getenv('DB_USER', 'postgres')
    DB_PASSWORD: str = os.getenv('DB_PASSWORD', 'postgres')
    DB_HOST: str = os.getenv('DB_HOST', '127.0.0.1')
    DB_PORT: str = os.getenv('DB_PORT', '5432')

    @property
    def DATABASE_URL(self) -> str:
        return f'postgresql+asyncpg://{self.DB_USER}:{quote_plus(self.DB_PASSWORD)}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}'

    @property
    def DATABASE_URL_SYNC(self) -> str:
        return f'postgresql://{self.DB_USER}:{quote_plus(self.DB_PASSWORD)}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?sslmode=require'

    # LLM Primary (Cerebras)
    CEREBRAS_API_KEY: str = os.getenv('CEREBRAS_API_KEY', '')
    CEREBRAS_MODEL: str = os.getenv('CEREBRAS_MODEL', 'gpt-oss-120b')
    CEREBRAS_CHAT_URL: str = os.getenv('CEREBRAS_CHAT_URL', 'https://api.cerebras.ai/v1/chat/completions')

    # LLM Fallback (Gemini)
    GEMINI_API_KEY: str = os.getenv('GEMINI_API_KEY', '')
    GEMINI_MODEL: str = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')

    # LLM Tertiary (NVIDIA)
    NVIDIA_API_KEY: str = os.getenv('NVIDIA_API_KEY', '')
    NVIDIA_MODEL: str = os.getenv('NVIDIA_MODEL', 'mistralai/mistral-nemotron')
    NVIDIA_CHAT_URL: str = os.getenv('NVIDIA_CHAT_URL', 'https://integrate.api.nvidia.com/v1/chat/completions')
    NVIDIA_BACKUP_MODELS: str = os.getenv('NVIDIA_BACKUP_MODELS', '')

    # Embeddings (Gemini)
    EMBEDDING_MODEL: str = os.getenv('EMBEDDING_MODEL', 'gemini-embedding-001')

    # n8n
    N8N_MEETING_WEBHOOK_URL: str = os.getenv('N8N_MEETING_WEBHOOK_URL', '')

    # LangSmith
    LANGSMITH_TRACING: bool = os.getenv('LANGSMITH_TRACING', 'false').lower() in ('true', '1')
    LANGSMITH_ENDPOINT: str = os.getenv('LANGSMITH_ENDPOINT', '')
    LANGSMITH_API_KEY: str = os.getenv('LANGSMITH_API_KEY', '')
    LANGSMITH_PROJECT: str = os.getenv('LANGSMITH_PROJECT', '')

    # Assistant config
    MAX_HISTORY_MESSAGES: int = 100
    CHAT_API_PORT: int = int(os.getenv('CHAT_API_PORT', '8001'))

    # Security Config (Loaded dynamically from .env)
    INTERNAL_API_KEY: str = os.getenv('INTERNAL_API_KEY', '')
    MAX_MESSAGE_LENGTH: int = int(os.getenv('MAX_MESSAGE_LENGTH', '350'))
    MAX_SESSION_MESSAGES: int = int(os.getenv('MAX_SESSION_MESSAGES', '20'))
    MAX_IP_REQUESTS_PER_MIN: int = int(os.getenv('MAX_IP_REQUESTS_PER_MIN', '10'))

    # SMTP Email Config
    EMAIL_HOST: str = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
    EMAIL_PORT: int = int(os.getenv('EMAIL_PORT', '587'))
    EMAIL_USE_TLS: bool = os.getenv('EMAIL_USE_TLS', 'true').lower() in ('true', '1')
    EMAIL_HOST_USER: str = os.getenv('EMAIL_HOST_USER', '')
    EMAIL_HOST_PASSWORD: str = os.getenv('EMAIL_HOST_PASSWORD', '')
    DEFAULT_FROM_EMAIL: str = os.getenv('DEFAULT_FROM_EMAIL', '')
    NOTIFICATION_EMAIL: str = os.getenv('NOTIFICATION_EMAIL', '')


settings = Settings()
