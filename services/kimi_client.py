import os
from openai import OpenAI

from services.api_limits import REQUEST_TIMEOUT_SECONDS, MAX_RETRIES


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

        usage = {
            "input_tokens": response.usage.prompt_tokens if response.usage else 0,
            "output_tokens": response.usage.completion_tokens if response.usage else 0,
            "total_tokens": response.usage.total_tokens if response.usage else 0,
            "cached_input_tokens": self._cached_tokens(response.usage),
        }

        return text, usage

    def generate(self, prompt, model="kimi-k2.7-code"):
        messages = [{"role": "user", "content": prompt}]
        return self.chat(messages=messages, model=model)

    def stream_chat(self, messages, model="kimi-k2.7-code"):
        if not self.client:
            raise RuntimeError("KIMI_API_KEY is not set.")

        return _KimiUsageStream(self.client, model, messages)

    @staticmethod
    def _cached_tokens(usage) -> int:
        details = getattr(usage, "prompt_tokens_details", None) if usage else None
        return int(getattr(details, "cached_tokens", 0) or 0)


class _KimiUsageStream:
    """Iterable text stream that retains the API's final usage chunk."""

    def __init__(self, client, model: str, messages: list):
        self.client = client
        self.model = model
        self.messages = messages
        self.usage = None

    def __iter__(self):
        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                stream=True,
                stream_options={"include_usage": True},
            )
            for chunk in stream:
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage:
                    self.usage = {
                        "input_tokens": int(chunk_usage.prompt_tokens or 0),
                        "output_tokens": int(chunk_usage.completion_tokens or 0),
                        "total_tokens": int(chunk_usage.total_tokens or 0),
                        "cached_input_tokens": KimiClientWrapper._cached_tokens(chunk_usage),
                    }
                choices = getattr(chunk, "choices", None) or []
                if choices:
                    delta = choices[0].delta.content
                    if delta:
                        yield delta
        except Exception as exc:
            raise RuntimeError(f"Kimi streaming request failed: {exc}") from exc
