
import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

try:
    from aiogram.fsm.storage.redis import RedisStorage
    from redis.asyncio import Redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from config import BOT_TOKEN, PAYMENT_TIMEOUT, FRAGMENT_API_KEY_TON
from handlers import user_router, admin_router
from database import init_db, expire_old_orders, get_pending_paid_orders, update_order_status, get_user
from fragment_api import FragmentAPIClient

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_bot_instance: Bot = None

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


async def get_storage():
    """Redis ga ulanishga harakat qiladi. Muvaffaqiyatsiz bo'lsa MemoryStorage qaytaradi."""
    if not REDIS_AVAILABLE:
        logger.warning("⚠️ Redis kutubxonasi o'rnatilmagan, MemoryStorage ishlatiladi")
        return MemoryStorage()

    try:
        redis = Redis.from_url(REDIS_URL, decode_responses=False)
        await redis.ping()
        # Write test — read-only emasligini tekshirish
        await redis.set("_bot_health_check", "ok", ex=10)
        logger.info("✅ Redis ulandi (read/write)")
        return RedisStorage(redis=redis)
    except Exception as e:
        logger.warning(f"⚠️ Redis ishlamayapti ({e}), MemoryStorage ishlatiladi")
        return MemoryStorage()


# ── Background tasks ──────────────────────────────────────────────────────────

async def order_expiry_task():
    """Har daqiqada pending buyurtmalarni tekshiradi, 30 daqiqa o'tganlari expired bo'ladi."""
    while True:
        try:
            expired = await expire_old_orders(timeout_minutes=PAYMENT_TIMEOUT)
            if expired > 0:
                logger.info(f"⏰ {expired} ta buyurtma expired bo'ldi ({PAYMENT_TIMEOUT} daqiqa o'tdi)")
        except Exception as e:
            logger.error(f"Expiry task xatosi: {e}")
        await asyncio.sleep(60)


async def auto_fulfill_task():
    """
    Har 15 sekundda 'paid' statusli buyurtmalarni tekshiradi.
    Fragment API orqali stars/premium sotib olib yuboradi.
    Parallel ishlaydi — bir vaqtda 5 tagacha buyurtma.
    """
    global _bot_instance
    while True:
        try:
            orders = await get_pending_paid_orders()
            semaphore = asyncio.Semaphore(5)

            async def process_order(order):
                async with semaphore:
                    await _fulfill_single_order(order)

            tasks = [process_order(order) for order in orders]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            logger.error(f"Auto fulfill xatosi: {e}")
        await asyncio.sleep(15)


async def _fulfill_single_order(order):
    global _bot_instance
    order_id = order["id"]
    username = order["target_username"]

    client = FragmentAPIClient(api_key=FRAGMENT_API_KEY_TON)
    try:
        if order["order_type"] == "stars":
            result = await client.buy_stars(username, order["amount"])
        else:
            result = await client.buy_premium(username, order["amount"])

        if result.success:
            await update_order_status(order_id, "completed")
            logger.info(f"✅ #{order_id} bajarildi! {order['order_type']} → @{username}")

            if _bot_instance:
                try:
                    user = await get_user(order["user_id"])
                    lang = user["language"] if user else "uz"
                    from locales import t
                    from aiogram.utils.keyboard import InlineKeyboardBuilder
                    if order["order_type"] == "stars":
                        msg = f"✅ Buyurtma #{order_id} bajarildi!\n\n⭐ {order['amount']} Stars @{username} ga yuborildi!"
                    else:
                        msg = f"✅ Buyurtma #{order_id} bajarildi!\n\n💎 {order['amount']} oy Premium @{username} ga yuborildi!"
                    b = InlineKeyboardBuilder()
                    b.button(text=t("btn_main_menu", lang), callback_data="action:main_menu")
                    await _bot_instance.send_message(order["user_id"], msg, reply_markup=b.as_markup())
                except Exception as e:
                    logger.error(f"User xabar xatosi: {e}")
        else:
            logger.warning(f"❌ #{order_id} xato: {result.message}")
            await update_order_status(order_id, "failed")
            if _bot_instance:
                try:
                    user = await get_user(order["user_id"])
                    lang = user["language"] if user else "uz"
                    from locales import t
                    from aiogram.utils.keyboard import InlineKeyboardBuilder
                    msg = t("order_failed_no_balance", lang, id=order_id)
                    b = InlineKeyboardBuilder()
                    b.button(text=t("btn_main_menu", lang), callback_data="action:main_menu")
                    await _bot_instance.send_message(order["user_id"], msg, reply_markup=b.as_markup())
                except Exception:
                    pass

                # Adminga "to'lov qilinmadi" xabari
                try:
                    from config import ADMIN_IDS
                    from aiogram.utils.keyboard import InlineKeyboardBuilder as IKB2
                    unit = "⭐" if order["order_type"] == "stars" else "oy 💎"
                    admin_text = (
                        f"📦 <b>Buyurtma #{order_id}</b>\n\n"
                        f"Tur: {order['order_type']} | {order['amount']} {unit}\n"
                        f"🎯 @{username}\n"
                        f"💰 {order['price_ton']} TON / ${order['price_usdt']}\n"
                        f"Status: To'lov qilinmadi ❌"
                    )
                    ab = IKB2()
                    ab.button(text="🗑 O'chirish", callback_data="admin_delete_msg")
                    for admin_id in ADMIN_IDS:
                        try:
                            await _bot_instance.send_message(admin_id, admin_text, reply_markup=ab.as_markup(), parse_mode="HTML")
                        except Exception:
                            pass
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"#{order_id} execute xatosi: {e}")
    finally:
        await client.close()


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    global _bot_instance

    logger.info("🚀 Bot ishga tushmoqda...")
    logger.info(f"   DATABASE_URL: ...@{os.getenv('DATABASE_URL', '').split('@')[-1] if '@' in os.getenv('DATABASE_URL', '') else 'not set'}")
    logger.info(f"   REDIS_URL: {REDIS_URL}")

    # 1. PostgreSQL
    await init_db()

    # 2. Storage (Redis yoki MemoryStorage)
    storage = await get_storage()

    # 3. Bot
    bot = Bot(token=BOT_TOKEN)
    _bot_instance = bot
    dp = Dispatcher(storage=storage)

    dp.include_router(admin_router)
    dp.include_router(user_router)

    # 4. Background tasklar
    asyncio.create_task(order_expiry_task())
    asyncio.create_task(auto_fulfill_task())

    logger.info("✅ Bot started! Polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
