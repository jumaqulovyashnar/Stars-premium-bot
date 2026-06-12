import logging
import time
import re
from datetime import datetime
from collections import defaultdict
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import (
    MIN_STARS, MAX_STARS, PAYMENT_TIMEOUT, ADMIN_IDS,
    FRAGMENT_API_KEY_TON, WALLET_ADDRESS,
)
from database import upsert_user, get_user, set_user_language, create_order, get_user_orders, update_order_status
from keyboards import language_keyboard, main_menu_keyboard, username_keyboard, invoice_keyboard
from locales import t
from fragment_api import FragmentAPIClient, PriceCalculator

logger = logging.getLogger(__name__)
user_router = Router()


# ── Xavfsizlik: Username sanitizatsiya ─────────────────────────────────────────
_USERNAME_REGEX = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{3,31}$')


def sanitize_username(raw: str) -> str | None:
    """
    Telegram username validatsiyasi.
    - 5-32 belgi
    - Faqat harf, raqam, pastki chiziq
    - Harf bilan boshlanishi kerak
    XSS va injection oldini oladi.
    """
    cleaned = raw.strip().lstrip("@")
    if not cleaned:
        return None
    if not _USERNAME_REGEX.match(cleaned):
        return None
    return cleaned


# ── Rate Limiter (DDoS himoyasi) ───────────────────────────────────────────────
_rate_limit: dict[int, list[float]] = defaultdict(list)
RATE_LIMIT_MAX = 20      # 1 daqiqada maksimum so'rovlar
RATE_LIMIT_WINDOW = 60   # sekund

# Anti-spam: 1 soatda maksimum 10 ta buyurtma
_order_limit: dict[int, list[float]] = defaultdict(list)
ORDER_LIMIT_MAX = 10       # 1 soatda maksimum buyurtmalar
ORDER_LIMIT_WINDOW = 3600  # 1 soat

# Flood control: bitta callback'ni qayta-qayta bosishdan himoya
_last_callback: dict[int, float] = {}
CALLBACK_COOLDOWN = 1.0  # sekund


def is_rate_limited(user_id: int) -> bool:
    """User 1 daqiqada 20 tadan ko'p so'rov yuborganda True qaytaradi."""
    now = time.time()
    _rate_limit[user_id] = [t for t in _rate_limit[user_id] if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_limit[user_id]) >= RATE_LIMIT_MAX:
        return True
    _rate_limit[user_id].append(now)
    return False


def is_order_limited(user_id: int) -> bool:
    """User 1 soatda 10 tadan ko'p buyurtma berganda True qaytaradi."""
    now = time.time()
    _order_limit[user_id] = [t for t in _order_limit[user_id] if now - t < ORDER_LIMIT_WINDOW]
    if len(_order_limit[user_id]) >= ORDER_LIMIT_MAX:
        return True
    _order_limit[user_id].append(now)
    return False


def is_flood(user_id: int) -> bool:
    """Bitta tugmani qayta-qayta bosishdan himoya (1 sek cooldown)."""
    now = time.time()
    last = _last_callback.get(user_id, 0)
    if now - last < CALLBACK_COOLDOWN:
        return True
    _last_callback[user_id] = now
    return False


@user_router.message.outer_middleware()
async def rate_limit_message_middleware(handler, event: Message, data: dict):
    if event.from_user and event.from_user.id not in ADMIN_IDS:
        if is_rate_limited(event.from_user.id):
            await event.answer("⚠️ Juda ko'p so'rov! Iltimos, biroz kuting.")
            return
    return await handler(event, data)


@user_router.callback_query.outer_middleware()
async def rate_limit_callback_middleware(handler, event: CallbackQuery, data: dict):
    if event.from_user and event.from_user.id not in ADMIN_IDS:
        if is_rate_limited(event.from_user.id):
            await event.answer("⚠️ Juda ko'p so'rov! Biroz kuting.", show_alert=True)
            return
        if is_flood(event.from_user.id):
            await event.answer()
            return
    return await handler(event, data)

_frag_client = None


def get_frag_client() -> FragmentAPIClient:
    global _frag_client
    if _frag_client is None:
        _frag_client = FragmentAPIClient(api_key=FRAGMENT_API_KEY_TON)
    return _frag_client


