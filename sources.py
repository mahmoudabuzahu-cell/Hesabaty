import asyncio
import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

logging.basicConfig(level=(os.getenv("LOG_LEVEL") or "INFO").upper())
logger = logging.getLogger(__name__)

BASE = Path(__file__).resolve().parent
DATA_FILE = BASE / "config" / "data.json"
RULES_FILE = BASE / "config" / "rules.json"
PRICES_FILE = BASE / "config" / "market_prices.json"
EGX_FILE = BASE / "config" / "egx_data.json"
INFLATION_DATA_FILE = BASE / "config" / "inflation_data.json"
HISTORY_FILE = BASE / "config" / "price_history.json"
FUEL_FILE = BASE / "config" / "fuel_prices.json"

CBE_URLS = {
    "policy_rates": "https://www.cbe.org.eg/en/economic-research/statistics/overnight-deposit-and-lending-rate",
    "inflation": "https://www.cbe.org.eg/en/economic-research/statistics/inflation-rates",
    "exchange_rates": "https://www.cbe.org.eg/en/economic-research/statistics/cbe-exchange-rates",
}

# مصدر مجاني بدون مفتاح، يحدَّث كل ساعة، ويغطي العملات والمعادن الثمينة معاً.
# ملحوظة مهمة: القيم المرجعة هي "كمية العملة الأخرى مقابل 1 دولار" (base=USD)،
# لذلك سعر الذهب/الفضة بالدولار = 1 / rates["XAU"] وليس rates["XAU"] نفسها،
# وسعر العملة بالجنيه = rates["EGP"] / rates[العملة] وليس ضرباً مباشراً.
FX_API_URL = "https://api.exchangerate.fun/latest"
OANOR_API_KEY = os.getenv("OANOR_API_KEY", "").strip()
OANOR_BASE_URL = "https://api.oanor.com/v1"

HEADERS = {"User-Agent": "EgyptFinanceCalculator/1.0 (+data-monitoring)"}
MAX_RETRIES = 3
RETRY_BACKOFF = 2
TROY_OUNCE_GRAMS = Decimal("31.1034768")

# حدود منطقية لرفض أي رقم غريب يصل من مصدر خارجي بدل عرضه للمستخدم
SANITY_BOUNDS = {
    "usd_egp": (Decimal("10"), Decimal("200")),
    "gold_ounce_usd": (Decimal("300"), Decimal("20000")),
    "silver_ounce_usd": (Decimal("5"), Decimal("500")),
}

CURRENCIES = {
    "USD": "دولار أمريكي",
    "EUR": "يورو",
    "SAR": "ريال سعودي",
    "AED": "درهم إماراتي",
    "KWD": "دينار كويتي",
}


class DataSourceError(Exception):
    pass


# ---------------------------------------------------------------------------
# أدوات ملفات عامة
# ---------------------------------------------------------------------------
# بعض منصات الاستضافة السيرفرليس (زي Vercel) بتديك نظام ملفات للقراءة فقط،
# وبتسمح بالكتابة في /tmp بس (ومحتواها مؤقت وبيتصفّر بين الـ cold starts).
# الدالتين دول بيكتشفوا الحالة دي مرة واحدة، وبيحوّلوا أي كتابة لمسار مرآة
# تحت /tmp تلقائياً بدل ما يفشلوا بصمت أو يطلعوا PermissionError. على أي
# استضافة عادية (محلي، أو سيرفر دائم)، السلوك زي ما هو تماماً من غير تغيير.
_WRITABLE_CONFIG_DIR: Optional[Path] = None


def _writable_config_dir() -> Path:
    global _WRITABLE_CONFIG_DIR
    if _WRITABLE_CONFIG_DIR is not None:
        return _WRITABLE_CONFIG_DIR
    original = BASE / "config"
    probe = original / ".write_test"
    try:
        original.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        _WRITABLE_CONFIG_DIR = original
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "hasabaty_config"
        fallback.mkdir(parents=True, exist_ok=True)
        _WRITABLE_CONFIG_DIR = fallback
        logger.warning(
            "مجلد config/ غير قابل للكتابة (على الأرجح استضافة سيرفرليس زي Vercel) — "
            "التحديثات هتتخزن مؤقتاً في %s بدل كده.",
            fallback,
        )
    return _WRITABLE_CONFIG_DIR


