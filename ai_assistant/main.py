import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from db import init_db, close_db, async_session_factory
from rag.retriever import reindex
from api.chat import router as chat_router
from api.reindex import router as reindex_router
from config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with async_session_factory() as session:
        try:
            count = await reindex(session)
            print(f"[startup] Portfolio indexed: {count} documents")
        except Exception as e:
            print(f"[startup] Index error (will retry on first request): {e}")
    yield
    await close_db()


app = FastAPI(
    title="Daisy AI Assistant API",
    description="AI assistant microservice for Sahil Thakur's portfolio",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://automation.crescaler.com",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8001",
        "http://127.0.0.1:8001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix="/api")
app.include_router(reindex_router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "daisy-ai-assistant"}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.CHAT_API_PORT,
        reload=True,
    )
