import time
import asyncio
from google import genai
from google.genai import types
from config import settings


def _is_quota_error(e: Exception) -> bool:
    """Detect if an exception is due to rate limits or quota exhaustion (HTTP 429)."""
    err_str = str(e).lower()
    quota_indicators = [
        "429", "resource_exhausted", "quota", "rate limit",
        "too many requests", "exceeded", "limit"
    ]
    if any(ind in err_str for ind in quota_indicators):
        return True
    if getattr(e, "code", None) == 429 or getattr(e, "status_code", None) == 429:
        return True
    return False


def _is_transient_error(e: Exception) -> bool:
    """Detect if an exception is a transient Google server error (503 / 500 / overloaded)."""
    err_str = str(e).lower()
    indicators = ["503", "unavailable", "high demand", "overloaded", "spikes in demand", "internal error"]
    return any(ind in err_str for ind in indicators)


def _get_candidate_models() -> list[str]:
    """Returns candidate Gemini models starting with fast models and verified fallbacks."""
    primary = settings.GEMINI_MODEL.strip()
    # Prioritize gemini-3.6-flash and gemini-3.5-flash-lite for speed and stability
    fallbacks = ["gemini-3.6-flash", "gemini-3.5-flash-lite"]
    candidates = []
    if primary and primary not in fallbacks:
        candidates.append(primary)
    for fb in fallbacks:
        if fb not in candidates:
            candidates.append(fb)
    return candidates


class GeminiKeyManager:
    """
    Manages multiple Gemini API keys with smart failover and zero-latency sequence restoration.
    - If a key hits quota (429), it cools down for 60 seconds (matching Gemini 1-minute quota window).
    - While in cooldown, requests skip the exhausted key to prevent 429 latency overhead.
    - As soon as cooldown expires ('refresh'), the key immediately regains its top priority in sequence.
    """
    def __init__(self):
        self._clients: dict[str, genai.Client] = {}
        self._cooldown_until: dict[str, float] = {}

    def get_keys(self) -> list[str]:
        keys = settings.GEMINI_KEYS_LIST
        if not keys and settings.GEMINI_API_KEY:
            keys = [settings.GEMINI_API_KEY.strip()]
        return keys

    def get_client(self, api_key: str) -> genai.Client:
        if api_key not in self._clients:
            self._clients[api_key] = genai.Client(api_key=api_key)
        return self._clients[api_key]

    def mark_exhausted(self, api_key: str, cooldown_seconds: float = 60.0):
        self._cooldown_until[api_key] = time.time() + cooldown_seconds
        masked = api_key[:6] + "..." + api_key[-4:] if len(api_key) > 10 else "key"
        print(f"[GeminiKeyManager] Key {masked} quota exceeded. Cooling down for {cooldown_seconds}s.")

    def get_ordered_keys(self) -> list[str]:
        keys = self.get_keys()
        if not keys:
            return []

        now = time.time()
        # Ready keys (not in cooldown) retain their exact configured priority order (Key 1 -> Key 2 -> ...)
        ready_keys = [k for k in keys if self._cooldown_until.get(k, 0.0) <= now]
        # Cooling keys are temporarily relegated to the end of the line
        cooling_keys = [k for k in keys if self._cooldown_until.get(k, 0.0) > now]
        cooling_keys.sort(key=lambda k: self._cooldown_until.get(k, 0.0))

        return ready_keys + cooling_keys


key_manager = GeminiKeyManager()


async def call_llm(messages: list[dict], tools: list | None = None) -> tuple[str, dict | None]:
    """
    Calls Gemini LLM with automatic key rotation and zero-latency failover.
    Returns (text_response, tool_call_dict).
    """
    ordered_keys = key_manager.get_ordered_keys()
    if not ordered_keys:
        raise RuntimeError("No Gemini API keys configured. Please set GEMINI_API_KEY or GEMINI_API_KEYS in .env.")

    candidate_models = _get_candidate_models()

    formatted = []
    for m in messages:
        role = "user" if m.get("role") in ("user", "system") else "model"
        content_text = m.get("content", "")
        formatted.append(types.Content(role=role, parts=[types.Part.from_text(text=content_text)]))

    config_args: dict = {
        "temperature": 0.3,
        "max_output_tokens": 1024,
    }

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
                        "description": p_info.get("description", "")
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
                    description=func_info.get("description", ""),
                    parameters=parameters
                )
                gemini_tools.append(types.Tool(function_declarations=[decl]))

        if gemini_tools:
            config_args["tools"] = gemini_tools
            config_args["tool_config"] = types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="ANY")
            )

    config = types.GenerateContentConfig(**config_args)

    last_error = None
    for model_candidate in candidate_models:
        model_name = model_candidate if model_candidate.startswith("models/") else f"models/{model_candidate}"
        for api_key in ordered_keys:
            client = key_manager.get_client(api_key)
            try:
                resp = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model_name,
                    contents=formatted,
                    config=config,
                )

                if resp.function_calls:
                    call = resp.function_calls[0]
                    args = dict(call.args) if call.args else {}
                    return "", {"name": call.name, "arguments": args}

                return resp.text or "", None

            except Exception as e:
                last_error = e
                if _is_quota_error(e):
                    key_manager.mark_exhausted(api_key, cooldown_seconds=60.0)
                    # Next loop iteration automatically tries the next available key
                    continue
                elif _is_transient_error(e):
                    # Transient error on this model (e.g. 503 high demand), try next model/key
                    masked = api_key[:6] + "..." + api_key[-4:] if len(api_key) > 10 else "key"
                    print(f"[Gemini LLM] Model {model_candidate} unavailable (503/spikes) with key {masked}, failing over: {e}")
                    break
                else:
                    masked = api_key[:6] + "..." + api_key[-4:] if len(api_key) > 10 else "key"
                    print(f"[Gemini LLM] Error with model {model_candidate} and key {masked}: {e}")
                    continue

    raise RuntimeError(f"All Gemini API keys and candidate models failed. Last error: {last_error}")