def _mirrored_path(path: Path) -> Path:
    writable_dir = _writable_config_dir()
    if writable_dir == path.parent:
        return path
    return writable_dir / path.name


def atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path = _mirrored_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp_path, path)


def load_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    # لو موجودة نسخة أحدث اتكتبت في مسار /tmp البديل (بعد تحديث ناجح سابق)
    # في نفس الـ instance، فضّلها على النسخة الأصلية المجمّدة في الحزمة.
    mirrored = _mirrored_path(path)
    if mirrored != path and mirrored.exists():
        path = mirrored
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load {path}: {e}")
        return default


def load_data() -> Dict[str, Any]:
    return load_json(DATA_FILE, {"updated_at": None, "sources": {}, "cbe": {}})


def load_fuel_prices() -> Dict[str, Any]:
    """أسعار المنتجات البترولية قرار حكومي دوري، وليست بيانات سوق لحظية.

    تُقرأ من ملف مُحدَّث يدوياً (config/fuel_prices.json) بدل تضمينها كأرقام
    ثابتة داخل الكود، حتى يسهل تحديثها عند صدور قرار تسعير جديد مع توثيق
    المصدر وتاريخ السريان — بنفس فلسفة rules.json و bank_certificates.json.
    """
    return load_json(
        FUEL_FILE,
        {
            "effective_from": None,
            "checked_at": None,
            "source": None,
            "source_url": None,
            "note": "لم يتم إعداد ملف أسعار الوقود بعد.",
            "prices": {},
        },
    )


def get_salary_rules(year: int) -> Optional[Dict[str, Any]]:
    rules = load_json(RULES_FILE, {"salary_rules": []})
    for item in rules.get("salary_rules", []):
        if item.get("year") == year and item.get("verified", False):
            return item
    return None


async def fetch_text_with_retry(url: str, retries: int = MAX_RETRIES, params: Optional[Dict] = None) -> str:
    last_exc = None
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=HEADERS) as client:
        for attempt in range(1, retries + 1):
            try:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response.text
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                last_exc = e
                if attempt < retries:
                    await asyncio.sleep(RETRY_BACKOFF**attempt)
    raise DataSourceError(f"Failed to fetch {url} after {retries} attempts: {last_exc}")


# ---------------------------------------------------------------------------
# بيانات البنك المركزي (سياسة نقدية / تضخم / أسعار صرف رسمية)
# ---------------------------------------------------------------------------
def extract_percent_multi(text: str, labels: List[str], fallback_pattern: Optional[str] = None) -> Optional[float]:
    for label in labels:
        pattern = re.compile(rf"{re.escape(label)}.*?(\d+(?:\.\d+)?)\s*%", re.I | re.S)
        match = pattern.search(text)
        if match:
            return float(match.group(1))
    if fallback_pattern:
        match = re.search(fallback_pattern, text, re.I | re.S)
        if match:
            return float(match.group(1))
    return None


def parse_exchange_table(html: str) -> List[Dict[str, Any]]:
    try:
        soup = BeautifulSoup(html, "html.parser")
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            if "currency" in headers and ("buy" in headers or "sell" in headers):
                idx_currency = headers.index("currency")
                idx_buy = headers.index("buy") if "buy" in headers else None
                idx_sell = headers.index("sell") if "sell" in headers else None
                rows = []
                for tr in table.find_all("tr")[1:]:
                    cells = [td.get_text(strip=True) for td in tr.find_all("td")]
                    if len(cells) <= idx_currency:
                        continue
                    currency = cells[idx_currency]
                    buy = sell = None
                    if idx_buy and idx_buy < len(cells):
                        try:
                            buy = float(cells[idx_buy].replace(",", ""))
                        except ValueError:
                            buy = None
                    if idx_sell and idx_sell < len(cells):
                        try:
                            sell = float(cells[idx_sell].replace(",", ""))
                        except ValueError:
                            sell = None
                    rows.append({"currency": currency, "buy": buy, "sell": sell})
                return rows
    except Exception as e:
        logger.error(f"Parsing error: {e}")
    return []


