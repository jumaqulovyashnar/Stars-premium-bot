from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from locales import t


def language_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🇺🇿 O'zbekcha", callback_data="lang:uz")
    b.button(text="🇬🇧 English",   callback_data="lang:en")
    b.button(text="🇸🇦 العربية",    callback_data="lang:ar")
    b.adjust(3)
    return b.as_markup()


def main_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t("btn_buy_stars",   lang), callback_data="action:buy_stars")
    b.button(text=t("btn_buy_premium", lang), callback_data="action:buy_premium")
    b.button(text=t("btn_my_orders",   lang), callback_data="action:my_orders")
    b.button(text=t("btn_help",        lang), callback_data="action:help")
    b.button(text=t("btn_change_lang", lang), callback_data="action:change_lang")
    b.adjust(2, 2, 1)
    return b.as_markup()


def username_keyboard(lang: str, myself_username: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if myself_username:
        b.button(text=f"👤 {t('btn_for_myself', lang)}", callback_data=f"username:{myself_username}")
    b.button(text=t("btn_back", lang), callback_data="action:main_menu")
    b.adjust(1)
    return b.as_markup()


def currency_keyboard(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💎 TON bilan to'lash",  callback_data="currency:TON")
    b.button(text="💵 USDT bilan to'lash", callback_data="currency:USDT")
    b.button(text=t("btn_back", lang),     callback_data="action:main_menu")
    b.adjust(2, 1)
    return b.as_markup()


def premium_period_keyboard_dynamic(lang: str, calc) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for months, label_uz, label_en in [(3, "3 oy", "3 Months"), (6, "6 oy", "6 Months"), (12, "1 yil", "1 Year")]:
        ton  = calc.premium_price_ton(months)
        usdt = calc.premium_price_usdt(months)
        label = label_uz if lang == "uz" else label_en
        b.button(text=f"💎 {label} — {ton:.2f} TON / {usdt:.2f} USDT", callback_data=f"premium_period:{months}")
    b.button(text=t("btn_back", lang), callback_data="action:main_menu")
    b.adjust(1)
    return b.as_markup()


def invoice_keyboard(lang: str, order_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t("btn_paid",         lang), callback_data=f"paid:{order_id}")
    b.button(text=t("btn_cancel_order", lang), callback_data=f"cancel_order:{order_id}")
    b.adjust(2)
    return b.as_markup()


def admin_menu_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📦 Buyurtmalar", callback_data="admin:orders:pending")
    b.button(text="📊 Statistika",  callback_data="admin:stats")
    b.button(text="👥 Userlar",     callback_data="admin:users")
    b.button(text="📢 Broadcast",   callback_data="admin:broadcast")
    b.button(text="💱 Narxlar",     callback_data="admin:rates")
    b.adjust(2, 2, 1)
    return b.as_markup()


def admin_order_keyboard(order_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Tasdiqlash & Yuborish", callback_data=f"admin_order:confirm:{order_id}")
    b.button(text="❌ Rad etish",             callback_data=f"admin_order:reject:{order_id}")
    b.button(text="◀️ Orqaga",               callback_data="admin:orders:paid")
    b.adjust(2, 1)
    return b.as_markup()


def orders_filter_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⏳ Pending", callback_data="admin:orders:pending")
    b.button(text="✅ Paid",    callback_data="admin:orders:paid")
    b.button(text="📦 Hammasi", callback_data="admin:orders:all")
    b.button(text="◀️ Back",   callback_data="admin:menu")
    b.adjust(3, 1)
    return b.as_markup()
