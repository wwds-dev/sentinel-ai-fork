import os
from openai import OpenAI

from services.api_limits import REQUEST_TIMEOUT_SECONDS, MAX_RETRIES


class OpenAIClientWrapper:
    KNOWN_MODELS = [
        "gpt-4o-mini",
        "gpt-4o",
        "gpt-4.1-mini",
        "gpt-4.1",
        "dall-e-3",
    ]

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.client = (
            OpenAI(
                api_key=self.api_key,
                timeout=REQUEST_TIMEOUT_SECONDS,
                max_retries=MAX_RETRIES,
            )
            if self.api_key
            else None
        )

    @staticmethod
    def key_available():
        return bool(os.getenv("OPENAI_API_KEY"))

    def list_models(self) -> list[str]:
        """Chat-capable model ids, newest listing from the API when reachable.

        Falls back to KNOWN_MODELS with no key or on any API error so the model
        dropdowns are never left empty.
        """
        if not self.client:
            return self.KNOWN_MODELS
        try:
            result = self.client.models.list()
            models = sorted(
                m.id for m in result.data
                if any(x in m.id.lower() for x in ("gpt", "o1", "o3", "o4", "dall-e", "image"))
            )
            return models if models else self.KNOWN_MODELS
        except Exception:
            return self.KNOWN_MODELS

    def chat(self, messages, model="gpt-4o-mini"):
        if not self.client:
            raise RuntimeError("OPENAI_API_KEY is not set.")

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

    def generate(self, prompt, model="gpt-4o-mini"):
        messages = [{"role": "user", "content": prompt}]
        return self.chat(messages=messages, model=model)
    
    def generate_image(self, prompt: str, size: str = "1024x1024") -> str:
        """Generate an image with DALL-E 3. Returns the image URL."""
        if not self.client:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        response = self.client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size=size,
            quality="standard",
            n=1,
        )
        return response.data[0].url

    def stream_chat(self, messages, model="gpt-4o-mini"):
        if not self.client:
            raise RuntimeError("OPENAI_API_KEY is not set.")

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
            raise RuntimeError(f"OpenAI streaming request failed: {e}")
