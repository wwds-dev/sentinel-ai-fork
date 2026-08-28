import os
from openai import OpenAI

from services.api_limits import REQUEST_TIMEOUT_SECONDS, MAX_RETRIES


def _usage_value(container, *names):
    """Read an SDK usage field from either an object or a plain mapping."""
    if container is None:
        return None
    for name in names:
        value = container.get(name) if isinstance(container, dict) else getattr(container, name, None)
        if value is not None:
            return value
    return None


def cached_input_tokens(usage) -> int:
    """Return Kimi cache-hit tokens across current and compatible SDK shapes.

    Kimi's API documents ``usage.cached_tokens``.  Some OpenAI-compatible
    clients instead place the same value below ``prompt_tokens_details`` (or
    call it ``cached_input_tokens``), so accept those shapes without ever
    allowing a malformed value to inflate the cache discount.
    """
    candidates = [
        _usage_value(usage, "cached_tokens", "cached_input_tokens"),
    ]
    details = _usage_value(usage, "prompt_tokens_details", "input_tokens_details")
    candidates.append(
        _usage_value(details, "cached_tokens", "cached_input_tokens", "cache_read_input_tokens")
    )

    # Pydantic/OpenAI SDK models retain provider-specific fields in a dumped
    # mapping even when no generated attribute exists for them.
    if not isinstance(usage, dict) and hasattr(usage, "model_dump"):
        try:
            dumped = usage.model_dump()
        except Exception:
            dumped = None
        if dumped:
            candidates.append(_usage_value(dumped, "cached_tokens", "cached_input_tokens"))

    for value in candidates:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            continue
    return 0


class KimiClientWrapper:
    """Wrapper for Moonshot AI's Kimi models via the OpenAI-compatible Kimi API.

    Docs: https://platform.kimi.ai/docs/api/overview
    """

    KNOWN_MODELS = [
        "kimi-k3",
        "kimi-k2.7-code",
        "kimi-k2.7-code-highspeed",
        "kimi-k2.6",
    ]

    def __init__(self):
        self.api_key = os.getenv("KIMI_API_KEY")
        self.client = (
            OpenAI(
                api_key=self.api_key,
                base_url="https://api.moonshot.ai/v1",
                timeout=REQUEST_TIMEOUT_SECONDS,
                max_retries=MAX_RETRIES,
            )
            if self.api_key
            else None
        )

    @staticmethod
    def key_available():
        return bool(os.getenv("KIMI_API_KEY"))

    def list_models(self) -> list[str]:
        if not self.client:
            return self.KNOWN_MODELS
        try:
            result = self.client.models.list()
            models = sorted(m.id for m in result.data)
            return models if models else self.KNOWN_MODELS
        except Exception:
            return self.KNOWN_MODELS

    def chat(self, messages, model="kimi-k2.7-code"):
        if not self.client:
            raise RuntimeError("KIMI_API_KEY is not set.")

        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
        )

        text = response.choices[0].message.content or ""

        response_usage = response.usage
        input_tokens = int(_usage_value(response_usage, "prompt_tokens", "input_tokens") or 0)
        usage = {
            "input_tokens": input_tokens,
            "cached_input_tokens": min(input_tokens, cached_input_tokens(response_usage)),
            "output_tokens": int(
                _usage_value(response_usage, "completion_tokens", "output_tokens") or 0
            ),
            "total_tokens": int(_usage_value(response_usage, "total_tokens") or 0),
        }

        return text, usage

    def generate(self, prompt, model="kimi-k2.7-code"):
        messages = [{"role": "user", "content": prompt}]
        return self.chat(messages=messages, model=model)

    def stream_chat(self, messages, model="kimi-k2.7-code"):
        if not self.client:
            raise RuntimeError("KIMI_API_KEY is not set.")

        try:
            stream = self.client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
            )

            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta

        except Exception as e:
            raise RuntimeError(f"Kimi streaming request failed: {e}")
