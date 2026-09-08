from typing import Dict, Any


class AIProvider:
    def __init__(self, name: str):
        self.name = name

    async def generate(self, prompt: str) -> Dict[str, Any]:
        raise NotImplementedError(
            "This provider is not implemented yet."
        )


class OpenAIProvider(AIProvider):
    def __init__(self):
        super().__init__("OpenAI")

    async def generate(self, prompt: str) -> Dict[str, Any]:
        return {
            "provider": self.name,
            "status": "ready",
            "message": "OpenAI integration layer is ready.",
            "prompt": prompt
        }


class GeminiProvider(AIProvider):
    def __init__(self):
        super().__init__("Gemini")

    async def generate(self, prompt: str) -> Dict[str, Any]:
        return {
            "provider": self.name,
            "status": "ready",
            "message": "Gemini integration layer is ready.",
            "prompt": prompt
        }


class ClaudeProvider(AIProvider):
    def __init__(self):
        super().__init__("Claude")

    async def generate(self, prompt: str) -> Dict[str, Any]:
        return {
            "provider": self.name,
            "status": "ready",
            "message": "Claude integration layer is ready.",
            "prompt": prompt
        }


class LlamaProvider(AIProvider):
    def __init__(self):
        super().__init__("Llama")

    async def generate(self, prompt: str) -> Dict[str, Any]:
        return {
            "provider": self.name,
            "status": "ready",
            "message": "Llama integration layer is ready.",
            "prompt": prompt
        }


PROVIDERS = {
    "GPT": OpenAIProvider(),
    "Gemini": GeminiProvider(),
    "Claude": ClaudeProvider(),
    "Llama": LlamaProvider(),
}


def get_provider(model: str) -> AIProvider:
    model = model.strip()

    if model not in PROVIDERS:
        raise ValueError(
            f"Unsupported model: {model}"
        )

    return PROVIDERS[model]
