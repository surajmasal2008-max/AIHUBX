from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
import sqlite3


BASE_DIR = Path(__file__).resolve().parent.parent
DB_FILE = BASE_DIR / "aihubx.db"


app = FastAPI(
    title="AIHUBX AI Cost Optimizer",
    version="1.0.0"
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


# Demo pricing per 1000 tokens
MODEL_PRICES = {
    "GPT": 0.005,
    "Gemini": 0.002,
    "Claude": 0.004,
    "Llama": 0.001
}


class UsageData(BaseModel):
    agent_name: str
    model: str
    api_calls: int
    tokens: int


@app.get("/")
def home():
    return {
        "message": "AIHUBX is running!",
        "status": "success"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }


@app.get("/optimize")
def optimize(model: str, tokens: int):

    if model not in MODEL_PRICES:
        return {
            "error": "Unknown model",
            "available_models": list(MODEL_PRICES.keys())
        }

    current_cost = tokens * MODEL_PRICES[model]

    recommended_model = min(
        MODEL_PRICES,
        key=MODEL_PRICES.get
    )

    recommended_cost = (
        tokens * MODEL_PRICES[recommended_model]
    )

    saving = max(
        current_cost - recommended_cost,
        0
    )

    return {
        "current_model": model,
        "recommended_model": recommended_model,
        "tokens": tokens,
        "current_cost": round(current_cost, 4),
        "recommended_cost": round(recommended_cost, 4),
        "potential_saving": round(saving, 4)
    }


@app.post("/usage")
def add_usage(data: UsageData):

    if data.model not in MODEL_PRICES:
        return {
            "error": "Unknown model",
            "available_models": list(MODEL_PRICES.keys())
        }

    current_cost = (
        data.tokens * MODEL_PRICES[data.model]
    )

    recommended_model = min(
        MODEL_PRICES,
        key=MODEL_PRICES.get
    )

    recommended_cost = (
        data.tokens *
        MODEL_PRICES[recommended_model]
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
        "message": "Usage data analyzed",
        "model": data.model,
        "api_calls": data.api_calls,
        "tokens": data.tokens,
        "total_cost": round(current_cost, 4),
        "recommended_model": recommended_model,
        "recommended_cost": round(recommended_cost, 4),
        "estimated_saving": round(saving, 4)
    }


@app.get("/usage/summary")
def usage_summary():

    db = get_db()

    row = db.execute(
        """
        SELECT
            COUNT(*) AS total_records,
            COALESCE(SUM(api_calls), 0) AS total_api_calls,
            COALESCE(SUM(tokens), 0) AS total_tokens,
            COALESCE(SUM(cost), 0) AS total_cost,
            COALESCE(SUM(saving), 0) AS total_saving
        FROM usage_history
        """
    ).fetchone()

    db.close()

    return {
        "total_records": row["total_records"],
        "total_api_calls": row["total_api_calls"],
        "total_tokens": row["total_tokens"],
        "total_cost": round(row["total_cost"], 4),
        "total_saving": round(row["total_saving"], 4)
    }


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
            "id": row["id"],
            "agent_name": row["agent_name"],
            "model": row["model"],
            "api_calls": row["api_calls"],
            "tokens": row["tokens"],
            "cost": round(row["cost"], 4),
            "saving": round(row["saving"], 4)
        })

    return {
        "history": history
    }


@app.get("/security/status")
def security_status():

    return {
        "security": "active",
        "database_exists": DB_FILE.exists()
    }