from rag.retriever import retrieve, keyword_fallback
from agents.llm_client import call_llm
from prompts import get_prompt, get_fallback


async def generate_answer(
    query: str,
    history: list[dict],
    portfolio_name: str = "the portfolio owner",
    language: str = "english",
) -> str:
    retrieved_docs = []
    try:
        retrieved_docs = await retrieve(query, top_k=10)
    except Exception:
        pass

    if not retrieved_docs:
        try:
            retrieved_docs = await keyword_fallback(query, top_k=10)
        except Exception:
            retrieved_docs = []

    context_parts = []
    for doc in retrieved_docs:
        t = doc.get('type', 'info').upper()
        context_parts.append(f"[{t}] {doc.get('title', '')}\n{doc.get('content', '')}")
    context_str = "\n\n---\n\n".join(context_parts) if context_parts else "No specific information found."

    language_label = "Hindi" if language.lower() == "hindi" else "English"
    system_text = get_prompt(
        "answer", "system_prompt",
        portfolio_name=portfolio_name,
        language=language_label,
        context=context_str,
    )
    system_msg = {"role": "system", "content": system_text}

    messages_for_llm = [system_msg]
    recent_history = history[-6:] if history else []
    messages_for_llm.extend(recent_history)
    messages_for_llm.append({"role": "user", "content": query})

    try:
        import asyncio
        answer, _ = await asyncio.wait_for(call_llm(messages_for_llm), timeout=15.0)
        if answer and answer.strip():
            return answer.strip()
    except Exception as e:
        print(f"[generate_answer] LLM call failed or timed out: {e}")

    # Fallback 1: If RAG retrieved portfolio documents, synthesize a direct answer
    # instead of returning a generic robotic 'no information' response
    if retrieved_docs:
        is_hindi = language.lower() == "hindi"
        items = []
        for doc in retrieved_docs[:4]:
            title = doc.get("title", "").strip()
            content = doc.get("content", "").strip()
            if title and content:
                items.append(f"• **{title}**: {content}")
            elif content:
                items.append(f"• {content}")

        if items:
            intro = (
                f"{portfolio_name} ke portfolio se related jankari:\n\n"
                if is_hindi
                else f"Here is the information from {portfolio_name}'s portfolio:\n\n"
            )
            return intro + "\n\n".join(items)

    # Fallback 2: Keyword-based intents
    ql = query.lower()
    if "resume" in ql:
        return get_fallback("resume", language, portfolio_name=portfolio_name)
    if "contact" in ql or "email" in ql or "reach" in ql:
        return get_fallback("contact", language, portfolio_name=portfolio_name)

    return get_fallback("no_info", language, portfolio_name=portfolio_name)
