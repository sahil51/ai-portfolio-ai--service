from prompts import get_prompt
from agents.llm_client import call_llm

MEETING_TOOL = {
    "type": "function",
    "function": {
        "name": "schedule_meeting",
        "description": "Schedule a meeting with the portfolio owner",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "User's full name"},
                "company_name": {"type": "string", "description": "User's company name"},
                "company_address": {"type": "string", "description": "Company address"},
                "email": {"type": "string", "description": "User's email address"},
                "contact_number": {"type": "string", "description": "User's contact number"},
                "meeting_purpose": {"type": "string", "description": "Purpose of the meeting"},
                "meeting_date_time": {"type": "string", "description": "Preferred meeting date and time"},
                "connection_type": {"type": "string", "enum": ["online", "offline"]},
            },
            "required": [],
        },
    },
}

QUERY_TOOL = {
    "type": "function",
    "function": {
        "name": "answer_query",
        "description": "Answer questions about the portfolio owner's background, skills, experience, projects, etc.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The user's question"},
            },
            "required": ["query"],
        },
    },
}


async def classify_intent(messages: list[dict], portfolio_name: str = "the portfolio owner") -> tuple[str, dict | None]:
    system_text = get_prompt("router", "system_prompt", portfolio_name=portfolio_name)
    system_msg = {"role": "system", "content": system_text}
    full_messages = [system_msg] + messages[-6:]

    try:
        content, tool_call = await call_llm(full_messages, tools=[MEETING_TOOL, QUERY_TOOL])

        if tool_call:
            intent_name = tool_call.get("name", "")
            intent_args = tool_call.get("arguments", {})
            if intent_name == "schedule_meeting":
                return "meeting", intent_args
            return "general_query", intent_args

        return "general_query", {"query": messages[-1]["content"] if messages else ""}

    except Exception:
        last_msg = messages[-1]["content"] if messages else ""
        meeting_keywords = [
            "schedule", "meeting", "book a call", "book call",
            "book a meeting", "interview", "appointment",
            "discuss project", "want to talk", "let's talk",
            "discuss a project", "want to meet", "set up a call",
            "schedule a call", "arrange a meeting",
        ]
        msg_lower = last_msg.lower()
        for kw in meeting_keywords:
            if kw in msg_lower:
                return "meeting", {}
        return "general_query", {"query": last_msg}
