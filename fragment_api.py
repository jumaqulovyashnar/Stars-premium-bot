"""
Fragment-API.uz integratsiyasi — real API dokumentatsiyasiga asoslangan.

Base URL: https://fragment-api.uz/api/v1
Header: X-API-Key: <api-key>
Barcha endpointlar POST + JSON body

Ustamalar (bizning foyda):
  Stars <= 1000: +5%
  Stars > 1000: +8%
  Premium 3 oy: +5%
  Premium 6 oy: +5%
  Premium 12 oy: +3%
"""

import aiohttp
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class StarsPricing:
    amount: int
    price_ton: float
    price_usd: float


@dataclass
class PremiumPackage:
    months: int
    price_ton: float
    price_usd: float


@dataclass
class OrderResult:
    success: bool
    order_id: Optional[str] = None
    message: str = ""
    username: str = ""
    amount: int = 0
    payment_method: str = ""
    cost: float = 0.0


class FragmentAPIClient:
    """
    fragment-api.uz real API client.

    Endpointlar:
      POST /v1/stars/pricing   — Stars narxini olish
      POST /v1/premium/pricing — Premium narxlarini olish
      POST /v1/stars/buy       — Stars sotib olish
      POST /v1/premium/buy     — Premium sotib olish
      POST /v1/wallet/balance  — Balans tekshirish
      POST /v1/getInfo         — User ma'lumoti
    """

    BASE_URL = "https://fragment-api.uz/api/v1"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._session: Optional[aiohttp.ClientSession] = None

    def _headers(self) -> dict:
        return {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self._headers())
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Stars Pricing ──────────────────────────────────────────────────────────

    async def get_stars_pricing(self, amount: int) -> StarsPricing:
        """
        POST /v1/stars/pricing
        Body: {"amount": 60}
        Response: {"ok": true, "result": {"amount": 50, "price": {"ton": "0.3151", "usd": "0.75"}}}
        """
        session = await self._get_session()
        async with session.post(
            f"{self.BASE_URL}/stars/pricing",
            json={"amount": amount},
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            data = await resp.json()
            if resp.status == 200 and data.get("ok"):
                result = data["result"]
                return StarsPricing(
                    amount=int(result["amount"]),
                    price_ton=float(result["price"]["ton"]),
                    price_usd=float(result["price"]["usd"]),
                )
            else:
                raise Exception(f"Stars pricing xatosi: {data.get('message', 'Noma`lum xato')}")

    # ── Premium Pricing ────────────────────────────────────────────────────────

    async def get_premium_pricing(self) -> list[PremiumPackage]:
        """
        POST /v1/premium/pricing
        Body: {}
        Response: {"ok": true, "result": {"packages": [{"months": 3, "ton": "5", "usd": "11.99"}, ...]}}
        """
        session = await self._get_session()
        async with session.post(
            f"{self.BASE_URL}/premium/pricing",
            json={},
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            data = await resp.json()
            if resp.status == 200 and data.get("ok"):
                packages = []
                for pkg in data["result"]["packages"]:
                    packages.append(PremiumPackage(
                        months=int(pkg["months"]),
                        price_ton=float(pkg["ton"]),
                        price_usd=float(pkg["usd"]),
                    ))
                return packages
            else:
                raise Exception(f"Premium pricing xatosi: {data.get('message', 'Noma`lum xato')}")

    # ── Stars Buy ─────────────────────────────────────────────────────────────

    async def buy_stars(self, username: str, amount: int) -> OrderResult:
        """
        POST /v1/stars/buy
        Body: {"amount": 60, "username": "durov"}
        Response: {"ok": true, "result": {"username": "durov", "amount": 50, "payment_method": "USDT", "cost": "0.75"}}
        """
        uname = username.lstrip("@")
        try:
            session = await self._get_session()
            payload = {"amount": amount, "username": uname}
            logger.info(f"[Fragment API] stars/buy → {payload}")
            async with session.post(
                f"{self.BASE_URL}/stars/buy",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                data = await resp.json()
                logger.info(f"[Fragment API] stars/buy ← status={resp.status} response={data}")
                if resp.status == 200 and data.get("ok"):
                    result = data["result"]
                    return OrderResult(
                        success=True,
                        message=data.get("message", "OK"),
                        username=result.get("username", uname),
                        amount=int(result.get("amount", amount)),
                        payment_method=result.get("payment_method", ""),
                        cost=float(result.get("cost", 0)),
                    )
                else:
                    logger.warning(f"[Fragment API] stars/buy FAILED: {data}")
                    return OrderResult(
                        success=False,
                        message=data.get("message", "Noma'lum xato")
                    )
        except aiohttp.ClientConnectorError:
            return OrderResult(success=False, message="API serveriga ulanib bo'lmadi")
        except Exception as e:
            logger.error(f"Stars buy xatosi: {e}")
            return OrderResult(success=False, message=str(e))

    # ── Premium Buy ────────────────────────────────────────────────────────────

    async def buy_premium(self, username: str, duration: int) -> OrderResult:
        """
        POST /v1/premium/buy
        Body: {"duration": 12, "username": "durov"}
        Response: {"ok": true, "result": {"username": "durov", "duration": 3, "payment_method": "TON", "cost": "5"}}
        """
        uname = username.lstrip("@")
        try:
            session = await self._get_session()
            async with session.post(
                f"{self.BASE_URL}/premium/buy",
                json={"duration": duration, "username": uname},
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                data = await resp.json()
                if resp.status == 200 and data.get("ok"):
                    result = data["result"]
                    return OrderResult(
                        success=True,
                        message=data.get("message", "OK"),
                        username=result.get("username", uname),
                        amount=int(result.get("duration", duration)),
                        payment_method=result.get("payment_method", ""),
                        cost=float(result.get("cost", 0)),
                    )
                else:
                    return OrderResult(
                        success=False,
                        message=data.get("message", "Noma'lum xato")
                    )
        except aiohttp.ClientConnectorError:
            return OrderResult(success=False, message="API serveriga ulanib bo'lmadi")
        except Exception as e:
            logger.error(f"Premium buy xatosi: {e}")
            return OrderResult(success=False, message=str(e))

    # ── Wallet Balance ─────────────────────────────────────────────────────────

    async def get_balance(self) -> dict:
        """
        POST /v1/wallet/balance
        Body: {}
        Response: {"ok": true, "result": {"balance_ton": "0.24", "balance_usdt": "12.5", ...}}
        """
        try:
            session = await self._get_session()
            async with session.post(
                f"{self.BASE_URL}/wallet/balance",
                json={},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                if resp.status == 200 and data.get("ok"):
                    return data["result"]
        except Exception as e:
            logger.error(f"Balance xatosi: {e}")
        return {"balance_ton": "0", "balance_usdt": "0"}

    # ── Get User Info ──────────────────────────────────────────────────────────

    async def get_user_info(self, username: str) -> dict:
        """
        POST /v1/getInfo
        Body: {"username": "durov"}
        """
        uname = username.lstrip("@")
        try:
            session = await self._get_session()
            async with session.post(
                f"{self.BASE_URL}/getInfo",
                json={"username": uname},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                if resp.status == 200 and data.get("ok"):
                    return data["result"]
        except Exception as e:
            logger.error(f"GetInfo xatosi: {e}")
        return {}


# ── Narx hisoblash (ustama qo'shish) ──────────────────────────────────────────

class PriceCalculator:
    """
    API dan olingan real narxga ustama qo'shadi:
      - Stars <= 1000: +5%
      - Stars > 1000: +8%
      - Premium 3 oy: +5%
      - Premium 6 oy: +5%
      - Premium 12 oy: +3%
    """

    @staticmethod
    def stars_markup(amount: int) -> float:
        """Stars uchun ustama foizi."""
        if amount <= 1000:
            return 0.05
        return 0.08

    @staticmethod
    def premium_markup(months: int) -> float:
        """Premium uchun ustama foizi."""
        if months == 12:
            return 0.03
        return 0.05

    @staticmethod
    def calc_stars_price(pricing: StarsPricing) -> tuple[float, float]:
        """
        API dan olingan narxga ustama qo'shib (ton, usd) qaytaradi.
        """
        markup = PriceCalculator.stars_markup(pricing.amount)
        ton = round(pricing.price_ton * (1 + markup), 4)
        usd = round(pricing.price_usd * (1 + markup), 2)
        return ton, usd

    @staticmethod
    def calc_premium_price(package: PremiumPackage) -> tuple[float, float]:
        """
        API dan olingan narxga ustama qo'shib (ton, usd) qaytaradi.
        """
        markup = PriceCalculator.premium_markup(package.months)
        ton = round(package.price_ton * (1 + markup), 4)
        usd = round(package.price_usd * (1 + markup), 2)
        return ton, usd
