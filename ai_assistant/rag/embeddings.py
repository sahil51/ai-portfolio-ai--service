import asyncio
from google import genai
from config import settings


class EmbeddingClient:
    def __init__(self):
        self.model_name = f'models/{settings.EMBEDDING_MODEL}'
        self._lock = asyncio.Lock()

    async def embed_text(self, text: str) -> list[float]:
        from agents.llm_client import key_manager, _is_quota_error
        ordered_keys = key_manager.get_ordered_keys()
        if not ordered_keys:
            ordered_keys = [settings.GEMINI_API_KEY] if settings.GEMINI_API_KEY else []

        last_error = None
        for api_key in ordered_keys:
            client = key_manager.get_client(api_key)
            try:
                async with self._lock:
                    result = await asyncio.to_thread(
                        client.models.embed_content,
                        model=self.model_name,
                        contents=text,
                    )
                return result.embeddings[0].values
            except Exception as e:
                last_error = e
                if _is_quota_error(e):
                    key_manager.mark_exhausted(api_key, cooldown_seconds=60.0)
                    continue
                else:
                    continue

        raise last_error or RuntimeError("Embedding generation failed across all keys.")

    async def embed_query(self, query: str) -> list[float]:
        return await self.embed_text(query)


class EmbeddingStore:
    def __init__(self):
        self.documents: list[dict] = []
        self.embeddings: list[list[float]] = []
        self._ready = False

    def is_ready(self) -> bool:
        return self._ready and len(self.documents) > 0

    def set_ready(self, val: bool = True):
        self._ready = val

    def clear(self):
        self.documents.clear()
        self.embeddings.clear()
        self._ready = False

    def add(self, doc: dict, embedding: list[float]):
        self.documents.append(doc)
        self.embeddings.append(embedding)

    def __len__(self) -> int:
        return len(self.documents)


embedding_client = EmbeddingClient()
embedding_store = EmbeddingStore()
