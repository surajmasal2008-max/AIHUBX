import os
from openai import AsyncOpenAI


class OpenAIProvider:
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise ValueError("OPENAI_API_KEY is not configured")

        self.client = AsyncOpenAI(api_key=api_key)

    async def generate(self, prompt: str):
        response = await self.client.responses.create(
            model="gpt-4o-mini",
            input=prompt
        )

        usage = response.usage

        return {
            "text": response.output_text,
            "usage": {
                "input_tokens": getattr(usage, "input_tokens", 0),
                "output_tokens": getattr(usage, "output_tokens", 0),
                "total_tokens": getattr(usage, "total_tokens", 0)
            }
        }


def get_provider(model: str):
    model = model.strip().lower()

    if model in ["gpt", "openai", "gpt-4o-mini"]:
        return OpenAIProvider()

    raise ValueError(
        f"Provider for '{model}' is not configured yet."
    )