class UserStates(StatesGroup):
    choosing_language      = State()
    stars_enter_username   = State()
    stars_enter_amount     = State()
    stars_confirm          = State()
    premium_enter_username = State()
    premium_choose_period  = State()
    premium_confirm        = State()


async def get_lang(user_id: int) -> str:
    user = await get_user(user_id)
    return user["language"] if user else "uz"


# ── /start ─────────────────────────────────────────────────────────────────────

@user_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    await upsert_user(user.id, user.username or "", user.full_name)

    if user.id in ADMIN_IDS:
        from keyboards import admin_menu_keyboard
        await message.answer(
            f"👑 <b>Admin Panel</b>\n\nSalom, {user.full_name}!",
            reply_markup=admin_menu_keyboard(),
            parse_mode="HTML"
        )
        return

    db_user = await get_user(user.id)
    if not db_user or not db_user["language"]:
        await message.answer(t("choose_language", "uz"), reply_markup=language_keyboard())
        await state.set_state(UserStates.choosing_language)
    else:
        lang = db_user["language"]
        await message.answer(
            t("main_menu", lang, name=user.full_name),
            reply_markup=main_menu_keyboard(lang),
            parse_mode="HTML"
        )


@user_router.message(Command("lang"))
async def cmd_lang(message: Message, state: FSMContext):
    await state.set_state(UserStates.choosing_language)
    await message.answer(t("choose_language", "uz"), reply_markup=language_keyboard())


# ── Til tanlash ────────────────────────────────────────────────────────────────

@user_router.callback_query(F.data.startswith("lang:"))
async def cb_language(call: CallbackQuery, state: FSMContext):
    lang = call.data.split(":")[1]
    await set_user_language(call.from_user.id, lang)
    await state.clear()
    await call.message.edit_text(
        t("main_menu", lang, name=call.from_user.full_name),
        reply_markup=main_menu_keyboard(lang), parse_mode="HTML"
    )


@user_router.callback_query(F.data == "action:main_menu")
async def cb_main_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    lang = await get_lang(call.from_user.id)
    await call.message.edit_text(
        t("main_menu", lang, name=call.from_user.full_name),
        reply_markup=main_menu_keyboard(lang), parse_mode="HTML"
    )


@user_router.callback_query(F.data == "action:change_lang")
async def cb_change_lang(call: CallbackQuery, state: FSMContext):
    await state.set_state(UserStates.choosing_language)
    await call.message.edit_text(t("choose_language", "uz"), reply_markup=language_keyboard())


@user_router.callback_query(F.data == "action:help")
async def cb_help(call: CallbackQuery):
    lang = await get_lang(call.from_user.id)
    b = InlineKeyboardBuilder()
    b.button(text=t("btn_main_menu", lang), callback_data="action:main_menu")
    await call.message.edit_text(t("help_text", lang), reply_markup=b.as_markup(), parse_mode="HTML")


@user_router.callback_query(F.data == "action:my_orders")
async def cb_my_orders(call: CallbackQuery):
    lang = await get_lang(call.from_user.id)
    orders = await get_user_orders(call.from_user.id)
    b = InlineKeyboardBuilder()
    b.button(text=t("btn_main_menu", lang), callback_data="action:main_menu")
    if not orders:
        await call.message.edit_text(t("no_orders", lang), reply_markup=b.as_markup())
        return

    status_emoji = {
        "pending": "⏳",
        "paid": "💸",
        "completed": "✅",
        "failed": "❌",
        "expired": "⌛",
        "cancelled": "🚫",
        "rejected": "🚫",
    }

    text = "📋 <b>Buyurtmalarim</b>\n\n"
    for idx, o in enumerate(orders, 1):
        date = datetime.fromtimestamp(o["created_at"]).strftime("%d.%m.%Y %H:%M")
        emoji = status_emoji.get(o["status"], "❓")
        type_emoji = "⭐" if o["order_type"] == "stars" else "💎"
        product = f"{o['amount']} Stars" if o["order_type"] == "stars" else f"{o['amount']} oy Premium"

        text += f"<b>{idx}.</b> {type_emoji} {product}\n"
        text += f"    👤 @{o['target_username']}\n"
        text += f"    💰 {o['price_ton']} TON | {emoji} {o['status'].capitalize()}\n"
        text += f"    📅 {date}\n\n"

    await call.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")


