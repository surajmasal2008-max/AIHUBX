MODEL_PRICING = {
    "GPT": 0.005,
    "Gemini": 0.002,
    "Claude": 0.004,
    "Llama": 0.001,
}


def get_model_price(model: str) -> float:
    model = model.strip()

    if model not in MODEL_PRICING:
        raise ValueError(f"Unsupported model: {model}")

    return MODEL_PRICING[model]


def calculate_cost(model: str, tokens: int) -> float:
    price = get_model_price(model)
    return round(tokens * price, 2)


def get_cheapest_model() -> str:
    return min(MODEL_PRICING, key=MODEL_PRICING.get)


def calculate_saving(model: str, tokens: int):
    current_cost = calculate_cost(model, tokens)

    cheapest_model = get_cheapest_model()
    recommended_cost = calculate_cost(cheapest_model, tokens)

    saving = round(max(current_cost - recommended_cost, 0), 2)

    return {
        "current_model": model,
        "current_cost": current_cost,
        "recommended_model": cheapest_model,
        "recommended_cost": recommended_cost,
        "saving": saving,
    }
