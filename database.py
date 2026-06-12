"""
Database modul — PostgreSQL (asyncpg) bilan ishlaydi.
Agar PostgreSQL ulanmasa — startup'da aniq xato xabari beradi.
"""

import time
import random
import string
import os
import asyncpg
import logging

logger = logging.getLogger(__name__)

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/starsbot")

_pool: asyncpg.Pool = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        try:
            _pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=20, timeout=10)
            logger.info("✅ PostgreSQL ulandi")
        except Exception as e:
            logger.critical(f"❌ PostgreSQL ga ulanib bo'lmadi: {e}")
            logger.critical(f"   DATABASE_URL: {DB_URL.split('@')[-1] if '@' in DB_URL else DB_URL}")
            logger.critical("   PostgreSQL ishga tushirilganmi? 'docker compose up -d' buyrug'ini ishlating.")
            raise SystemExit(1)
    return _pool


async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     BIGINT PRIMARY KEY,
                username    TEXT,
                full_name   TEXT,
                language    TEXT DEFAULT 'uz',
                created_at  BIGINT DEFAULT (EXTRACT(EPOCH FROM NOW())::BIGINT)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id              SERIAL PRIMARY KEY,
                user_id         BIGINT,
                order_type      TEXT,
                target_username TEXT,
                amount          INTEGER,
                price_ton       DOUBLE PRECISION,
                price_usdt      DOUBLE PRECISION DEFAULT 0,
                currency        TEXT DEFAULT 'TON',
                status          TEXT DEFAULT 'pending',
                memo            TEXT,
                fragment_order_id TEXT,
                created_at      BIGINT DEFAULT (EXTRACT(EPOCH FROM NOW())::BIGINT),
                paid_at         BIGINT
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at)")
    logger.info("✅ Database tablolar tayyor")


# ── Users ──────────────────────────────────────────────────────────────────────

async def upsert_user(user_id, username, full_name, language="uz"):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, username, full_name, language)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT(user_id) DO UPDATE SET
                username=EXCLUDED.username, full_name=EXCLUDED.full_name
        """, user_id, username, full_name, language)


async def get_user(user_id):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)
        return dict(row) if row else None


async def set_user_language(user_id, lang):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET language=$1 WHERE user_id=$2", lang, user_id)


async def get_all_users():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM users ORDER BY created_at DESC")
        return [dict(r) for r in rows]


# ── Orders ─────────────────────────────────────────────────────────────────────

def _gen_memo():
    return ''.join(random.choices(string.digits, k=10))


async def create_order(user_id, order_type, target_username,
                        amount, price_ton, price_usdt=0.0, currency="TON", memo=None):
    if not memo:
        memo = _gen_memo()
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO orders
              (user_id, order_type, target_username, amount, price_ton, price_usdt, currency, memo)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
        """, user_id, order_type, target_username, amount, price_ton, price_usdt, currency, memo)
        return {"id": row["id"], "memo": memo,
                "price_ton": price_ton, "price_usdt": price_usdt, "currency": currency}


async def get_order(order_id):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM orders WHERE id=$1", order_id)
        return dict(row) if row else None


async def get_user_orders(user_id, limit=10):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM orders WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2",
            user_id, limit)
        return [dict(r) for r in rows]


async def update_order_status(order_id, status, fragment_order_id=None):
    paid_at = int(time.time()) if status == "paid" else None
    pool = await get_pool()
    async with pool.acquire() as conn:
        if fragment_order_id:
            await conn.execute("UPDATE orders SET status=$1, fragment_order_id=$2 WHERE id=$3",
                               status, fragment_order_id, order_id)
        elif paid_at:
            await conn.execute("UPDATE orders SET status=$1, paid_at=$2 WHERE id=$3",
                               status, paid_at, order_id)
        else:
            await conn.execute("UPDATE orders SET status=$1 WHERE id=$2", status, order_id)


async def get_all_orders(status=None, limit=50):
    pool = await get_pool()
    async with pool.acquire() as conn:
        if status:
            rows = await conn.fetch(
                "SELECT * FROM orders WHERE status=$1 ORDER BY created_at DESC LIMIT $2", status, limit)
        else:
            rows = await conn.fetch("SELECT * FROM orders ORDER BY created_at DESC LIMIT $1", limit)
        return [dict(r) for r in rows]


async def get_stats():
    pool = await get_pool()
    async with pool.acquire() as conn:
        stats = {}
        stats["total_users"] = await conn.fetchval("SELECT COUNT(*) FROM users")
        stats["total_orders"] = await conn.fetchval("SELECT COUNT(*) FROM orders")
        stats["paid_orders"] = await conn.fetchval("SELECT COUNT(*) FROM orders WHERE status IN ('paid','completed')")
        stats["failed_orders"] = await conn.fetchval("SELECT COUNT(*) FROM orders WHERE status IN ('failed','rejected','expired')")
        stats["pending_orders"] = await conn.fetchval("SELECT COUNT(*) FROM orders WHERE status='pending'")
        stats["total_revenue_ton"] = await conn.fetchval("SELECT COALESCE(SUM(price_ton),0) FROM orders WHERE status IN ('paid','completed')")
        stats["total_revenue_usdt"] = await conn.fetchval("SELECT COALESCE(SUM(price_usdt),0) FROM orders WHERE status IN ('paid','completed')")
        return stats


async def expire_old_orders(timeout_minutes: int = 30) -> int:
    expire_before = int(time.time()) - (timeout_minutes * 60)
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE orders SET status='expired' WHERE status='pending' AND created_at < $1", expire_before)
        return int(result.split()[-1])


async def get_pending_paid_orders():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM orders WHERE status='paid' ORDER BY created_at ASC")
        return [dict(r) for r in rows]
