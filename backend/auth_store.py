"""Small SQLite-backed auth and account store for SpatialParse."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DB_PATH = Path(__file__).parent.parent / "spatialparse.db"
PBKDF2_ITERATIONS = 260_000
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def _db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS parse_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                query TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'fast',
                centroid_lon REAL,
                centroid_lat REAL,
                steps_json TEXT NOT NULL,
                geojson_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS saved_places (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                query TEXT NOT NULL,
                lon REAL,
                lat REAL,
                geojson_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS user_consents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                consent_type TEXT NOT NULL,
                document_version TEXT NOT NULL,
                accepted INTEGER NOT NULL DEFAULT 0,
                accepted_at TEXT NOT NULL,
                ip_address TEXT,
                user_agent TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_user_consents_user_id
              ON user_consents(user_id);

            CREATE INDEX IF NOT EXISTS idx_user_consents_type
              ON user_consents(user_id, consent_type);
            """
        )


def _row_to_user(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "email": row["email"],
        "name": row["name"],
        "created_at": row["created_at"],
    }


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _json_loads(value: str) -> Any:
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        PBKDF2_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algo, iterations, salt, expected = password_hash.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt),
            int(iterations),
        ).hex()
        return hmac.compare_digest(digest, expected)
    except Exception:
        return False


def create_user(email: str, password: str, name: str = "") -> dict[str, Any]:
    email_clean = normalize_email(email)
    name_clean = str(name or "").strip() or email_clean.split("@")[0]

    if not EMAIL_RE.match(email_clean):
        raise ValueError("Введите корректный email")
    if len(password or "") < 8:
        raise ValueError("Пароль должен быть не короче 8 символов")

    with _db() as conn:
        try:
            cur = conn.execute(
                """
                INSERT INTO users (email, name, password_hash, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (email_clean, name_clean, hash_password(password), _now()),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Пользователь с таким email уже существует") from exc

        row = conn.execute("SELECT id, email, name, created_at FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
        user = _row_to_user(row)
        if user is None:
            raise ValueError("Не удалось создать пользователя")
        return user


def record_user_consent(
    user_id: int,
    consent_type: str,
    document_version: str,
    accepted: bool,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    consent_type_clean = str(consent_type or "").strip()[:80]
    document_version_clean = str(document_version or "").strip()[:80]
    if not consent_type_clean:
        raise ValueError("Тип согласия не должен быть пустым")
    if not document_version_clean:
        raise ValueError("Версия документа не должна быть пустой")

    accepted_at = _now()
    with _db() as conn:
        cur = conn.execute(
            """
            INSERT INTO user_consents
              (user_id, consent_type, document_version, accepted, accepted_at, ip_address, user_agent)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                consent_type_clean,
                document_version_clean,
                1 if accepted else 0,
                accepted_at,
                str(ip_address or "").strip()[:120] or None,
                str(user_agent or "").strip()[:500] or None,
            ),
        )

    return {
        "id": cur.lastrowid,
        "user_id": user_id,
        "consent_type": consent_type_clean,
        "document_version": document_version_clean,
        "accepted": bool(accepted),
        "accepted_at": accepted_at,
        "ip_address": ip_address,
        "user_agent": user_agent,
    }


def authenticate_user(email: str, password: str) -> dict[str, Any] | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT id, email, name, password_hash, created_at FROM users WHERE email = ?",
            (normalize_email(email),),
        ).fetchone()
        if row is None or not verify_password(password, row["password_hash"]):
            return None
        return _row_to_user(row)


