from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from pathlib import Path
from datetime import datetime, timezone
import sqlite3
import hashlib
import secrets


BASE_DIR = Path(__file__).resolve().parent.parent
DB_FILE = BASE_DIR / "aihubx.db"
FRONTEND_FILE = BASE_DIR / "frontend" / "index.html"

app = FastAPI(
    title="AIHUBX AI Cost Optimizer",
    version="4.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

MODEL_PRICES = {
    "GPT": 0.005,
    "Gemini": 0.002,
    "Claude": 0.004,
    "Llama": 0.001
}


class RegisterData(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=5, max_length=150)
    password: str = Field(min_length=6, max_length=100)


class LoginData(BaseModel):
    email: str
    password: str


class UsageData(BaseModel):
    agent_name: str = Field(min_length=1, max_length=100)
    model: str
    api_calls: int = Field(gt=0)
    tokens: int = Field(gt=0)


def get_db():
    db = sqlite3.connect(DB_FILE)
    db.row_factory = sqlite3.Row
    return db


def hash_password(password: str, salt: str = None):
    if salt is None:
        salt = secrets.token_hex(16)

    hashed = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt.encode(),
        120000
    ).hex()

    return salt, hashed


def verify_password(password: str, salt: str, stored_hash: str):
    _, hashed = hash_password(password, salt)
    return secrets.compare_digest(hashed, stored_hash)


def create_tables():
    db = get_db()

    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS usage_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_name TEXT NOT NULL,
            model TEXT NOT NULL,
            api_calls INTEGER NOT NULL,
            tokens INTEGER NOT NULL,
            cost REAL NOT NULL,
            saving REAL NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    columns = [
        row["name"]
        for row in db.execute(
            "PRAGMA table_info(usage_history)"
        ).fetchall()
    ]

    if "user_id" not in columns:
        db.execute(
            "ALTER TABLE usage_history ADD COLUMN user_id INTEGER"
        )

    if "created_at" not in columns:
        db.execute(
            "ALTER TABLE usage_history ADD COLUMN created_at TEXT"
        )

        db.execute("""
            UPDATE usage_history
            SET created_at = ?
            WHERE created_at IS NULL
        """, (
            datetime.now(timezone.utc).isoformat(),
        ))

    db.commit()
    db.close()


create_tables()


def get_current_user(authorization: str = None):
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Login required"
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization"
        )

    token = authorization.replace("Bearer ", "", 1).strip()

    db = get_db()

    user = db.execute("""
        SELECT
            users.id,
            users.name,
            users.email
        FROM sessions
        JOIN users
            ON users.id = sessions.user_id
        WHERE sessions.token = ?
    """, (token,)).fetchone()

    db.close()

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Session expired. Please login again."
        )

    return user


def calculate_usage(model: str, tokens: int):
    if model not in MODEL_PRICES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Unknown model",
                "available_models": list(MODEL_PRICES.keys())
            }
        )

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

    return (
        current_cost,
        recommended_model,
        recommended_cost,
        saving
    )


@app.get("/")
def home():
    if not FRONTEND_FILE.exists():
        return {
            "message": "AIHUBX is running!",
            "status": "success",
            "version": "4.0.0"
        }

    return FileResponse(FRONTEND_FILE)


@app.get("/api")
def api_info():
    return {
        "message": "AIHUBX API is running!",
        "status": "success",
        "version": "4.0.0"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "database_exists": DB_FILE.exists(),
        "frontend_exists": FRONTEND_FILE.exists(),
        "version": "4.0.0"
    }


