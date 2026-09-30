import os


def get_provider(provider_name: str = "default"):
    providers = {
        "openai": {
            "name": "OpenAI",
            "api_key": os.getenv("OPENAI_API_KEY"),
            "base_url": "https://api.openai.com/v1",
        },
        "gemini": {
            "name": "Google Gemini",
            "api_key": os.getenv("GEMINI_API_KEY"),
            "base_url": "https://generativelanguage.googleapis.com",
        },
        "default": {
            "name": "AIHUBX",
            "api_key": None,
            "base_url": None,
        },
    }

    return providers.get(provider_name, providers["default"])
