import re

MEETING_KEYWORDS = [
    "schedule", "meeting", "interview", "book a call", "book call",
    "book a meeting", "appointment", "discuss project", "want to talk",
    "let's talk", "want to meet", "set up a call", "arrange a meeting",
    "book an interview", "schedule interview", "take interview", "interview schedule",
    "hire", "hire you", "hire sahil", "call"
]


async def classify_intent(messages: list[dict], portfolio_name: str = "the portfolio owner") -> tuple[str, dict | None]:
    """
    Lightning-fast, zero-overhead intent classifier.
    Eliminates slow AFC function calling LLM loops to achieve instant (<1ms) routing.
    """
    last_msg = messages[-1]["content"] if messages else ""
    msg_lower = last_msg.lower().strip()

    # Check for meeting keywords
    for kw in MEETING_KEYWORDS:
        if kw in msg_lower:
            return "meeting", {}

    return "general_query", {"query": last_msg}