async def fetch_policy_rates() -> Tuple[Optional[float], Optional[float], Optional[str]]:
    try:
        html = await fetch_text_with_retry(CBE_URLS["policy_rates"])
        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        deposit = extract_percent_multi(text, ["Overnight Deposit Rate", "Deposit Rate", "Overnight Deposit"])
        lending = extract_percent_multi(text, ["Overnight Lending Rate", "Lending Rate", "Overnight Lending"])
        return deposit, lending, None
    except Exception as e:
        return None, None, str(e)


async def fetch_inflation() -> Tuple[Optional[float], Optional[float], Optional[str]]:
    try:
        html = await fetch_text_with_retry(CBE_URLS["inflation"])
        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        headline = extract_percent_multi(text, ["Headline (y/y)", "Headline Inflation", "Headline"])
        core = extract_percent_multi(text, ["Core (y/y)", "Core Inflation", "Core"])
        return headline, core, None
    except Exception as e:
        return None, None, str(e)


async def fetch_exchange_rates() -> Tuple[List[Dict[str, Any]], Optional[str]]:
    try:
        html = await fetch_text_with_retry(CBE_URLS["exchange_rates"])
        return parse_exchange_table(html), None
    except Exception as e:
        return [], str(e)


async def update_cbe_data() -> Dict[str, Any]:
    data = await asyncio.to_thread(load_data)
    old_cbe = data.get("cbe", {})
    new_cbe = {"source_urls": CBE_URLS, "fetched_at": datetime.now(timezone.utc).isoformat(), "errors": {}}
    changed_fields = []

    (deposit, lending, policy_err), (headline, core, inflation_err), (fx_rows, fx_err) = await asyncio.gather(
        fetch_policy_rates(), fetch_inflation(), fetch_exchange_rates()
    )

    if policy_err:
        new_cbe["errors"]["policy_rates"] = policy_err
    if inflation_err:
        new_cbe["errors"]["inflation"] = inflation_err
    if fx_err:
        new_cbe["errors"]["exchange_rates"] = fx_err

    policy_rates = {"overnight_deposit": deposit, "overnight_lending": lending}
    inflation = {"headline_yoy": headline, "core_yoy": core}

    if old_cbe.get("policy_rates") != policy_rates:
        changed_fields.append("policy_rates")
    if old_cbe.get("inflation") != inflation:
        changed_fields.append("inflation")
    if old_cbe.get("exchange_rates") != fx_rows:
        changed_fields.append("exchange_rates")

    new_cbe.update({"policy_rates": policy_rates, "inflation": inflation, "exchange_rates": fx_rows})
    data["cbe"] = new_cbe
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    data["sources"]["cbe"] = {"name": "البنك المركزي المصري", "official": True, "urls": CBE_URLS}

    await asyncio.to_thread(atomic_write_json, DATA_FILE, data)
    return {"ok": True, "changed_fields": changed_fields, "errors": new_cbe.get("errors", {})}


# ---------------------------------------------------------------------------
# العملات والمعادن الثمينة
# ---------------------------------------------------------------------------
def _in_bounds(value: Decimal, key: str) -> bool:
    low, high = SANITY_BOUNDS[key]
    return low <= value <= high


def _spread(mid: Decimal, spread_pct: Decimal = Decimal("0.5")) -> Tuple[Decimal, Decimal]:
    """يُنتج سعري شراء/بيع تقديريين حول السعر المتوسط (spread_pct% إجمالاً)."""
    half = mid * spread_pct / Decimal("100") / Decimal("2")
    return round(mid - half, 2), round(mid + half, 2)


