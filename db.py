"""SQLite DB: 사용자(로그인·잠금) + 대시보드용 샘플 매출 데이터."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent / "data" / "app.db"


def hash_password_sha256(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


@contextmanager
def get_conn() -> Any:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                lock_until REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sale_date TEXT NOT NULL,
                category TEXT NOT NULL,
                region TEXT NOT NULL,
                amount REAL NOT NULL,
                quantity INTEGER NOT NULL
            );
            """
        )
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE username = ?",
            ("admin",),
        ).fetchone()
        if row["c"] == 0:
            conn.execute(
                """
                INSERT INTO users (username, password_hash, failed_attempts, lock_until)
                VALUES (?, ?, 0, 0)
                """,
                ("admin", hash_password_sha256("admin1234")),
            )
        row = conn.execute("SELECT COUNT(*) AS c FROM sales").fetchone()
        if row["c"] == 0:
            _seed_sales(conn)


def _seed_sales(conn: sqlite3.Connection) -> None:
    categories = ("전자", "식품", "의류", "가구", "도서")
    regions = ("서울", "경기", "부산", "대구", "광주")
    base = date.today() - timedelta(days=120)
    rows = []
    for i in range(400):
        d = base + timedelta(days=i % 90)
        cat = categories[i % len(categories)]
        reg = regions[i % len(regions)]
        amount = 10000 + (i * 137) % 500000
        qty = 1 + (i * 3) % 48
        rows.append((d.isoformat(), cat, reg, float(amount), qty))
    conn.executemany(
        "INSERT INTO sales (sale_date, category, region, amount, quantity) VALUES (?,?,?,?,?)",
        rows,
    )


def try_login(username: str, password: str) -> tuple[bool, str]:
    """성공 시 (True, ''), 실패 시 (False, 메시지). 3회 실패 시 300초 잠금."""
    now = time.time()
    with get_conn() as conn:
        u = conn.execute(
            "SELECT id, password_hash, failed_attempts, lock_until FROM users WHERE username = ?",
            (username.strip(),),
        ).fetchone()
        if u is None:
            return False, "사용자를 찾을 수 없습니다."

        lock_until = float(u["lock_until"] or 0)
        if lock_until > now:
            remain = int(lock_until - now) + 1
            return False, f"로그인이 일시 중지되었습니다. 약 {remain}초 후 다시 시도하세요."

        if hash_password_sha256(password) == u["password_hash"]:
            conn.execute(
                "UPDATE users SET failed_attempts = 0, lock_until = 0 WHERE id = ?",
                (u["id"],),
            )
            return True, ""

        attempts = int(u["failed_attempts"] or 0) + 1
        if attempts >= 3:
            conn.execute(
                "UPDATE users SET failed_attempts = 0, lock_until = ? WHERE id = ?",
                (now + 300.0, u["id"]),
            )
            return False, "비밀번호를 3회 이상 틀려 5분간 로그인할 수 없습니다."

        conn.execute(
            "UPDATE users SET failed_attempts = ? WHERE id = ?",
            (attempts, u["id"]),
        )
        return False, f"비밀번호가 올바르지 않습니다. ({attempts}/3)"


def fetch_sales(
    date_from: str | None,
    date_to: str | None,
    categories: list[str] | None,
    regions: list[str] | None,
) -> list[sqlite3.Row]:
    q = "SELECT sale_date, category, region, amount, quantity FROM sales WHERE 1=1"
    params: list[Any] = []
    if date_from:
        q += " AND sale_date >= ?"
        params.append(date_from)
    if date_to:
        q += " AND sale_date <= ?"
        params.append(date_to)
    if categories:
        q += " AND category IN (%s)" % ",".join("?" * len(categories))
        params.extend(categories)
    if regions:
        q += " AND region IN (%s)" % ",".join("?" * len(regions))
        params.extend(regions)
    q += " ORDER BY sale_date"
    with get_conn() as conn:
        return list(conn.execute(q, params).fetchall())


def distinct_categories() -> list[str]:
    with get_conn() as conn:
        return [r[0] for r in conn.execute("SELECT DISTINCT category FROM sales ORDER BY category")]


def distinct_regions() -> list[str]:
    with get_conn() as conn:
        return [r[0] for r in conn.execute("SELECT DISTINCT region FROM sales ORDER BY region")]


def sales_date_bounds() -> tuple[str, str]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT MIN(sale_date) AS mn, MAX(sale_date) AS mx FROM sales"
        ).fetchone()
        return str(row["mn"]), str(row["mx"])
