import asyncio
from google import genai
from config import settings


class EmbeddingClient:
    def __init__(self):
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self.model_name = f'models/{settings.EMBEDDING_MODEL}'
        self._lock = asyncio.Lock()

    async def embed_text(self, text: str) -> list[float]:
        loop = asyncio.get_event_loop()
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with self._lock:
                    result = await loop.run_in_executor(
                        None,
                        lambda: self.client.models.embed_content(
                            model=self.model_name,
                            contents=text,
                        )
                    )
                return result.embeddings[0].values
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                await asyncio.sleep(1.0 * (attempt + 1))

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