# ── STARS ──────────────────────────────────────────────────────────────────────

@user_router.callback_query(F.data == "action:buy_stars")
async def cb_buy_stars(call: CallbackQuery, state: FSMContext):
    lang = await get_lang(call.from_user.id)
    await state.set_state(UserStates.stars_enter_username)
    await state.update_data(lang=lang)
    uname = call.from_user.username or ""
    await call.message.edit_text(
        t("stars_enter_username", lang),
        reply_markup=username_keyboard(lang, uname), parse_mode="HTML"
    )


@user_router.callback_query(F.data.startswith("username:"), UserStates.stars_enter_username)
async def cb_stars_username_cb(call: CallbackQuery, state: FSMContext):
    username = call.data.split(":", 1)[1]
    await state.update_data(target_username=username)
    await _stars_ask_amount(call.message, state, edit=True)


@user_router.message(UserStates.stars_enter_username)
async def msg_stars_username(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.startswith("@") or len(text) < 2:
        data = await state.get_data()
        lang = data.get("lang", "uz")
        await message.answer(t("username_invalid", lang))
        return
    username = sanitize_username(text)
    if not username:
        data = await state.get_data()
        lang = data.get("lang", "uz")
        await message.answer(t("username_invalid", lang))
        return
    await state.update_data(target_username=username)
    await _stars_ask_amount(message, state, edit=False)


async def _stars_ask_amount(msg, state, edit=False):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    await state.set_state(UserStates.stars_enter_amount)

    b = InlineKeyboardBuilder()
    b.button(text=t("btn_back", lang), callback_data="action:buy_stars")

    text = t("stars_enter_amount", lang, min=MIN_STARS, max=MAX_STARS)
    if edit:
        await msg.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")
    else:
        await msg.answer(text, reply_markup=b.as_markup(), parse_mode="HTML")


@user_router.message(UserStates.stars_enter_amount)
async def msg_stars_amount(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")

    try:
        amount = int(message.text.strip().replace(" ", "").replace(",", ""))
    except ValueError:
        await message.answer(t("stars_invalid_amount", lang, min=MIN_STARS, max=MAX_STARS))
        return

    if amount < MIN_STARS or amount > MAX_STARS:
        await message.answer(t("stars_invalid_amount", lang, min=MIN_STARS, max=MAX_STARS))
        return

    await state.update_data(amount=amount)

    # Real API dan narx olish
    try:
        client = get_frag_client()
        pricing = await client.get_stars_pricing(amount)
        # Ustama qo'shish
        price_ton, price_usd = PriceCalculator.calc_stars_price(pricing)
    except Exception as e:
        logger.error(f"Stars pricing xatosi: {e}")
        await message.answer(f"❌ Narx olishda xato: {e}")
        return

    await state.update_data(price_ton=price_ton, price_usd=price_usd, real_amount=pricing.amount)
    await state.set_state(UserStates.stars_confirm)

    target = data.get("target_username", "")

    # Memo generatsiya (random son)
    import random
    memo = str(random.randint(1000000000, 9999999999))
    await state.update_data(memo=memo)

    # TON miqdorini nanoton ga aylantirish (Tonkeeper uchun)
    amount_nano = int(price_ton * 1_000_000_000)
    tonkeeper_url = f"ton://transfer/{WALLET_ADDRESS}?amount={amount_nano}&text={memo}"

    text = (
        f"⭐ <b>Stars xarid</b>\n\n"
        f"👤 Kimga: @{target}\n"
        f"⭐ Miqdor: {pricing.amount}\n\n"
        f"💰 <b>Narx:</b>\n"
        f"💎 TON: <b>{price_ton} TON</b>\n"
        f"💵 USD: <b>${price_usd}</b>\n\n"
        f"💳 <b>To'lov manzili:</b>\n<code>{WALLET_ADDRESS}</code>\n\n"
        f"💬 <b>Comment (memo):</b> <code>{memo}</code>\n\n"
        f"‼️ Aynan <b>{price_ton} TON</b> yuboring.\n"
        f"⚠️ Comment (memo) ni albatta qo'shing, aks holda to'lov tasdiqlanmaydi.\n\n"
        f"⏰ Buyurtma {PAYMENT_TIMEOUT} daqiqa ichida amal qiladi."
    )

    b = InlineKeyboardBuilder()
    b.button(text="💚 Pay in App", url=tonkeeper_url)
    b.button(text="✅ To'ladim", callback_data="stars_paid")
    b.button(text="❌ Bekor qilish", callback_data="stars_cancel")
    b.adjust(1)
    await message.answer(text, reply_markup=b.as_markup(), parse_mode="HTML")


@user_router.callback_query(F.data == "stars_paid", UserStates.stars_confirm)
async def cb_stars_paid(call: CallbackQuery, state: FSMContext):
    # Anti-spam tekshiruv
    if is_order_limited(call.from_user.id):
        await call.answer("⚠️ 1 soatda 10 tadan ko'p buyurtma berish mumkin emas! Keyinroq urinib ko'ring.", show_alert=True)
        return
    data = await state.get_data()
    lang = data.get("lang", "uz")
    amount = data.get("real_amount", data.get("amount"))
    target = data.get("target_username", call.from_user.username or "")
    price_ton = data.get("price_ton", 0)
    price_usd = data.get("price_usd", 0)
    memo = data.get("memo", "")

    order = await create_order(
        user_id=call.from_user.id,
        order_type="stars",
        target_username=target,
        amount=amount,
        price_ton=price_ton,
        price_usdt=price_usd,
        currency="TON",
        memo=memo,
    )

    await update_order_status(order["id"], "paid")
    await state.clear()

    b = InlineKeyboardBuilder()
    b.button(text=t("btn_main_menu", lang), callback_data="action:main_menu")
    await call.message.edit_text(
        f"✅ Buyurtma #{order['id']} qabul qilindi!\n\n"
        f"⭐ {amount} Stars → @{target}\n"
        f"💰 {price_ton} TON\n\n"
        f"⏳ Tekshirilmoqda... Tez orada yuboriladi!",
        reply_markup=b.as_markup(), parse_mode="HTML"
    )

    # Adminlarga xabar
    await _notify_admins_new(call.bot, order, "stars", target, amount, status="paid")


# ── PREMIUM ────────────────────────────────────────────────────────────────────

@user_router.callback_query(F.data == "action:buy_premium")
async def cb_buy_premium(call: CallbackQuery, state: FSMContext):
    lang = await get_lang(call.from_user.id)
    await state.set_state(UserStates.premium_enter_username)
    await state.update_data(lang=lang)
    uname = call.from_user.username or ""
    await call.message.edit_text(
        t("premium_enter_username", lang),
        reply_markup=username_keyboard(lang, uname), parse_mode="HTML"
    )


@user_router.callback_query(F.data.startswith("username:"), UserStates.premium_enter_username)
async def cb_premium_username_cb(call: CallbackQuery, state: FSMContext):
    username = call.data.split(":", 1)[1]
    await state.update_data(target_username=username)
    await _show_premium_periods(call.message, state, username, edit=True)


@user_router.message(UserStates.premium_enter_username)
async def msg_premium_username(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.startswith("@") or len(text) < 2:
        data = await state.get_data()
        lang = data.get("lang", "uz")
        await message.answer(t("username_invalid", lang))
        return
    username = sanitize_username(text)
    if not username:
        data = await state.get_data()
        lang = data.get("lang", "uz")
        await message.answer(t("username_invalid", lang))
        return
    await state.update_data(target_username=username)
    await _show_premium_periods(message, state, username, edit=False)


async def _show_premium_periods(msg, state, username, edit=False):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    await state.set_state(UserStates.premium_choose_period)

    # Real API dan premium narxlarini olish
    try:
        client = get_frag_client()
        packages = await client.get_premium_pricing()
    except Exception as e:
        logger.error(f"Premium pricing xatosi: {e}")
        text = f"❌ Narx olishda xato: {e}"
        if edit:
            await msg.edit_text(text)
        else:
            await msg.answer(text)
        return

    # Narxlarni state ga saqlash
    pkg_data = {}
    b = InlineKeyboardBuilder()
    for pkg in packages:
        ton, usd = PriceCalculator.calc_premium_price(pkg)
        b.button(
            text=f"{'💎'} {pkg.months} oy — {ton} TON (${usd})",
            callback_data=f"premium_period:{pkg.months}"
        )
        pkg_data[str(pkg.months)] = {"ton": ton, "usd": usd, "base_ton": pkg.price_ton, "base_usd": pkg.price_usd}

    b.button(text=t("btn_back", lang), callback_data="action:main_menu")
    b.adjust(1)

    await state.update_data(premium_packages=pkg_data)
    text = f"💎 <b>Premium xarid</b>\n\n👤 Kimga: @{username}\n\n📦 Muddatni tanlang:"
    if edit:
        await msg.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")
    else:
        await msg.answer(text, reply_markup=b.as_markup(), parse_mode="HTML")


@user_router.callback_query(F.data.startswith("premium_period:"), UserStates.premium_choose_period)
async def cb_premium_period(call: CallbackQuery, state: FSMContext):
    months = int(call.data.split(":")[1])
    data = await state.get_data()
    lang = data.get("lang", "uz")
    target = data.get("target_username", "")
    pkg_data = data.get("premium_packages", {})
    pkg = pkg_data.get(str(months), {})

    price_ton = pkg.get("ton", 0)
    price_usd = pkg.get("usd", 0)

    await state.update_data(months=months, price_ton=price_ton, price_usd=price_usd)
    await state.set_state(UserStates.premium_confirm)

    # Memo generatsiya
    import random
    memo = str(random.randint(1000000000, 9999999999))
    await state.update_data(memo=memo)

    # Tonkeeper deeplink
    amount_nano = int(price_ton * 1_000_000_000)
    tonkeeper_url = f"ton://transfer/{WALLET_ADDRESS}?amount={amount_nano}&text={memo}"

    text = (
        f"💎 <b>Premium xarid</b>\n\n"
        f"👤 Kimga: @{target}\n"
        f"📦 Muddat: {months} oy\n\n"
        f"💰 <b>Narx:</b>\n"
        f"💎 TON: <b>{price_ton} TON</b>\n"
        f"💵 USD: <b>${price_usd}</b>\n\n"
        f"💳 <b>To'lov manzili:</b>\n<code>{WALLET_ADDRESS}</code>\n\n"
        f"💬 <b>Comment (memo):</b> <code>{memo}</code>\n\n"
        f"‼️ Aynan <b>{price_ton} TON</b> yuboring.\n"
        f"⚠️ Comment (memo) ni albatta qo'shing, aks holda to'lov tasdiqlanmaydi.\n\n"
        f"⏰ Buyurtma {PAYMENT_TIMEOUT} daqiqa ichida amal qiladi."
    )

    b = InlineKeyboardBuilder()
    b.button(text="💚 Pay in App", url=tonkeeper_url)
    b.button(text="✅ To'ladim", callback_data="premium_paid")
    b.button(text="❌ Bekor qilish", callback_data="premium_cancel")
    b.adjust(1)
    await call.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")


@user_router.callback_query(F.data == "premium_paid", UserStates.premium_confirm)
async def cb_premium_paid(call: CallbackQuery, state: FSMContext):
    # Anti-spam tekshiruv
    if is_order_limited(call.from_user.id):
        await call.answer("⚠️ 1 soatda 10 tadan ko'p buyurtma berish mumkin emas! Keyinroq urinib ko'ring.", show_alert=True)
        return
    data = await state.get_data()
    lang = data.get("lang", "uz")
    months = data.get("months")
    target = data.get("target_username", call.from_user.username or "")
    price_ton = data.get("price_ton", 0)
    price_usd = data.get("price_usd", 0)
    memo = data.get("memo", "")

    order = await create_order(
        user_id=call.from_user.id,
        order_type="premium",
        target_username=target,
        amount=months,
        price_ton=price_ton,
        price_usdt=price_usd,
        currency="TON",
        memo=memo,
    )

    await update_order_status(order["id"], "paid")
    await state.clear()

    b = InlineKeyboardBuilder()
    b.button(text=t("btn_main_menu", lang), callback_data="action:main_menu")
    await call.message.edit_text(
        f"✅ Buyurtma #{order['id']} qabul qilindi!\n\n"
        f"💎 {months} oy Premium → @{target}\n"
        f"💰 {price_ton} TON\n\n"
        f"⏳ Tekshirilmoqda... Tez orada yuboriladi!",
        reply_markup=b.as_markup(), parse_mode="HTML"
    )

    await _notify_admins_new(call.bot, order, "premium", target, months, status="paid")


# ── Bekor qilish ──────────────────────────────────────────────────────────────

@user_router.callback_query(F.data == "stars_cancel", UserStates.stars_confirm)
async def cb_stars_cancel(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    await state.clear()
    b = InlineKeyboardBuilder()
    b.button(text=t("btn_main_menu", lang), callback_data="action:main_menu")
    await call.message.edit_text(t("order_cancelled", lang), reply_markup=b.as_markup())


@user_router.callback_query(F.data == "premium_cancel", UserStates.premium_confirm)
async def cb_premium_cancel(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    await state.clear()
    b = InlineKeyboardBuilder()
    b.button(text=t("btn_main_menu", lang), callback_data="action:main_menu")
    await call.message.edit_text(t("order_cancelled", lang), reply_markup=b.as_markup())


@user_router.callback_query(F.data.startswith("cancel_order:"))
async def cb_cancel_order(call: CallbackQuery):
    order_id = int(call.data.split(":")[1])
    lang = await get_lang(call.from_user.id)
    await update_order_status(order_id, "cancelled")
    b = InlineKeyboardBuilder()
    b.button(text=t("btn_main_menu", lang), callback_data="action:main_menu")
    await call.message.edit_text(t("order_cancelled", lang), reply_markup=b.as_markup())


# ── Fragment API orqali bajarish (admin uchun ham) ─────────────────────────────

async def execute_order_via_api(bot, order_id: int) -> tuple[bool, str]:
    from database import get_order
    order = await get_order(order_id)
    if not order:
        return False, "Buyurtma topilmadi"

    client = get_frag_client()
    username = order["target_username"]

    try:
        if order["order_type"] == "stars":
            result = await client.buy_stars(username, order["amount"])
        else:
            result = await client.buy_premium(username, order["amount"])

        if result.success:
            await update_order_status(order_id, "completed")
            try:
                user = await get_user(order["user_id"])
                lang = user["language"] if user else "uz"
                if order["order_type"] == "stars":
                    msg = f"✅ Buyurtma #{order_id} bajarildi!\n⭐ {order['amount']} Stars @{username} ga yuborildi!"
                else:
                    msg = f"✅ Buyurtma #{order_id} bajarildi!\n💎 {order['amount']} oy Premium @{username} ga yuborildi!"
                await bot.send_message(order["user_id"], msg)
            except Exception:
                pass
            return True, f"✅ Muvaffaqiyatli! Cost: {result.cost} {result.payment_method}"
        else:
            return False, f"❌ Fragment API: {result.message}"
    except Exception as e:
        logger.error(f"Order execute xatosi: {e}")
        return False, str(e)


async def _notify_admins_new(bot, order, order_type, target, amount, status="paid"):
    unit = "⭐" if order_type == "stars" else "oy 💎"
    if status == "paid":
        emoji = "✅"
        status_text = "To'lov qildi"
    elif status == "cancelled":
        emoji = "❌"
        status_text = "To'lov qilmadi"
    else:
        emoji = "⏳"
        status_text = status

    text = (
        f"📦 <b>Buyurtma #{order['id']}</b>\n\n"
        f"Tur: {order_type} | {amount} {unit}\n"
        f"🎯 @{target}\n"
        f"💰 {order['price_ton']} TON / ${order['price_usdt']}\n"
        f"Status: {status_text} {emoji}"
    )
    b = InlineKeyboardBuilder()
    b.button(text="🗑 O'chirish", callback_data="admin_delete_msg")
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, reply_markup=b.as_markup(), parse_mode="HTML")
        except Exception:
            pass
