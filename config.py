import os
import sys
from dotenv import load_dotenv

load_dotenv()

# ── Bot ────────────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
    print("❌ BOT_TOKEN .env faylda sozlanmagan!")
    sys.exit(1)

# ── Admins ─────────────────────────────────────────────────────────────────────
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "123456789").split(",")))

# ── Fragment-API.uz ────────────────────────────────────────────────────────────
FRAGMENT_API_KEY_TON  = os.getenv("FRAGMENT_API_KEY_TON",  "")
FRAGMENT_API_KEY_USDT = os.getenv("FRAGMENT_API_KEY_USDT", "")

if not FRAGMENT_API_KEY_TON:
    print("⚠️ FRAGMENT_API_KEY_TON sozlanmagan! Bot narx ko'rsata olmaydi.")

# ── Wallet manzili ─────────────────────────────────────────────────────────────
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "")

if not WALLET_ADDRESS:
    print("⚠️ WALLET_ADDRESS sozlanmagan! To'lov manzili ko'rsatilmaydi.")

# ── Stars limits ───────────────────────────────────────────────────────────────
MIN_STARS = 50
MAX_STARS = 1_000_000

# ── Payment timeout ────────────────────────────────────────────────────────────
PAYMENT_TIMEOUT = 30  # daqiqa


