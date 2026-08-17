from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
import sqlite3


BASE_DIR = Path(__file__).resolve().parent.parent
DB_FILE = BASE_DIR / "aihubx.db"


app = FastAPI(
    title="AIHUBX AI Cost Optimizer",
    version="2.0.0"
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# DATABASE
# =========================

def get_db():
    db = sqlite3.connect(DB_FILE)
    db.row_factory = sqlite3.Row
    return db


def create_table():
    db = get_db()

    db.execute("""
        CREATE TABLE IF NOT EXISTS usage_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_name TEXT NOT NULL,
            model TEXT NOT NULL,
            api_calls INTEGER NOT NULL,
            tokens INTEGER NOT NULL,
            cost REAL NOT NULL,
            saving REAL NOT NULL
        )
    """)

    db.commit()
    db.close()


create_table()


# =========================
# MODEL PRICING
# Price = per 1000 tokens
# =========================

MODEL_PRICES = {
    "GPT": 0.005,
    "Gemini": 0.002,
    "Claude": 0.004,
    "Llama": 0.001
}


# =========================
# MODELS
# =========================

class UsageData(BaseModel):
    agent_name: str
    model: str
    api_calls: int
    tokens: int


# =========================
# HOME
# =========================

@app.get("/")
def home():
    return {
        "message": "AIHUBX is running!",
        "status": "success",
        "version": "2.0.0"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }


# =========================
# COST CALCULATION
# =========================

def calculate_cost(model: str, tokens: int):
    return (
        tokens / 1000
    ) * MODEL_PRICES[model]


# =========================
# MODEL COMPARISON
# =========================

@app.get("/models")
def model_comparison(tokens: int):

    if tokens <= 0:
        return {
            "error": "Tokens must be greater than 0"
        }

    models = []

    cheapest_model = min(
        MODEL_PRICES,
        key=MODEL_PRICES.get
    )

    cheapest_cost = calculate_cost(
        cheapest_model,
        tokens
    )

    for model, price in MODEL_PRICES.items():

        cost = calculate_cost(
            model,
            tokens
        )

        saving = max(
            cost - cheapest_cost,
            0
        )

        models.append({
            "model": model,
            "price_per_1000_tokens": price,
            "cost": round(cost, 6),
            "saving_vs_cheapest": round(
                saving,
                6
            ),
            "recommended":
                model == cheapest_model
        })

    return {
        "tokens": tokens,
        "recommended_model": cheapest_model,
        "models": models
    }


# =========================
# OPTIMIZE
# =========================

@app.get("/optimize")
def optimize(model: str, tokens: int):

    if model not in MODEL_PRICES:

        return {
            "error": "Unknown model",
            "available_models":
                list(MODEL_PRICES.keys())
        }

    if tokens <= 0:

        return {
            "error":
                "Tokens must be greater than 0"
        }

    current_cost = calculate_cost(
        model,
        tokens
    )

    recommended_model = min(
        MODEL_PRICES,
        key=MODEL_PRICES.get
    )

    recommended_cost = calculate_cost(
        recommended_model,
        tokens
    )

    saving = max(
        current_cost - recommended_cost,
        0
    )

    return {
        "current_model": model,
        "recommended_model":
            recommended_model,
        "tokens": tokens,
        "current_cost":
            round(current_cost, 6),
        "recommended_cost":
            round(recommended_cost, 6),
        "potential_saving":
            round(saving, 6)
    }


# =========================
# ADD USAGE
# =========================

@app.post("/usage")
def add_usage(data: UsageData):

    if data.model not in MODEL_PRICES:

        return {
            "error": "Unknown model",
            "available_models":
                list(MODEL_PRICES.keys())
        }

    if data.api_calls <= 0:

        return {
            "error":
                "API calls must be greater than 0"
        }

    if data.tokens <= 0:

        return {
            "error":
                "Tokens must be greater than 0"
        }


    current_cost = calculate_cost(
        data.model,
        data.tokens
    )


    recommended_model = min(
        MODEL_PRICES,
        key=MODEL_PRICES.get
    )


    recommended_cost = calculate_cost(
        recommended_model,
        data.tokens
    )


    saving = max(
        current_cost - recommended_cost,
        0
    )


    db = get_db()

    db.execute(
        """
        INSERT INTO usage_history
        (
            agent_name,
            model,
            api_calls,
            tokens,
            cost,
            saving
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            data.agent_name,
            data.model,
            data.api_calls,
            data.tokens,
            current_cost,
            saving
        )
    )

    db.commit()
    db.close()


    return {
        "message":
            "Usage data analyzed",

        "model":
            data.model,

        "api_calls":
            data.api_calls,

        "tokens":
            data.tokens,

        "total_cost":
            round(current_cost, 6),

        "recommended_model":
            recommended_model,

        "recommended_cost":
            round(recommended_cost, 6),

        "estimated_saving":
            round(saving, 6)
    }


# =========================
# SUMMARY
# =========================

@app.get("/usage/summary")
def usage_summary():

    db = get_db()

    row = db.execute(
        """
        SELECT
            COUNT(*) AS total_records,
            COALESCE(
                SUM(api_calls), 0
            ) AS total_api_calls,
            COALESCE(
                SUM(tokens), 0
            ) AS total_tokens,
            COALESCE(
                SUM(cost), 0
            ) AS total_cost,
            COALESCE(
                SUM(saving), 0
            ) AS total_saving
        FROM usage_history
        """
    ).fetchone()

    db.close()


    return {
        "total_records":
            row["total_records"],

        "total_api_calls":
            row["total_api_calls"],

        "total_tokens":
            row["total_tokens"],

        "total_cost":
            round(
                row["total_cost"],
                6
            ),

        "total_saving":
            round(
                row["total_saving"],
                6
            )
    }


# =========================
# HISTORY
# =========================

@app.get("/usage/history")
def usage_history():

    db = get_db()

    rows = db.execute(
        """
        SELECT
            id,
            agent_name,
            model,
            api_calls,
            tokens,
            cost,
            saving
        FROM usage_history
        ORDER BY id DESC
        """
    ).fetchall()

    db.close()


    history = []

    for row in rows:

        history.append({

            "id":
                row["id"],

            "agent_name":
                row["agent_name"],

            "model":
                row["model"],

            "api_calls":
                row["api_calls"],

            "tokens":
                row["tokens"],

            "cost":
                round(
                    row["cost"],
                    6
                ),

            "saving":
                round(
                    row["saving"],
                    6
                )
        })


    return {
        "history": history
    }


# =========================
# SECURITY
# =========================

@app.get("/security/status")
def security_status():

    return {
        "security": "active",
        "database_exists":
            DB_FILE.exists()
    }
