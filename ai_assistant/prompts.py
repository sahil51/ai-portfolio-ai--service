import tomllib
from pathlib import Path


PROMPTS_PATH = Path(__file__).resolve().parent / "prompts.toml"

def load_prompts() -> dict:
    with open(PROMPTS_PATH, "rb") as f:
        return tomllib.load(f)


def clear_cache():
    global _cache
    _cache = None


def get_prompt(*keys: str, **fmt_kwargs) -> str:
    data = load_prompts()
    for key in keys:
        data = data[key]
    if isinstance(data, dict) and "template" in data:
        data = data["template"]
    if isinstance(data, str) and fmt_kwargs:
        data = data.format(**fmt_kwargs)
    return data.strip()


def get_suggestions(language: str, **fmt_kwargs) -> list[str]:
    prompts = load_prompts()
    items = prompts["answer"]["suggestions"].get(language, prompts["answer"]["suggestions"]["english"])
    return [s.format(**fmt_kwargs) for s in items]


def get_meeting_fields(language: str) -> list[tuple[str, str]]:
    prompts = load_prompts()
    fields_dict = prompts["meeting"]["fields"].get(language, prompts["meeting"]["fields"]["english"])
    return [(k, v) for k, v in fields_dict.items()]


def get_meeting_labels(language: str) -> dict[str, str]:
    prompts = load_prompts()
    return prompts["meeting"]["labels"].get(language, prompts["meeting"]["labels"]["english"])


def get_meeting_collected_prefix(language: str) -> str:
    prompts = load_prompts()
    return prompts["meeting"]["collected_prefix"].get(language, prompts["meeting"]["collected_prefix"]["english"])["text"]


def get_meeting_confirmation(connection_type: str, has_link: bool, language: str, **fmt_kwargs) -> str:
    prompts = load_prompts()
    if connection_type == "online":
        key = "online_with_link" if has_link else "online_no_link"
    else:
        key = "offline"
    template = prompts["meeting"]["confirmation"][key].get(language, prompts["meeting"]["confirmation"][key]["english"])["template"]
    return template.format(**fmt_kwargs).strip()


def get_greeting(language: str, **fmt_kwargs) -> str:
    prompts = load_prompts()
    template = prompts["greeting"].get(language, prompts["greeting"]["english"])["template"]
    return template.format(**fmt_kwargs).strip()


def get_fallback(key: str, language: str, **fmt_kwargs) -> str:
    prompts = load_prompts()
    template = prompts["fallback"].get(language, prompts["fallback"]["english"])[key]
    return template.format(**fmt_kwargs).strip()


def get_meeting_confirmation_summary(language: str, **fmt_kwargs) -> str:
    prompts = load_prompts()
    section = prompts["meeting"]["confirmation_summary"]
    template = section.get(language, section["english"])["template"]
    return template.format(**fmt_kwargs).strip()


def get_meeting_validation_error(field: str, language: str) -> str:
    prompts = load_prompts()
    section = prompts["meeting"]["validation"]
    errors = section.get(language, section["english"])
    key_map = {
        "email": "invalid_email",
        "contact_number": "invalid_phone",
        "connection_type": "invalid_connection_type",
    }
    return errors.get(key_map.get(field, ""), "")


def get_meeting_cancel_message(language: str) -> str:
    prompts = load_prompts()
    section = prompts["meeting"]["cancel"]
    return section.get(language, section["english"])["template"].strip()


def get_meeting_edit_prompt(language: str) -> str:
    prompts = load_prompts()
    section = prompts["meeting"]["edit_prompt"]
    return section.get(language, section["english"])["template"].strip()


def get_meeting_start_message(first_question: str, language: str, **fmt_kwargs) -> str:
    prompts = load_prompts()
    section = prompts["meeting"]["start"]
    template = section.get(language, section["english"])["template"]
    return template.format(first_question=first_question, **fmt_kwargs).strip()