def update_user_name(user_id: int, name: str) -> dict[str, Any]:
    name_clean = str(name or "").strip()[:80]
    if not name_clean:
        raise ValueError("Имя не должно быть пустым")
    with _db() as conn:
        conn.execute("UPDATE users SET name = ? WHERE id = ?", (name_clean, user_id))
        row = conn.execute(
            "SELECT id, email, name, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    user = _row_to_user(row)
    if user is None:
        raise ValueError("Пользователь не найден")
    return user


def create_session(user_id: int, days: int = 30) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=days)
    with _db() as conn:
        conn.execute(
            """
            INSERT INTO sessions (token, user_id, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (token, user_id, _now(), expires_at.isoformat(timespec="seconds")),
        )
    return token


def delete_session(token: str) -> None:
    with _db() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def get_user_by_token(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    now = _now()
    with _db() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        row = conn.execute(
            """
            SELECT u.id, u.email, u.name, u.created_at
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ? AND s.expires_at > ?
            """,
            (token, now),
        ).fetchone()
        return _row_to_user(row)


def account_summary(user_id: int) -> dict[str, Any]:
    with _db() as conn:
        history_count = conn.execute(
            "SELECT COUNT(*) FROM parse_history WHERE user_id = ?",
            (user_id,),
        ).fetchone()[0]
        saved_count = conn.execute(
            "SELECT COUNT(*) FROM saved_places WHERE user_id = ?",
            (user_id,),
        ).fetchone()[0]
        last_row = conn.execute(
            """
            SELECT created_at FROM parse_history
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    return {
        "history_count": int(history_count),
        "saved_count": int(saved_count),
        "last_activity": last_row["created_at"] if last_row else None,
    }


def save_history(
    user_id: int,
    query: str,
    mode: str,
    steps: Any,
    geojson: Any,
    centroid: list[float] | None,
) -> dict[str, Any]:
    lon = float(centroid[0]) if centroid and len(centroid) >= 2 else None
    lat = float(centroid[1]) if centroid and len(centroid) >= 2 else None
    created_at = _now()
    with _db() as conn:
        cur = conn.execute(
            """
            INSERT INTO parse_history
              (user_id, query, mode, centroid_lon, centroid_lat, steps_json, geojson_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, query, mode, lon, lat, _json_dumps(steps), _json_dumps(geojson), created_at),
        )
        item_id = cur.lastrowid
    return {
        "id": item_id,
        "query": query,
        "mode": mode,
        "centroid": [lon, lat] if lon is not None and lat is not None else None,
        "steps": steps or [],
        "geojson": geojson or {},
        "created_at": created_at,
    }


def list_history(user_id: int, limit: int = 30) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 30), 100))
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT id, query, mode, centroid_lon, centroid_lat, steps_json, geojson_json, created_at
            FROM parse_history
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "query": row["query"],
            "mode": row["mode"],
            "centroid": [row["centroid_lon"], row["centroid_lat"]]
            if row["centroid_lon"] is not None and row["centroid_lat"] is not None
            else None,
            "steps": _json_loads(row["steps_json"]),
            "geojson": _json_loads(row["geojson_json"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def delete_history_item(user_id: int, item_id: int) -> bool:
    with _db() as conn:
        cur = conn.execute(
            "DELETE FROM parse_history WHERE user_id = ? AND id = ?",
            (user_id, item_id),
        )
        return cur.rowcount > 0


def clear_history(user_id: int) -> int:
    with _db() as conn:
        cur = conn.execute("DELETE FROM parse_history WHERE user_id = ?", (user_id,))
        return cur.rowcount


def save_place(
    user_id: int,
    title: str,
    query: str,
    lon: float | None,
    lat: float | None,
    geojson: Any,
) -> dict[str, Any]:
    title_clean = str(title or "").strip()[:120] or "Сохраненный результат"
    query_clean = str(query or "").strip()
    created_at = _now()
    with _db() as conn:
        cur = conn.execute(
            """
            INSERT INTO saved_places (user_id, title, query, lon, lat, geojson_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, title_clean, query_clean, lon, lat, _json_dumps(geojson), created_at),
        )
        item_id = cur.lastrowid
    return {
        "id": item_id,
        "title": title_clean,
        "query": query_clean,
        "centroid": [lon, lat] if lon is not None and lat is not None else None,
        "geojson": geojson or {},
        "created_at": created_at,
    }


def list_saved_places(user_id: int) -> list[dict[str, Any]]:
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT id, title, query, lon, lat, geojson_json, created_at
            FROM saved_places
            WHERE user_id = ?
            ORDER BY id DESC
            """,
            (user_id,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "query": row["query"],
            "centroid": [row["lon"], row["lat"]] if row["lon"] is not None and row["lat"] is not None else None,
            "geojson": _json_loads(row["geojson_json"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def delete_saved_place(user_id: int, item_id: int) -> bool:
    with _db() as conn:
        cur = conn.execute(
            "DELETE FROM saved_places WHERE user_id = ? AND id = ?",
            (user_id, item_id),
        )
        return cur.rowcount > 0


def export_account_data(user_id: int) -> dict[str, Any]:
    with _db() as conn:
        user = _row_to_user(
            conn.execute(
                "SELECT id, email, name, created_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        )
        history_rows = conn.execute(
            """
            SELECT id, query, mode, centroid_lon, centroid_lat, steps_json, geojson_json, created_at
            FROM parse_history
            WHERE user_id = ?
            ORDER BY id DESC
            """,
            (user_id,),
        ).fetchall()
        saved_rows = conn.execute(
            """
            SELECT id, title, query, lon, lat, geojson_json, created_at
            FROM saved_places
            WHERE user_id = ?
            ORDER BY id DESC
            """,
            (user_id,),
        ).fetchall()

    history = [
        {
            "id": row["id"],
            "query": row["query"],
            "mode": row["mode"],
            "centroid": [row["centroid_lon"], row["centroid_lat"]]
            if row["centroid_lon"] is not None and row["centroid_lat"] is not None
            else None,
            "steps": _json_loads(row["steps_json"]),
            "geojson": _json_loads(row["geojson_json"]),
            "created_at": row["created_at"],
        }
        for row in history_rows
    ]
    saved_places = [
        {
            "id": row["id"],
            "title": row["title"],
            "query": row["query"],
            "centroid": [row["lon"], row["lat"]] if row["lon"] is not None and row["lat"] is not None else None,
            "geojson": _json_loads(row["geojson_json"]),
            "created_at": row["created_at"],
        }
        for row in saved_rows
    ]
    return {
        "exported_at": _now(),
        "user": user,
        "summary": account_summary(user_id),
        "history": history,
        "saved_places": saved_places,
    }


def delete_user_account(user_id: int) -> bool:
    with _db() as conn:
        cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return cur.rowcount > 0