@app.post("/auth/register")
def register(data: RegisterData):

    email = data.email.strip().lower()

    db = get_db()

    existing = db.execute(
        "SELECT id FROM users WHERE email = ?",
        (email,)
    ).fetchone()

    if existing:
        db.close()
        raise HTTPException(
            status_code=409,
            detail="Email already registered"
        )

    salt, password_hash = hash_password(
        data.password
    )

    created_at = datetime.now(
        timezone.utc
    ).isoformat()

    cursor = db.execute("""
        INSERT INTO users
        (
            name,
            email,
            password_hash,
            password_salt,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        data.name.strip(),
        email,
        password_hash,
        salt,
        created_at
    ))

    user_id = cursor.lastrowid

    token = secrets.token_urlsafe(32)

    db.execute("""
        INSERT INTO sessions
        (
            token,
            user_id,
            created_at
        )
        VALUES (?, ?, ?)
    """, (
        token,
        user_id,
        created_at
    ))

    db.commit()
    db.close()

    return {
        "message": "Account created successfully",
        "token": token,
        "user": {
            "id": user_id,
            "name": data.name.strip(),
            "email": email
        }
    }


@app.post("/auth/login")
def login(data: LoginData):

    email = data.email.strip().lower()

    db = get_db()

    user = db.execute("""
        SELECT
            id,
            name,
            email,
            password_hash,
            password_salt
        FROM users
        WHERE email = ?
    """, (email,)).fetchone()

    if not user:
        db.close()
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    valid = verify_password(
        data.password,
        user["password_salt"],
        user["password_hash"]
    )

    if not valid:
        db.close()
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    token = secrets.token_urlsafe(32)

    db.execute("""
        INSERT INTO sessions
        (
            token,
            user_id,
            created_at
        )
        VALUES (?, ?, ?)
    """, (
        token,
        user["id"],
        datetime.now(timezone.utc).isoformat()
    ))

    db.commit()
    db.close()

    return {
        "message": "Login successful",
        "token": token,
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"]
        }
    }


@app.post("/auth/logout")
def logout(
    authorization: str = Header(default=None)
):

    if not authorization:
        return {
            "message": "Logged out"
        }

    token = authorization.replace(
        "Bearer ",
        "",
        1
    ).strip()

    db = get_db()

    db.execute(
        "DELETE FROM sessions WHERE token = ?",
        (token,)
    )

    db.commit()
    db.close()

    return {
        "message": "Logged out successfully"
    }


@app.get("/auth/me")
def me(
    authorization: str = Header(default=None)
):

    user = get_current_user(
        authorization
    )

    return {
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"]
        }
    }


@app.get("/models")
def models():
    return {
        "models": [
            {
                "name": name,
                "price_per_1000_tokens": price
            }
            for name, price in MODEL_PRICES.items()
        ]
    }


@app.post("/usage")
def add_usage(
    data: UsageData,
    authorization: str = Header(default=None)
):

    user = get_current_user(
        authorization
    )

    (
        current_cost,
        recommended_model,
        recommended_cost,
        saving
    ) = calculate_usage(
        data.model,
        data.tokens
    )

    created_at = datetime.now(
        timezone.utc
    ).isoformat()

    db = get_db()

    cursor = db.execute("""
        INSERT INTO usage_history
        (
            user_id,
            agent_name,
            model,
            api_calls,
            tokens,
            cost,
            saving,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user["id"],
        data.agent_name,
        data.model,
        data.api_calls,
        data.tokens,
        current_cost,
        saving,
        created_at
    ))

    record_id = cursor.lastrowid

    db.commit()
    db.close()

    return {
        "message": "Usage data analyzed",
        "id": record_id,
        "agent_name": data.agent_name,
        "model": data.model,
        "api_calls": data.api_calls,
        "tokens": data.tokens,
        "total_cost": round(current_cost, 4),
        "recommended_model": recommended_model,
        "recommended_cost": round(recommended_cost, 4),
        "estimated_saving": round(saving, 4),
        "created_at": created_at
    }


@app.get("/usage/summary")
def usage_summary(
    authorization: str = Header(default=None)
):

    user = get_current_user(
        authorization
    )

    db = get_db()

    row = db.execute("""
        SELECT
            COUNT(*) AS total_records,
            COALESCE(SUM(api_calls), 0) AS total_api_calls,
            COALESCE(SUM(tokens), 0) AS total_tokens,
            COALESCE(SUM(cost), 0) AS total_cost,
            COALESCE(SUM(saving), 0) AS total_saving
        FROM usage_history
        WHERE user_id = ?
    """, (
        user["id"],
    )).fetchone()

    db.close()

    return {
        "total_records": row["total_records"],
        "total_api_calls": row["total_api_calls"],
        "total_tokens": row["total_tokens"],
        "total_cost": round(row["total_cost"], 4),
        "total_saving": round(row["total_saving"], 4)
    }


@app.get("/usage/history")
def usage_history(
    authorization: str = Header(default=None)
):

    user = get_current_user(
        authorization
    )

    db = get_db()

    rows = db.execute("""
        SELECT
            id,
            agent_name,
            model,
            api_calls,
            tokens,
            cost,
            saving,
            created_at
        FROM usage_history
        WHERE user_id = ?
        ORDER BY id DESC
    """, (
        user["id"],
    )).fetchall()

    db.close()

    return {
        "history": [
            {
                "id": row["id"],
                "agent_name": row["agent_name"],
                "model": row["model"],
                "api_calls": row["api_calls"],
                "tokens": row["tokens"],
                "cost": round(row["cost"], 4),
                "saving": round(row["saving"], 4),
                "created_at": row["created_at"]
            }
            for row in rows
        ]
    }


@app.delete("/usage/{usage_id}")
def delete_usage(
    usage_id: int,
    authorization: str = Header(default=None)
):

    user = get_current_user(
        authorization
    )

    db = get_db()

    cursor = db.execute("""
        DELETE FROM usage_history
        WHERE id = ?
        AND user_id = ?
    """, (
        usage_id,
        user["id"]
    ))

    db.commit()
    db.close()

    if cursor.rowcount == 0:
        raise HTTPException(
            status_code=404,
            detail="Usage record not found"
        )

    return {
        "message": "Usage record deleted",
        "id": usage_id
    }


@app.delete("/usage")
def clear_usage(
    authorization: str = Header(default=None)
):

    user = get_current_user(
        authorization
    )

    db = get_db()

    db.execute("""
        DELETE FROM usage_history
        WHERE user_id = ?
    """, (
        user["id"],
    ))

    db.commit()
    db.close()

    return {
        "message": "Your usage history cleared"
    }


@app.get("/security/status")
def security_status():

    return {
        "security": "active",
        "authentication": "enabled",
        "password_hashing": "PBKDF2-SHA256",
        "database_exists": DB_FILE.exists(),
        "frontend_exists": FRONTEND_FILE.exists(),
        "version": "4.0.0"
    }
