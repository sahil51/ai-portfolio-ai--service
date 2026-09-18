import json
import httpx
from config import settings


LLM_FALLBACKS = []


def _build_cerebras_payload(messages: list[dict], tools: list | None = None) -> dict:
    payload = {
        "model": settings.CEREBRAS_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 1024,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    return payload


def _build_nvidia_payload(messages: list[dict], tools: list | None = None) -> dict:
    payload = {
        "model": settings.NVIDIA_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 1024,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    return payload


async def call_llm(messages: list[dict], tools: list | None = None) -> tuple[str, dict | None]:
    errors = []

    # Try Cerebras
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = _build_cerebras_payload(messages, tools)
            resp = await client.post(
                settings.CEREBRAS_CHAT_URL,
                headers={
                    "Authorization": f"Bearer {settings.CEREBRAS_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if resp.status_code == 200:
                data = resp.json()
                choice = data['choices'][0]
                if 'tool_calls' in choice.get('message', {}):
                    tc = choice['message']['tool_calls'][0]
                    return "", {"name": tc['function']['name'], "arguments": json.loads(tc['function']['arguments'])}
                return choice['message']['content'], None
            errors.append(f"cerebras_{resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        errors.append(f"cerebras_err: {str(e)[:200]}")

    # Try Gemini
    try:
        from google import genai
        from google.genai import types
        gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
        model_name = f'models/{settings.GEMINI_MODEL}'
        formatted = []
        for m in messages:
            role = "user" if m["role"] in ("user", "system") else "model"
            formatted.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))
        
        config_args = {"temperature": 0.3}
        if tools:
            gemini_tools = []
            for t in tools:
                if t.get("type") == "function":
                    func_info = t.get("function", {})
                    properties = {}
                    for p_name, p_info in func_info.get("parameters", {}).get("properties", {}).items():
                        p_type = p_info.get("type", "string").upper()
                        enum_vals = p_info.get("enum")
                        schema_args = {
                            "type": getattr(types.Type, p_type, types.Type.STRING),
                            "description": p_info.get("description")
                        }
                        if enum_vals:
                            schema_args["enum"] = enum_vals
                        properties[p_name] = types.Schema(**schema_args)
                    
                    parameters = types.Schema(
                        type=types.Type.OBJECT,
                        properties=properties,
                        required=func_info.get("parameters", {}).get("required", [])
                    )
                    
                    decl = types.FunctionDeclaration(
                        name=func_info.get("name"),
                        description=func_info.get("description"),
                        parameters=parameters
                    )
                    gemini_tools.append(types.Tool(function_declarations=[decl]))
            if gemini_tools:
                config_args["tools"] = gemini_tools

        config = types.GenerateContentConfig(**config_args)
        resp = gemini_client.models.generate_content(
            model=model_name,
            contents=formatted,
            config=config,
        )
        if resp.function_calls:
            call = resp.function_calls[0]
            # Convert args to a standard python dict
            args = dict(call.args) if call.args else {}
            return "", {"name": call.name, "arguments": args}
        return resp.text or "", None
    except Exception as e:
        errors.append(f"gemini_err: {str(e)[:200]}")

    # Try NVIDIA
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = _build_nvidia_payload(messages, tools)
            resp = await client.post(
                settings.NVIDIA_CHAT_URL,
                headers={
                    "Authorization": f"Bearer {settings.NVIDIA_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if resp.status_code == 200:
                data = resp.json()
                choice = data['choices'][0]
                return choice['message']['content'], None
            errors.append(f"nvidia_{resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        errors.append(f"nvidia_err: {str(e)[:200]}")

    raise RuntimeError(f"All LLMs failed: {' | '.join(errors)}")
