# ⭐ Telegram Stars & Premium Bot

Telegram Stars va Premium sotib olish boti. Fragment-API.uz orqali real vaqtda ishlaydi.

## Xususiyatlar

- ⭐ Telegram Stars sotib olish
- 💎 Telegram Premium (3, 6, 12 oy)
- 💚 Tonkeeper orqali to'lov
- 🔄 Avtomatik buyurtma bajarish (Fragment API)
- 🌐 3 til: O'zbekcha, English, العربية
- 👑 Admin panel (statistika, buyurtmalar, broadcast)
- ⏰ 30 daqiqalik to'lov muddati
- 🛡 Rate limiting (DDoS himoyasi)

## O'rnatish

1. Reponi klonlash:
```bash
git clone https://github.com/your-username/stars-bot.git
cd stars-bot
```

2. Kutubxonalarni o'rnatish:
```bash
pip install -r requirements.txt
```

3. `.env` faylni sozlash:
```bash
cp .env.example .env
```

`.env` faylni tahrirlang va quyidagilarni kiriting:
- `BOT_TOKEN` — @BotFather dan olingan token
- `ADMIN_IDS` — Admin Telegram ID (vergul bilan bir nechta)
- `FRAGMENT_API_KEY_TON` — Fragment-API.uz dan TON kalit
- `FRAGMENT_API_KEY_USDT` — Fragment-API.uz dan USDT kalit
- `WALLET_ADDRESS` — TON hamyon manzili

4. Botni ishga tushirish:
```bash
python bot.py
```

## Texnologiyalar

- Python 3.11+
- aiogram 3.13
- aiosqlite
- Fragment-API.uz

## Ustamalar

| Mahsulot | Shart | Ustama |
|----------|-------|--------|
| Stars | ≤ 1000 | 5% |
| Stars | > 1000 | 8% |
| Premium 3 oy | — | 5% |
| Premium 6 oy | — | 5% |
| Premium 12 oy | — | 3% |

## Litsenziya

MIT
