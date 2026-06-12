import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_IDS
from database import get_all_orders, get_order, update_order_status, get_stats, get_all_users
from keyboards import admin_menu_keyboard, admin_order_keyboard, orders_filter_keyboard
from locales import t

logger = logging.getLogger(__name__)
admin_router = Router()


class AdminStates(StatesGroup):
    broadcast_message = State()


def is_admin(uid): return uid in ADMIN_IDS


@admin_router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer(t("no_permission", "en"))
        return
    await message.answer(t("admin_menu", "en"), reply_markup=admin_menu_keyboard(), parse_mode="HTML")


@admin_router.callback_query(F.data == "admin:menu")
async def cb_admin_menu(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    await call.message.edit_text(t("admin_menu", "en"), reply_markup=admin_menu_keyboard(), parse_mode="HTML")


# ── Rates ──────────────────────────────────────────────────────────────────────

@admin_router.callback_query(F.data == "admin:rates")
async def cb_admin_rates(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    from handlers.user import fetch_rates
    await call.message.edit_text("⏳ Narxlar yuklanmoqda...", parse_mode="HTML")
    try:
        rates, calc = await fetch_rates()
        text = (
            f"💱 <b>Joriy narxlar (Fragment-API.uz)</b>\n\n"
            f"📈 1 TON = <b>${rates.ton_usd:.3f}</b>\n"
            f"💵 1 USDT = <b>${rates.usdt_usd:.3f}</b>\n\n"
            f"⭐ <b>Stars (1 dona):</b>\n"
            f"   Fragment: {rates.stars_ton:.5f} TON\n"
            f"   Bizning: {calc.stars_price_ton(1):.5f} TON / {calc.stars_price_usdt(1):.4f} USDT\n\n"
            f"💎 <b>Premium narxlar:</b>\n"
            f"   3 oy: {calc.premium_price_ton(3):.3f} TON / {calc.premium_price_usdt(3):.2f} USDT\n"
            f"   6 oy: {calc.premium_price_ton(6):.3f} TON / {calc.premium_price_usdt(6):.2f} USDT\n"
            f"  12 oy: {calc.premium_price_ton(12):.3f} TON / {calc.premium_price_usdt(12):.2f} USDT\n\n"
            f"🔧 Ustamalar: Stars ≤1000 +5% | Stars >1000 +8% | Premium 3/6oy +5% | 12oy +3%"
        )
    except Exception as e:
        text = f"❌ Xato: {e}"

    b = InlineKeyboardBuilder()
    b.button(text="🔄 Yangilash", callback_data="admin:rates")
    b.button(text="◀️ Back",    callback_data="admin:menu")
    b.adjust(2)
    await call.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")


# ── Stats ──────────────────────────────────────────────────────────────────────

@admin_router.callback_query(F.data == "admin:stats")
async def cb_admin_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    s = await get_stats()
    text = (
        f"📊 <b>Statistika</b>\n\n"
        f"👥 Obunachilar: <b>{s['total_users']}</b>\n"
        f"📦 Jami buyurtmalar: <b>{s['total_orders']}</b>\n"
        f"✅ Bajarilgan: <b>{s['paid_orders']}</b>\n"
        f"❌ Bajarilmagan: <b>{s.get('failed_orders', 0)}</b>\n"
        f"⏳ Kutilmoqda: <b>{s.get('pending_orders', 0)}</b>\n\n"
        f"💰 <b>Daromad:</b>\n"
        f"   TON: <b>{s['total_revenue_ton']:.4f}</b>\n"
        f"   USD: <b>${s['total_revenue_usdt']:.2f}</b>"
    )
    b = InlineKeyboardBuilder()
    b.button(text="🔄 Yangilash", callback_data="admin:stats")
    b.button(text="◀️ Back", callback_data="admin:menu")
    b.adjust(2)
    await call.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")


# ── Users ──────────────────────────────────────────────────────────────────────

@admin_router.callback_query(F.data == "admin:users")
async def cb_admin_users(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    users = await get_all_users()
    b = InlineKeyboardBuilder()
    b.button(text="🔄 Yangilash", callback_data="admin:users")
    b.button(text="◀️ Back", callback_data="admin:menu")
    b.adjust(2)
    text = f"👥 <b>Obunachilar — {len(users)} ta</b>\n\n"
    for idx, u in enumerate(users[:30], 1):
        uname = f"@{u['username']}" if u['username'] else "—"
        date = datetime.fromtimestamp(u['created_at']).strftime("%d.%m.%Y")
        lang_flag = {"uz": "🇺🇿", "en": "🇬🇧", "ar": "🇸🇦"}.get(u['language'], "🌐")
        text += f"{idx}. {lang_flag} {uname} | <code>{u['user_id']}</code> | {date}\n"
    if len(users) > 30:
        text += f"\n... va yana {len(users)-30} ta"
    await call.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")


# ── Orders ─────────────────────────────────────────────────────────────────────

@admin_router.callback_query(F.data.startswith("admin:orders:"))
async def cb_admin_orders(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    flt = call.data.split(":")[2]
    orders = await get_all_orders(status=(None if flt == "all" else flt), limit=20)

    b = InlineKeyboardBuilder()
    for o in orders:
        emoji = "⭐" if o["order_type"] == "stars" else "💎"
        date  = datetime.fromtimestamp(o["created_at"]).strftime("%d.%m %H:%M")
        cur   = o.get("currency", "TON")
        b.button(
            text=f"#{o['id']} {emoji} @{o['target_username']} {o['amount']} [{cur}] {o['status']} {date}",
            callback_data=f"admin:order_detail:{o['id']}"
        )
    b.button(text="🔍 Filter", callback_data="admin:orders_filter")
    b.button(text="◀️ Back",  callback_data="admin:menu")
    b.adjust(1)
    await call.message.edit_text(
        f"📦 <b>Buyurtmalar [{flt.upper()}] — {len(orders)} ta</b>",
        reply_markup=b.as_markup(), parse_mode="HTML"
    )


@admin_router.callback_query(F.data == "admin:orders_filter")
async def cb_orders_filter(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    await call.message.edit_text("Filter tanlang:", reply_markup=orders_filter_keyboard())


@admin_router.callback_query(F.data.startswith("admin:order_detail:"))
async def cb_order_detail(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    order_id = int(call.data.split(":")[2])
    order = await get_order(order_id)
    if not order:
        await call.answer("Topilmadi", show_alert=True)
        return

    date = datetime.fromtimestamp(order["created_at"]).strftime("%d.%m.%Y %H:%M")
    text = (
        f"📦 <b>Buyurtma #{order['id']}</b>\n\n"
        f"👤 User: <code>{order['user_id']}</code>\n"
        f"📌 Turi: {order['order_type']}\n"
        f"🎯 Hisob: @{order['target_username']}\n"
        f"📊 Miqdor: {order['amount']}\n"
        f"💰 TON: {order['price_ton']:.4f}\n"
        f"💵 USDT: {order['price_usdt']:.2f}\n"
        f"💱 Valyuta: {order.get('currency', 'TON')}\n"
        f"🔄 Status: <b>{order['status']}</b>\n"
        f"📅 Sana: {date}"
    )
    await call.message.edit_text(text, reply_markup=admin_order_keyboard(order_id), parse_mode="HTML")


# ── Confirm / Reject ───────────────────────────────────────────────────────────

@admin_router.callback_query(F.data.startswith("admin_order:"))
async def cb_admin_order_action(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    parts    = call.data.split(":")
    action   = parts[1]
    order_id = int(parts[2])
    order    = await get_order(order_id)
    if not order:
        await call.answer("Topilmadi", show_alert=True)
        return

    if action == "confirm":
        # Fragment-API.uz orqali haqiqiy xarid
        await call.message.edit_text(f"⏳ #{order_id} Fragment-API.uz orqali yuborilmoqda...")
        from handlers.user import execute_order_via_api
        success, msg = await execute_order_via_api(call.bot, order_id)
        status_text = f"✅ #{order_id} — {msg}" if success else f"⚠️ #{order_id} — {msg}"
        await call.message.edit_text(status_text, parse_mode="HTML")

    elif action == "reject":
        await update_order_status(order_id, "rejected")
        await call.message.edit_text(f"❌ #{order_id} rad etildi.")
        try:
            from database import get_user
            user = await get_user(order["user_id"])
            lang = user["language"] if user else "uz"
            await call.bot.send_message(
                order["user_id"],
                t("user_order_rejected", lang, id=order_id)
            )
        except Exception:
            pass


# ── Broadcast ──────────────────────────────────────────────────────────────────

@admin_router.callback_query(F.data == "admin:broadcast")
async def cb_admin_broadcast(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return
    await state.set_state(AdminStates.broadcast_message)
    b = InlineKeyboardBuilder()
    b.button(text="❌ Bekor", callback_data="admin:menu")
    await call.message.edit_text(t("broadcast_prompt", "en"), reply_markup=b.as_markup())


@admin_router.message(AdminStates.broadcast_message)
async def msg_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.clear()
    users = await get_all_users()
    count = 0
    for u in users:
        try:
            await message.bot.send_message(u["user_id"], message.text)
            count += 1
        except Exception:
            pass
    await message.answer(t("broadcast_done", "en", count=count))


# ── Xabarni o'chirish ──────────────────────────────────────────────────────────

@admin_router.callback_query(F.data == "admin_delete_msg")
async def cb_admin_delete_msg(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    try:
        await call.message.delete()
    except Exception:
        await call.answer("O'chirib bo'lmadi", show_alert=True)
