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