async def append_price_history(snapshot: Dict[str, Any], max_entries: int = 400) -> None:
    history = await asyncio.to_thread(load_json, HISTORY_FILE, {"entries": []})
    entries = history.get("entries", [])
    entries.append(snapshot)
    if len(entries) > max_entries:
        entries = entries[-max_entries:]
    history["entries"] = entries
    await asyncio.to_thread(atomic_write_json, HISTORY_FILE, history)


def get_price_history(days: int = 30) -> List[Dict[str, Any]]:
    history = load_json(HISTORY_FILE, {"entries": []})
    entries = history.get("entries", [])
    return entries[-days:]


async def update_market_prices() -> Dict[str, Any]:
    previous = await asyncio.to_thread(load_json, PRICES_FILE, {})

    try:
        async with httpx.AsyncClient(timeout=15, headers=HEADERS) as client:
            response = await client.get(FX_API_URL, params={"base": "USD"})
            response.raise_for_status()
            payload = response.json()
        rates = payload["rates"]

        usd_egp_mid = Decimal(str(rates["EGP"]))
        if not _in_bounds(usd_egp_mid, "usd_egp"):
            raise DataSourceError(f"سعر الدولار خارج الحدود المنطقية: {usd_egp_mid}")

        gold_ounce_usd = Decimal("1") / Decimal(str(rates["XAU"]))
        silver_ounce_usd = Decimal("1") / Decimal(str(rates["XAG"]))
        if not _in_bounds(gold_ounce_usd, "gold_ounce_usd") or not _in_bounds(silver_ounce_usd, "silver_ounce_usd"):
            raise DataSourceError("أسعار المعادن الثمينة خارج الحدود المنطقية")

        currency_rows = {}
        for code, name in CURRENCIES.items():
            if code == "USD":
                mid = usd_egp_mid
            else:
                mid = usd_egp_mid / Decimal(str(rates[code]))
            buy, sell = _spread(mid)
            currency_rows[code] = {"name": name, "buy": float(buy), "sell": float(sell), "mid": float(round(mid, 4))}

        gold_gram_24k = (gold_ounce_usd / TROY_OUNCE_GRAMS) * usd_egp_mid
        silver_gram = (silver_ounce_usd / TROY_OUNCE_GRAMS) * usd_egp_mid

        new_prices = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "status": "live",
            "source_url": "https://github.com/haxqer/FreeExchangeRateApi",
            "currency": currency_rows,
            "gold": {
                "ounce_usd": float(round(gold_ounce_usd, 2)),
                "24k": float(round(gold_gram_24k, 2)),
                "21k": float(round(gold_gram_24k * Decimal("0.875"), 2)),
                "18k": float(round(gold_gram_24k * Decimal("0.75"), 2)),
                "pound_21k": float(round(gold_gram_24k * Decimal("0.875") * Decimal("8"), 2)),
            },
            "silver": {"999": float(round(silver_gram, 2))},
        }

        await asyncio.to_thread(atomic_write_json, PRICES_FILE, new_prices)
        await append_price_history(
            {
                "date": new_prices["last_updated"],
                "usd_egp": currency_rows["USD"]["mid"],
                "eur_egp": currency_rows["EUR"]["mid"],
                "gold_21k": new_prices["gold"]["21k"],
                "silver": new_prices["silver"]["999"],
            }
        )
        return {"ok": True, "message": "تم تحديث أسعار العملات والمعادن بنجاح"}

    except Exception as e:
        logger.error(f"Failed to update market prices, keeping last known values: {e}")
        if previous:
            previous["status"] = "stale"
            previous["error"] = str(e)
            await asyncio.to_thread(atomic_write_json, PRICES_FILE, previous)
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# البورصة المصرية (EGX)
# ---------------------------------------------------------------------------
async def _fetch_egx_from_oanor() -> Optional[Dict[str, Any]]:
    if not OANOR_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=15, headers={**HEADERS, "Authorization": f"Bearer {OANOR_API_KEY}"}) as client:
            index_resp = await client.get(f"{OANOR_BASE_URL}/indices", params={"symbols": "EGX30,EGX70,EGX100"})
            index_resp.raise_for_status()
            movers_resp = await client.get(f"{OANOR_BASE_URL}/screener", params={"type": "gainers,losers,most_active", "limit": 5})
            movers_resp.raise_for_status()

        indices_payload = index_resp.json()
        movers_payload = movers_resp.json()

        indices = {}
        for row in indices_payload.get("data", []):
            symbol = row.get("symbol", "").replace("^", "")
            indices[symbol] = {"value": row.get("last") or row.get("close"), "change": row.get("change_percent")}

        return {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "status": "live",
            "provider": "oanor.com",
            "indices": indices,
            "top_gainers": movers_payload.get("gainers", [])[:5],
            "top_losers": movers_payload.get("losers", [])[:5],
            "most_active": movers_payload.get("most_active", [])[:5],
        }
    except Exception as e:
        logger.warning(f"oanor.com EGX fetch failed: {e}")
        return None


