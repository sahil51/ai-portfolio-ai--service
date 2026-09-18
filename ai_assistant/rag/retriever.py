import math
from rag.embeddings import embedding_client, embedding_store
from rag.contexts import load_all_documents
from sqlalchemy.ext.asyncio import AsyncSession


CATEGORY_KEYWORDS = {
    "project": ["project", "projects", "built", "build", "developed", "created", "made", "application", "app", "platform"],
    "skill": ["skill", "skills", "technology", "technologies", "tech", "stack", "know", "expertise", "proficient"],
    "experience": ["experience", "work", "job", "company", "companies", "worked", "employment", "career", "role", "position"],
    "education": ["education", "study", "studied", "degree", "university", "college", "school", "learn", "academic"],
    "blog": ["blog", "article", "post", "write", "writing", "published"],
    "contact": ["contact", "email", "phone", "reach", "connect", "hire", "call"],
    "profile": ["about", "who", "introduce", "introduction", "background", "summary", "bio", "profile"],
}


async def reindex(session: AsyncSession):
    embedding_store.clear()

    docs = await load_all_documents(session)

    for doc in docs:
        text_for_embedding = f"{doc['title']}\n{doc['content']}\n{doc['keywords']}"
        emb = await embedding_client.embed_text(text_for_embedding)
        embedding_store.add(doc, emb)

    embedding_store.set_ready()
    return len(docs)


async def retrieve(query: str, top_k: int = 8) -> list[dict]:
    if not embedding_store.is_ready():
        return []

    query_emb = await embedding_client.embed_query(query)

    scored = []
    for i, doc_emb in enumerate(embedding_store.embeddings):
        score = cosine_similarity(query_emb, doc_emb)
        scored.append((score, embedding_store.documents[i]))

    scored.sort(key=lambda x: x[0], reverse=True)

    seen_ids = set()
    results = []

    # Include by semantic similarity
    for score, doc in scored:
        if len(results) >= top_k:
            break
        doc_id = doc.get('id', '')
        if doc_id not in seen_ids:
            seen_ids.add(doc_id)
            doc_copy = dict(doc)
            doc_copy['score'] = round(score, 4)
            results.append(doc_copy)

    # Include by category match (add all docs of matching type)
    q_lower = query.lower()
    matching_types = set()
    for ctype, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in q_lower:
                matching_types.add(ctype)

    if matching_types:
        for doc in embedding_store.documents:
            if doc.get('type') in matching_types and doc.get('id', '') not in seen_ids:
                seen_ids.add(doc.get('id', ''))
                doc_copy = dict(doc)
                doc_copy['score'] = 1.0
                results.append(doc_copy)

    return results[:top_k * 2]


async def keyword_fallback(query: str, top_k: 8) -> list[dict]:
    if not embedding_store.is_ready():
        return []

    query_lower = query.lower()
    query_tokens = set(query_lower.split())

    scored = []
    for doc in embedding_store.documents:
        kw_text = f"{doc['title']} {doc['content']} {doc['keywords']}".lower()
        kw_tokens = set(kw_text.split())
        overlap = len(query_tokens & kw_tokens)
        if overlap > 0:
            score = overlap / max(len(query_tokens), 1)
            scored.append((score, doc))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [dict(doc) for _, doc in scored[:top_k]]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)
