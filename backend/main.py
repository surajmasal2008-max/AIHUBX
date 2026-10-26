import os
import sqlite3
import hashlib
import hmac
import secrets
from pathlib import Path
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from jose import jwt, JWTError
from openai import AsyncOpenAI


BASE_DIR = Path(__file__).resolve().parent.parent
DB_FILE = BASE_DIR / "aihubx.db"

SECRET_KEY = os.getenv("JWT_SECRET_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = 60 * 24

if not SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY environment variable is required")

app = FastAPI(title="AIHUBX AI Cost Optimizer", version="2.0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def hash_password(password: str) -> str:
    iterations = 310_000
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, iterations_text, salt_hex, expected_hex = stored_hash.split("$")
        if scheme != "pbkdf2_sha256":
            return False

        iterations = int(iterations_text)
        if iterations < 1 or iterations > 2_000_000:
            return False

        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(expected_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


security = HTTPBearer()
client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

MODEL_PRICES_PER_MILLION = {
    "gpt-4o-mini": {
        "input": 0.15,
        "output": 0.60,
    }
}


def get_db():
    db = sqlite3.connect(DB_FILE)
    db.row_factory = sqlite3.Row
    return db


def create_tables():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS usage_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                agent_name TEXT NOT NULL,
                model TEXT NOT NULL,
                api_calls INTEGER NOT NULL,
                tokens INTEGER NOT NULL,
                cost REAL NOT NULL,
                saving REAL NOT NULL DEFAULT 0,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        # Add newer columns if an older database already exists.
        columns = {
            row["name"]
            for row in db.execute("PRAGMA table_info(usage_history)").fetchall()
        }

        migrations = {
            "input_tokens": "INTEGER NOT NULL DEFAULT 0",
            "output_tokens": "INTEGER NOT NULL DEFAULT 0",
            "created_at": "TEXT NOT NULL DEFAULT ''",
            "saving": "REAL NOT NULL DEFAULT 0",
        }

        for column, definition in migrations.items():
            if column not in columns:
                db.execute(
                    f"ALTER TABLE usage_history ADD COLUMN {column} {definition}"
                )


create_tables()


class AuthData(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=1024)


class GenerateData(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    agent_name: str = Field(default="AIHUBX Agent", max_length=100)


class UsageData(BaseModel):
    agent_name: str = Field(min_length=1, max_length=100)
    model: str
    api_calls: int = Field(ge=1, le=1000000)
    tokens: int = Field(ge=0, le=100000000)


def create_token(user_id: int):
    expires = datetime.now(timezone.utc) + timedelta(
        minutes=ACCESS_TOKEN_MINUTES
    )
    return jwt.encode(
        {"sub": str(user_id), "exp": expires},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    try:
        payload = jwt.decode(
            credentials.credentials,
            SECRET_KEY,
            algorithms=[ALGORITHM],
        )
        user_id = int(payload["sub"])
    except (JWTError, ValueError, KeyError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    with get_db() as db:
        user = db.execute(
            "SELECT id, email FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return {"id": user["id"], "email": user["email"]}


def get_price(model: str):
    prices = MODEL_PRICES_PER_MILLION.get(model)
    if not prices:
        raise HTTPException(
            status_code=400,
            detail=f"Pricing not configured for model: {model}",
        )
    return prices


@app.get("/")
def home():
    return {"service": "AIHUBX", "status": "running"}


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "database_exists": DB_FILE.exists(),
    }


@app.post("/auth/register")
def register(data: AuthData):
    email = data.email.strip().lower()

    if len(data.password.encode("utf-8")) > 4096:
        raise HTTPException(status_code=400, detail="Password is too long")

    with get_db() as db:
        existing = db.execute(
            "SELECT id FROM users WHERE email = ?", (email,)
        ).fetchone()

        if existing:
            raise HTTPException(
                status_code=409,
                detail="Email already registered",
            )

        password_hash = hash_password(data.password)

        cursor = db.execute(
            """
            INSERT INTO users (email, password_hash, created_at)
            VALUES (?, ?, ?)
            """,
            (email, password_hash, datetime.now(timezone.utc).isoformat()),
        )
        user_id = cursor.lastrowid

    return {
        "message": "Registration successful",
        "access_token": create_token(user_id),
        "token_type": "bearer",
    }


@app.post("/auth/login")
def login(data: AuthData):
    email = data.email.strip().lower()

    with get_db() as db:
        user = db.execute(
            "SELECT id, password_hash FROM users WHERE email = ?",
            (email,),
        ).fetchone()

    if not user or not verify_password(data.password, user["password_hash"]):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
        )

    return {
        "access_token": create_token(user["id"]),
        "token_type": "bearer",
    }


@app.get("/auth/me")
def me(user=Depends(current_user)):
    return user


@app.post("/ai/generate")
async def generate(data: GenerateData, user=Depends(current_user)):
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="OpenAI API key is not configured",
        )

    model = "gpt-4o-mini"

    try:
        response = await client.responses.create(
            model=model,
            input=data.prompt,
        )
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="AI provider request failed. Check provider configuration and limits.",
        )

    usage = response.usage
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    total_tokens = getattr(
        usage, "total_tokens", input_tokens + output_tokens
    ) or 0

    prices = get_price(model)
    cost = (
        input_tokens * prices["input"]
        + output_tokens * prices["output"]
    ) / 1_000_000

    with get_db() as db:
        db.execute(
            """
            INSERT INTO usage_history
            (user_id, agent_name, model, api_calls, tokens, cost,
             saving, input_tokens, output_tokens, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                data.agent_name,
                model,
                1,
                total_tokens,
                cost,
                0,
                input_tokens,
                output_tokens,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    return {
        "text": response.output_text,
        "model": model,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        },
        "actual_usage_cost_usd_estimate": round(cost, 8),
    }


@app.get("/usage/summary")
def usage_summary(user=Depends(current_user)):
    with get_db() as db:
        row = db.execute(
            """
            SELECT COUNT(*) AS total_records,
                   COALESCE(SUM(api_calls), 0) AS total_api_calls,
                   COALESCE(SUM(tokens), 0) AS total_tokens,
                   COALESCE(SUM(cost), 0) AS total_cost,
                   COALESCE(SUM(saving), 0) AS total_saving
            FROM usage_history
            WHERE user_id = ?
            """,
            (user["id"],),
        ).fetchone()

    return {
        "total_records": row["total_records"],
        "total_api_calls": row["total_api_calls"],
        "total_tokens": row["total_tokens"],
        "total_cost_usd_estimate": round(row["total_cost"], 8),
        "total_saving": round(row["total_saving"], 8),
    }


@app.get("/usage/history")
def usage_history(user=Depends(current_user)):
    with get_db() as db:
        rows = db.execute(
            """
            SELECT id, agent_name, model, api_calls, tokens, cost,
                   saving, input_tokens, output_tokens, created_at
            FROM usage_history
            WHERE user_id = ?
            ORDER BY id DESC LIMIT 500
            """,
            (user["id"],),
        ).fetchall()

    return {"history": [dict(row) for row in rows]}


@app.post("/usage")
def add_usage(data: UsageData, user=Depends(current_user)):
    # This is manually entered usage, not verified provider usage.
    prices = get_price(data.model)
    cost = data.tokens * prices["input"] / 1_000_000

    with get_db() as db:
        db.execute(
            """
            INSERT INTO usage_history
            (user_id, agent_name, model, api_calls, tokens, cost,
             saving, input_tokens, output_tokens, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                data.agent_name,
                data.model,
                data.api_calls,
                data.tokens,
                cost,
                0,
                data.tokens,
                0,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    return {
        "message": "Manual usage record saved",
        "cost_usd_estimate": round(cost, 8),
    }


@app.get("/usage/history/all")
def all_usage(user=Depends(current_user)):
    return usage_history(user)


@app.get("/optimize")
def optimize(model: str, tokens: int, user=Depends(current_user)):
    if tokens < 0:
        raise HTTPException(
            status_code=400,
            detail="Tokens cannot be negative",
        )

    prices = get_price(model)
    current_cost = tokens * prices["input"] / 1_000_000

    return {
        "current_model": model,
        "tokens": tokens,
        "current_cost_usd_estimate": round(current_cost, 8),
        "note": "Estimate uses input-token pricing only; it is not a provider comparison.",
    }


@app.get("/security/status")
def security_status():
    return {
        "security": "JWT authentication enabled",
        "database_exists": DB_FILE.exists(),
        "openai_configured": client is not None,
    }
