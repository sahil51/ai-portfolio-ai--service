import os
import asyncio
import uvicorn
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from db import init_db, close_db, async_session_factory
from rag.retriever import reindex
from api.chat import router as chat_router
from api.reindex import router as reindex_router
from config import settings

# ── Keep-Alive Self-Ping (prevents Render free-tier sleep) ──────────
KEEP_ALIVE_INTERVAL = 4 * 60  # 4 minutes (Render sleeps after 5 min)


async def _keep_alive(url: str):
    """Background task: pings own /health endpoint to stay awake."""
    async with httpx.AsyncClient() as client:
        while True:
            await asyncio.sleep(KEEP_ALIVE_INTERVAL)
            try:
                resp = await client.get(f"{url}/health", timeout=10)
                print(f"[keep-alive] pinged {url}/health → {resp.status_code}")
            except Exception as e:
                print(f"[keep-alive] ping failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with async_session_factory() as session:
        try:
            count = await reindex(session)
            print(f"[startup] Portfolio indexed: {count} documents")
        except Exception as e:
            print(f"[startup] Index error (will retry on first request): {e}")

    # Start keep-alive only on Render (RENDER_EXTERNAL_URL is auto-set)
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    keep_alive_task = None
    if render_url:
        keep_alive_task = asyncio.create_task(_keep_alive(render_url))
        print(f"[keep-alive] started → pinging {render_url} every {KEEP_ALIVE_INTERVAL}s")
    else:
        print("[keep-alive] skipped (not on Render)")

    yield

    # Cleanup
    if keep_alive_task:
        keep_alive_task.cancel()
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


@app.get("/")
@app.head("/")
async def root():
    return {"status": "ok", "service": "daisy-ai-assistant", "version": "1.0.0"}


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