async def _fetch_egx30_from_yfinance() -> Optional[Dict[str, Any]]:
    try:
        import yfinance as yf

        history = await asyncio.to_thread(yf.Ticker("^CASE30").history, period="5d")
        if history.empty or len(history) < 2:
            return None
        val = float(history["Close"].iloc[-1])
        prev = float(history["Close"].iloc[-2])
        change = round(((val - prev) / prev) * 100, 2) if prev else 0.0
        return {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "status": "live",
            "provider": "yfinance (EGX30 فقط، بدون بيانات الأعلى ارتفاعاً/انخفاضاً)",
            "indices": {"EGX30": {"value": round(val, 2), "change": change}},
            "top_gainers": [],
            "top_losers": [],
            "most_active": [],
        }
    except Exception as e:
        logger.warning(f"yfinance EGX30 fallback failed: {e}")
        return None


async def fetch_egx_data() -> Dict[str, Any]:
    result = await _fetch_egx_from_oanor()
    if result:
        await asyncio.to_thread(atomic_write_json, EGX_FILE, result)
        return result

    result = await _fetch_egx30_from_yfinance()
    if result:
        await asyncio.to_thread(atomic_write_json, EGX_FILE, result)
        return result

    cached = load_json(
        EGX_FILE,
        {"last_updated": None, "status": "unavailable", "indices": {}, "top_gainers": [], "top_losers": [], "most_active": []},
    )
    cached["status"] = "stale" if cached.get("indices") else "unavailable"
    await asyncio.to_thread(atomic_write_json, EGX_FILE, cached)
    return cached


async def fetch_inflation_data() -> float:
    """
    تحاول جلب أحدث نسبة تضخم أساسي في مصر من موقع بنك مصر.
    في حال فشل الاتصال، تعود للقيمة المخزنة في inflation_data.json أو آخر قيمة معروفة من CBE.
    """
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, headers=HEADERS) as client:
            response = await client.get("https://www.banquemisr.com/en/egyptian-economy/rates")
            response.raise_for_status()
            text = response.text
            match = re.search(r"(\d+(?:\.\d+)?)%.*?inflation", text, re.I)
            if match:
                rate = float(match.group(1))
                await asyncio.to_thread(atomic_write_json, INFLATION_DATA_FILE, {"rate": rate, "fetched_at": datetime.now(timezone.utc).isoformat()})
                return rate
    except Exception as e:
        logger.warning(f"Failed to fetch inflation rate, using cached value: {e}")

    cbe_data = load_data()
    cbe_headline = cbe_data.get("cbe", {}).get("inflation", {}).get("headline_yoy")
    if cbe_headline:
        return float(cbe_headline)

    data = load_json(INFLATION_DATA_FILE, {"rate": 13.8})
    return data.get("rate", 13.8)
