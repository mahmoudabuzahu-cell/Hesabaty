"""FastAPI entry point for حساباتى - Egypt Finance Calculators."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal, Optional

from dotenv import load_dotenv

# لازم تتنفذ قبل استيراد أي موديول محلي بيقرأ متغيرات بيئة.
load_dotenv()

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from calculators import (
    LOAN_PRESETS,
    budget_planner,
    certificate_calculator,
    certificate_early_redemption,
    certificates_meta,
    compare_certificates,
    compare_investment_vehicles,
    compare_savings_accounts,
    credit_card_balance_cost,
    credit_cards_meta,
    debt_burden_check,
    end_of_service_calculator,
    inflation_calculator,
    investment_reinvestment_income,
    load_bank_certificates,
    load_credit_cards,
    load_savings_accounts,
    loan_calculator,
    loan_early_settlement,
    money_plan_scenarios,
    recommend_credit_cards,
    salary_calculator,
    savings_accounts_meta,
    savings_calculator,
    zakat_calculator_full,
)
from sources import (
    DataSourceError,
    EGX_FILE,
    INFLATION_DATA_FILE,
    PRICES_FILE,
    fetch_egx_data,
    fetch_inflation_data,
    get_price_history,
    load_data,
    load_fuel_prices,
    load_json,
    update_cbe_data,
    update_market_prices,
)

logging.basicConfig(level=(os.getenv("LOG_LEVEL") or "INFO").upper())
logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent

# ملحوظة: بنستخدم `os.getenv(X) or default` مش `os.getenv(X, default)` هنا.
# لو المنصة (زي Vercel) عرّفت المتغيّر بس سايباه فاضي، os.getenv بيرجّع ''
# مش القيمة الافتراضية، و int('') كان بيطلّع ValueError ويكسر كل الموقع.
SITE_URL = (os.getenv("SITE_URL") or "https://hasabaty.example.com").rstrip("/")
MARKET_UPDATE_INTERVAL = int(os.getenv("MARKET_UPDATE_INTERVAL_SECONDS") or "3600")
EGX_UPDATE_INTERVAL = int(os.getenv("EGX_UPDATE_INTERVAL_SECONDS") or "900")
CBE_UPDATE_INTERVAL = int(os.getenv("CBE_UPDATE_INTERVAL_SECONDS") or str(6 * 3600))
INFLATION_UPDATE_INTERVAL = int(os.getenv("INFLATION_UPDATE_INTERVAL_SECONDS") or str(24 * 3600))
# لو شغّال على سيرفر دائم (مش سيرفرليس زي Vercel) وعايز الحلقات القديمة اللي
# بتحدّث البيانات في الخلفية باستمرار (بدل التحديث عند الطلب بس)، فعّلها بمتغيّر
# ENABLE_BACKGROUND_LOOPS=true في .env. من غيره التحديث بيحصل عند الطلب فقط.
ENABLE_BACKGROUND_LOOPS = (os.getenv("ENABLE_BACKGROUND_LOOPS") or "false").strip().lower() == "true"
# أقل مدة بين محاولتين لإعادة التحديث لو آخر محاولة فشلت (عشان لو المصدر
# الخارجي واقع، مش كل طلب هيستنى مهلة الاتصال كاملة لحد ما يرجع يشتغل).
REFRESH_RETRY_COOLDOWN_SECONDS = 60

# ---------------------------------------------------------------------------
# إعدادات جوجل أدسنس
# ---------------------------------------------------------------------------
# رقم الناشر بتاعك من AdSense، أرقام فقط من غير أي بادئة (لاقيه في:
# حساب > إعدادات > معلومات الحساب، شكله عادةً 16 رقم). سيبه فاضي لحد ما يتوفر.
ADSENSE_PUBLISHER_ID = os.getenv("ADSENSE_PUBLISHER_ID", "").strip()
# صيغة "ca-pub-..." المطلوبة لكود الإعلانات وميتا تاج التحقق من الملكية.
ADSENSE_CLIENT = f"ca-pub-{ADSENSE_PUBLISHER_ID}" if ADSENSE_PUBLISHER_ID else ""
# بريد التواصل الظاهر في صفحتي "تواصل معنا" و"سياسة الخصوصية".
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "").strip()

PositiveAmount = Annotated[FiniteFloat, Field(gt=0, description="Amount in EGP")]
NonNegativeAmount = Annotated[FiniteFloat, Field(ge=0, description="Amount in EGP")]
AnnualRate = Annotated[FiniteFloat, Field(ge=0, le=100, description="Annual percentage rate; 18 means 18%")]
YearsField = Annotated[int, Field(gt=0, le=50)]


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoanInput(APIModel):
    principal: PositiveAmount
    annual_rate: AnnualRate
    years: YearsField
    admin_fee_percent: Annotated[FiniteFloat, Field(ge=0, le=10)] = 0


class DebtBurdenInput(APIModel):
    monthly_installment: NonNegativeAmount
    monthly_net_income: PositiveAmount
    existing_monthly_debts: NonNegativeAmount = 0


class CertificateInput(APIModel):
    principal: PositiveAmount
    annual_rate: AnnualRate
    years: YearsField
    payout: Literal["monthly", "quarterly", "yearly", "maturity"] = "monthly"


class SavingsInput(APIModel):
    initial: NonNegativeAmount
    monthly_contribution: NonNegativeAmount
    annual_rate: AnnualRate
    years: Annotated[int, Field(gt=0, le=100)]


class InflationInput(APIModel):
    amount: PositiveAmount
    annual_inflation: AnnualRate
    years: Annotated[int, Field(gt=0, le=100)]


class SalaryInput(APIModel):
    net_monthly: PositiveAmount
    year: Optional[Annotated[int, Field(ge=2020, le=2035)]] = None


class CompareCertificatesInput(APIModel):
    money: PositiveAmount
    term_years: Annotated[int, Field(gt=0, le=10)]
    bank: Optional[str] = None


class CompareSavingsInput(APIModel):
    money: PositiveAmount
    years: Annotated[int, Field(gt=0, le=10)]
    bank: Optional[str] = None


class ZakatInput(APIModel):
    cash_egp: NonNegativeAmount = 0
    gold_grams_21k: NonNegativeAmount = 0
    gold_grams_18k: NonNegativeAmount = 0
    gold_grams_24k: NonNegativeAmount = 0
    worn_gold_grams_21k: NonNegativeAmount = 0
    worn_gold_grams_18k: NonNegativeAmount = 0
    worn_gold_grams_24k: NonNegativeAmount = 0
    exclude_worn_gold: bool = False
    silver_grams: NonNegativeAmount = 0
    stocks_value: NonNegativeAmount = 0
    receivables: NonNegativeAmount = 0
    debts: NonNegativeAmount = 0
    nisab_basis: Literal["gold", "silver"] = "gold"
    hawl_passed: bool = True
    override_gold_price_21k: Optional[PositiveAmount] = None
    override_silver_price: Optional[PositiveAmount] = None


class EndOfServiceInput(APIModel):
    salary: PositiveAmount
    uncovered_years: Annotated[int, Field(ge=0, le=50)]


class MoneyPlanInput(APIModel):
    amount: PositiveAmount
    liquidity_need: Literal["full", "partial", "none"]
    needs_income: bool
    duration_years: Annotated[int, Field(gt=0, le=10)]


class CreditCardRecommendInput(APIModel):
    monthly_income: PositiveAmount
    primary_need: Literal["عام", "سفر", "كاش باك"]


class CreditCardBalanceCostInput(APIModel):
    balance: PositiveAmount
    monthly_interest_rate_percent: Annotated[FiniteFloat, Field(gt=0, le=15)] = 4.0
    min_payment_percent: Annotated[FiniteFloat, Field(gt=0, le=100)] = 5.0
    min_payment_floor: NonNegativeAmount = 100


class BudgetPlannerInput(APIModel):
    monthly_net_income: PositiveAmount
    fixed_obligations: NonNegativeAmount = 0


class CompareInvestmentsInput(APIModel):
    amount: PositiveAmount
    duration_years: Annotated[int, Field(gt=0, le=10)] = 1


class EarlySettlementInput(LoanInput):
    months_paid: Annotated[int, Field(gt=0, le=600)]
    penalty_percent: Annotated[FiniteFloat, Field(ge=0, le=20)] = 2.0


class CertificateRedemptionInput(CertificateInput):
    months_held: Annotated[int, Field(gt=0, le=600)]


limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not ENABLE_BACKGROUND_LOOPS:
        # الوضع الافتراضي: التحديث بيحصل عند الطلب (راجع _refresh_if_stale)،
        # مش بحلقة دائمة في الخلفية. ده أساسي على استضافة سيرفرليس زي Vercel
        # لأنها أصلاً مش بتشغّل lifespan بشكل موثوق فيه.
        logger.info("Background updaters disabled — using on-demand refresh instead")
        yield
        return

    async def market_loop():
        while True:
            try:
                await update_market_prices()
            except Exception:
                logger.exception("Market price update loop failed")
            await asyncio.sleep(MARKET_UPDATE_INTERVAL)

    async def egx_loop():
        while True:
            try:
                await fetch_egx_data()
            except Exception:
                logger.exception("EGX update loop failed")
            await asyncio.sleep(EGX_UPDATE_INTERVAL)

    async def cbe_loop():
        while True:
            try:
                await update_cbe_data()
            except Exception:
                logger.exception("CBE update loop failed")
            await asyncio.sleep(CBE_UPDATE_INTERVAL)

    async def inflation_loop():
        while True:
            try:
                await fetch_inflation_data()
            except Exception:
                logger.exception("Inflation update loop failed")
            await asyncio.sleep(INFLATION_UPDATE_INTERVAL)

    tasks = [
        asyncio.create_task(market_loop()),
        asyncio.create_task(egx_loop()),
        asyncio.create_task(cbe_loop()),
        asyncio.create_task(inflation_loop()),
    ]
    logger.info(
        "Background updaters started (market every %ss, EGX every %ss, CBE every %ss)",
        MARKET_UPDATE_INTERVAL,
        EGX_UPDATE_INTERVAL,
        CBE_UPDATE_INTERVAL,
    )
    yield
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(
    title="حساباتى",
    version="2.0.0",
    description="نظام محاسبي متكامل للحسابات المالية المصرية.",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

allowed_origins = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "").split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_methods=["GET", "POST"], allow_headers=["*"])

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals["site_url"] = SITE_URL
templates.env.globals["adsense_client"] = ADSENSE_CLIENT
templates.env.globals["contact_email"] = CONTACT_EMAIL or "[email protected]"


def require_admin_token(x_admin_token: Annotated[str | None, Header()] = None) -> None:
    expected_token = os.getenv("ADMIN_TOKEN")
    if not expected_token:
        logger.error("ADMIN_TOKEN is not configured")
        raise HTTPException(status_code=503, detail="Administrative updates are not configured.")
    if x_admin_token is None or not secrets.compare_digest(x_admin_token, expected_token):
        raise HTTPException(status_code=401, detail="Invalid or missing admin token.", headers={"WWW-Authenticate": "AdminToken"})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "حدث خطأ غير متوقع. برجاء المحاولة مرة أخرى."})


# ---------------------------------------------------------------------------
# صفحات الموقع
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# التحديث عند الطلب (بديل الحلقات الدائمة، وشغال على أي استضافة)
# ---------------------------------------------------------------------------
_refresh_locks = {"market": asyncio.Lock(), "egx": asyncio.Lock(), "cbe": asyncio.Lock(), "inflation": asyncio.Lock()}
_last_refresh_attempt: dict[str, float] = {}


def _is_stale(iso_timestamp: Optional[str], interval_seconds: int) -> bool:
    if not iso_timestamp:
        return True
    try:
        updated = datetime.fromisoformat(iso_timestamp)
    except ValueError:
        return True
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - updated).total_seconds() > interval_seconds


async def _refresh_if_stale(key: str, loader, updater, timestamp_field: str, interval_seconds: int):
    """يحمّل البيانات المخزّنة، ولو قديمة على الفترة المحددة بيحدّثها فورًا قبل
    ما يرجعها، بدل ما تعتمد على حلقة خلفية دايمة الشغل (اللي مش متاحة أصلاً على
    استضافة سيرفرليس زي Vercel). لو طلب تاني بيحدّث نفس المصدر دلوقتي، أو لو
    آخر محاولة فشلت من أقل من دقيقة، بنرجّع آخر بيانات مخزنة على طول من غير
    ما نخلي الزائر يستنى مرتين على نفس المصدر الواقع."""
    data = await asyncio.to_thread(loader)
    if not _is_stale(data.get(timestamp_field), interval_seconds):
        return data

    lock = _refresh_locks[key]
    if lock.locked():
        return data

    now = time.monotonic()
    if now - _last_refresh_attempt.get(key, 0) < REFRESH_RETRY_COOLDOWN_SECONDS:
        return data

    async with lock:
        data = await asyncio.to_thread(loader)  # ممكن طلب تاني يكون حدّثها وإحنا مستنيين القفل
        if not _is_stale(data.get(timestamp_field), interval_seconds):
            return data
        _last_refresh_attempt[key] = time.monotonic()
        try:
            await updater()
        except Exception:
            logger.exception("On-demand refresh failed for %s, serving cached data", key)
        return await asyncio.to_thread(loader)


async def _market_snapshot():
    prices, egx = await asyncio.gather(
        _refresh_if_stale(
            "market",
            lambda: load_json(PRICES_FILE, {"status": "unavailable", "currency": {}, "gold": {}, "silver": {}}),
            update_market_prices,
            "last_updated",
            MARKET_UPDATE_INTERVAL,
        ),
        _refresh_if_stale(
            "egx",
            lambda: load_json(
                EGX_FILE,
                {"status": "unavailable", "indices": {}, "top_gainers": [], "top_losers": [], "most_active": []},
            ),
            fetch_egx_data,
            "last_updated",
            EGX_UPDATE_INTERVAL,
        ),
    )
    return prices, egx


@app.get("/", include_in_schema=False)
async def home(request: Request):
    prices, egx = await _market_snapshot()
    return templates.TemplateResponse(request=request, name="home.html", context={"prices": prices, "egx": egx})


@app.get("/about", include_in_schema=False)
def about_page(request: Request):
    return templates.TemplateResponse(request=request, name="about.html")


@app.get("/faq", include_in_schema=False)
def faq_page(request: Request):
    return templates.TemplateResponse(request=request, name="faq.html")


@app.get("/privacy", include_in_schema=False)
def privacy_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="privacy.html",
        context={"updated_date": datetime.now().strftime("%Y-%m-%d")},
    )


@app.get("/terms", include_in_schema=False)
def terms_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="terms.html",
        context={"updated_date": datetime.now().strftime("%Y-%m-%d")},
    )


@app.get("/contact", include_in_schema=False)
def contact_page(request: Request):
    return templates.TemplateResponse(request=request, name="contact.html")


@app.get("/loan", include_in_schema=False)
def loan_page(request: Request):
    return templates.TemplateResponse(request=request, name="loan.html", context={"presets": LOAN_PRESETS})


@app.get("/savings", include_in_schema=False)
def savings_page(request: Request):
    meta = savings_accounts_meta()
    accounts = load_savings_accounts().get("accounts", [])
    return templates.TemplateResponse(request=request, name="savings.html", context={"meta": meta, "accounts_json": json.dumps(accounts, ensure_ascii=False)})


@app.get("/inflation", include_in_schema=False)
async def inflation_page(request: Request):
    inflation_data = await _refresh_if_stale(
        "inflation",
        lambda: load_json(INFLATION_DATA_FILE, {"rate": 13.8, "fetched_at": None}),
        fetch_inflation_data,
        "fetched_at",
        INFLATION_UPDATE_INTERVAL,
    )
    default_rate = inflation_data.get("rate", 13.8)
    return templates.TemplateResponse(request=request, name="inflation.html", context={"default_rate": default_rate})


@app.get("/certificate", include_in_schema=False)
def certificate_page(request: Request):
    meta = certificates_meta()
    certs = load_bank_certificates().get("certificates", [])
    return templates.TemplateResponse(request=request, name="certificate.html", context={"meta": meta, "certificates_json": json.dumps(certs, ensure_ascii=False)})


@app.get("/salary", include_in_schema=False)
def salary_page(request: Request):
    return templates.TemplateResponse(request=request, name="salary.html", context={"year": datetime.now().year})


@app.get("/zakat", include_in_schema=False)
async def zakat_page(request: Request):
    prices, _ = await _market_snapshot()
    return templates.TemplateResponse(request=request, name="zakat.html", context={"prices": prices})


@app.get("/end-of-service", include_in_schema=False)
def end_of_service_page(request: Request):
    return templates.TemplateResponse(request=request, name="end_of_service.html")


@app.get("/market", include_in_schema=False)
async def market_page(request: Request):
    prices, egx = await _market_snapshot()
    history = get_price_history(30)
    fuel = load_fuel_prices()
    return templates.TemplateResponse(
        request=request,
        name="market.html",
        context={"prices": prices, "egx": egx, "fuel": fuel, "history_json": json.dumps(history, ensure_ascii=False)},
    )


@app.get("/money-plan", include_in_schema=False)
def money_plan_page(request: Request):
    return templates.TemplateResponse(request=request, name="money_plan.html")


@app.get("/credit-cards", include_in_schema=False)
def credit_cards_page(request: Request):
    return templates.TemplateResponse(request=request, name="credit_cards.html", context={"meta": credit_cards_meta()})


@app.get("/tafqeet", include_in_schema=False)
def tafqeet_page(request: Request):
    return templates.TemplateResponse(request=request, name="tafqeet.html")


@app.get("/budget-planner", include_in_schema=False)
def budget_planner_page(request: Request):
    return templates.TemplateResponse(request=request, name="budget_planner.html")


@app.get("/compare-investments", include_in_schema=False)
async def compare_investments_page(request: Request):
    prices, _ = await _market_snapshot()
    return templates.TemplateResponse(request=request, name="compare_investments.html", context={"prices": prices})


@app.get("/nbe-certificate", include_in_schema=False)
def nbe_certificate_landing(request: Request):
    all_certs = load_bank_certificates().get("certificates", [])
    nbe_certs = [c for c in all_certs if c["bank"] == "البنك الأهلي المصري"]
    return templates.TemplateResponse(request=request, name="landing_nbe_certificate.html", context={"certs": nbe_certs, "certs_json": json.dumps(nbe_certs, ensure_ascii=False)})


@app.get("/zakat-deposit", include_in_schema=False)
async def zakat_deposit_landing(request: Request):
    prices, _ = await _market_snapshot()
    return templates.TemplateResponse(request=request, name="landing_zakat_deposit.html", context={"prices": prices})


@app.get("/savings-interest-guide", include_in_schema=False)
def savings_interest_guide_landing(request: Request):
    return templates.TemplateResponse(request=request, name="landing_savings_guide.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.get("/robots.txt", include_in_schema=False)
async def robots():
    content = f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n"
    return Response(content=content, media_type="text/plain")


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap():
    urls = ["", "/about", "/faq", "/privacy", "/terms", "/contact", "/loan", "/certificate", "/savings", "/inflation", "/salary", "/zakat", "/end-of-service", "/market", "/money-plan", "/credit-cards", "/tafqeet", "/budget-planner", "/compare-investments", "/nbe-certificate", "/zakat-deposit", "/savings-interest-guide"]
    xml_content = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    for url in urls:
        xml_content += f"<url><loc>{SITE_URL}{url}</loc><priority>0.8</priority></url>"
    xml_content += "</urlset>"
    return Response(content=xml_content, media_type="application/xml")


@app.get("/ads.txt", include_in_schema=False)
async def ads_txt():
    # جوجل بيقرأ الملف ده من جذر الدومين عشان يتأكد إنك مصرّح لنفسك ببيع
    # مساحة الإعلانات (معيار IAB ads.txt). لحد ما تحط ADSENSE_PUBLISHER_ID
    # في .env، بيرجع تعليق بس (سطر بيبدأ بـ #) عشان الملف يفضل صالح الصيغة.
    if ADSENSE_PUBLISHER_ID:
        content = f"google.com, pub-{ADSENSE_PUBLISHER_ID}, DIRECT, f08c47fec0942fa0\n"
    else:
        content = "# ADSENSE_PUBLISHER_ID لسه مش متظبط في .env — حطّه بعد التسجيل في AdSense\n"
    return Response(content=content, media_type="text/plain")


@app.get("/healthz", include_in_schema=False)
def health_check() -> dict[str, str]:
    return {"service": "حساباتى", "status": "ok"}


# ---------------------------------------------------------------------------
# بيانات ومصادر
# ---------------------------------------------------------------------------
@app.get("/data", tags=["data"])
@limiter.limit("30/minute")
async def data_status(request: Request):
    try:
        return await _refresh_if_stale("cbe", load_data, update_cbe_data, "updated_at", CBE_UPDATE_INTERVAL)
    except DataSourceError as exc:
        logger.exception("Unable to load source data")
        raise HTTPException(status_code=503, detail="Source data is temporarily unavailable.") from exc


@app.get("/api/market", tags=["data"])
@limiter.limit("60/minute")
async def api_market(request: Request):
    prices, egx = await _market_snapshot()
    return {"prices": prices, "egx": egx, "fuel": load_fuel_prices()}


@app.get("/api/market/history", tags=["data"])
@limiter.limit("60/minute")
def api_market_history(request: Request, days: int = 30):
    days = max(1, min(days, 400))
    return {"entries": get_price_history(days)}


# ---------------------------------------------------------------------------
# القروض
# ---------------------------------------------------------------------------
@app.post("/calculate/loan", tags=["calculators"])
@limiter.limit("30/minute")
def calculate_loan(request: Request, payload: LoanInput):
    try:
        return loan_calculator(payload.principal, payload.annual_rate, payload.years, payload.admin_fee_percent)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/calculate/debt-burden", tags=["calculators"])
@limiter.limit("30/minute")
def calculate_debt_burden(request: Request, payload: DebtBurdenInput):
    try:
        return debt_burden_check(payload.monthly_installment, payload.monthly_net_income, payload.existing_monthly_debts)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/simulate/loan-early-settlement", tags=["simulators"])
@limiter.limit("10/minute")
def simulate_early_settlement(request: Request, payload: EarlySettlementInput):
    try:
        return loan_early_settlement(payload.principal, payload.annual_rate, payload.years, payload.months_paid, payload.penalty_percent)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# شهادات الادخار
# ---------------------------------------------------------------------------
@app.post("/calculate/certificate", tags=["calculators"])
@limiter.limit("30/minute")
def calculate_certificate(request: Request, payload: CertificateInput):
    try:
        return certificate_calculator(payload.principal, payload.annual_rate, payload.years, payload.payout)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/certificates/meta", tags=["calculators"])
@limiter.limit("60/minute")
def certificates_meta_route(request: Request):
    return certificates_meta()


@app.get("/certificates", tags=["calculators"])
@limiter.limit("60/minute")
def certificates_list_route(request: Request):
    return load_bank_certificates()


@app.post("/compare-certificates", tags=["calculators"])
@limiter.limit("30/minute")
def compare_certificates_route(request: Request, payload: CompareCertificatesInput):
    try:
        return compare_certificates(payload.money, payload.term_years, payload.bank)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/simulate/certificate-redemption", tags=["simulators"])
@limiter.limit("10/minute")
def simulate_certificate_redemption(request: Request, payload: CertificateRedemptionInput):
    try:
        return certificate_early_redemption(payload.principal, payload.annual_rate, payload.years, payload.months_held)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# حسابات التوفير
# ---------------------------------------------------------------------------
@app.post("/calculate/savings", tags=["calculators"])
@limiter.limit("30/minute")
def calculate_savings(request: Request, payload: SavingsInput):
    try:
        return savings_calculator(payload.initial, payload.monthly_contribution, payload.annual_rate, payload.years)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/savings-accounts/meta", tags=["calculators"])
@limiter.limit("60/minute")
def savings_accounts_meta_route(request: Request):
    return savings_accounts_meta()


@app.get("/savings-accounts", tags=["calculators"])
@limiter.limit("60/minute")
def savings_accounts_list_route(request: Request):
    return load_savings_accounts()


@app.post("/compare-savings", tags=["calculators"])
@limiter.limit("30/minute")
def compare_savings_route(request: Request, payload: CompareSavingsInput):
    try:
        return compare_savings_accounts(payload.money, payload.years, payload.bank)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/calculate/compound-reinvestment", tags=["calculators"])
@limiter.limit("30/minute")
def calculate_reinvestment(request: Request, payload: SavingsInput):
    try:
        return investment_reinvestment_income(payload.initial, payload.annual_rate, payload.years, payload.monthly_contribution)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# التضخم
# ---------------------------------------------------------------------------
@app.post("/calculate/inflation", tags=["calculators"])
@limiter.limit("30/minute")
def calculate_inflation(request: Request, payload: InflationInput):
    try:
        return inflation_calculator(payload.amount, payload.annual_inflation, payload.years)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# الراتب
# ---------------------------------------------------------------------------
@app.post("/calculate/salary", tags=["calculators"])
@limiter.limit("30/minute")
def calculate_salary(request: Request, payload: SalaryInput):
    year = payload.year or datetime.now().year
    try:
        return salary_calculator(payload.net_monthly, year)
    except (ValueError, DataSourceError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# مكافأة مدة الخدمة غير المؤمن عليها
# ---------------------------------------------------------------------------
@app.post("/calculate/end-of-service", tags=["calculators"])
@limiter.limit("30/minute")
def calculate_eos(request: Request, payload: EndOfServiceInput):
    try:
        return end_of_service_calculator(payload.salary, payload.uncovered_years)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# الزكاة
# ---------------------------------------------------------------------------
@app.post("/calculate/zakat", tags=["calculators"])
@limiter.limit("30/minute")
async def calculate_zakat(request: Request, payload: ZakatInput):
    prices, _ = await _market_snapshot()
    gold = prices.get("gold", {})
    silver = prices.get("silver", {})
    gold_21 = payload.override_gold_price_21k or gold.get("21k")
    gold_18 = gold.get("18k")
    gold_24 = gold.get("24k")
    silver_price = payload.override_silver_price or silver.get("999")

    try:
        return zakat_calculator_full(
            cash_egp=payload.cash_egp,
            gold_grams_21k=payload.gold_grams_21k,
            gold_grams_18k=payload.gold_grams_18k,
            gold_grams_24k=payload.gold_grams_24k,
            worn_gold_grams_21k=payload.worn_gold_grams_21k,
            worn_gold_grams_18k=payload.worn_gold_grams_18k,
            worn_gold_grams_24k=payload.worn_gold_grams_24k,
            exclude_worn_gold=payload.exclude_worn_gold,
            silver_grams=payload.silver_grams,
            stocks_value=payload.stocks_value,
            receivables=payload.receivables,
            debts=payload.debts,
            nisab_basis=payload.nisab_basis,
            gold_price_21k_gram=gold_21,
            gold_price_18k_gram=gold_18,
            gold_price_24k_gram=gold_24,
            silver_price_gram=silver_price,
            hawl_passed=payload.hawl_passed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# ماذا أفعل بفلوسي؟
# ---------------------------------------------------------------------------
@app.post("/calculate/money-plan", tags=["calculators"])
@limiter.limit("20/minute")
async def calculate_money_plan(request: Request, payload: MoneyPlanInput):
    prices, _ = await _market_snapshot()
    gold_21 = prices.get("gold", {}).get("21k")
    try:
        return money_plan_scenarios(payload.amount, payload.liquidity_need, payload.needs_income, payload.duration_years, gold_21)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# البطاقات الائتمانية
# ---------------------------------------------------------------------------
@app.get("/credit-cards/meta", tags=["calculators"])
@limiter.limit("60/minute")
def credit_cards_meta_route(request: Request):
    return credit_cards_meta()


@app.get("/credit-cards", tags=["calculators"])
@limiter.limit("60/minute")
def credit_cards_list_route(request: Request):
    return load_credit_cards()


@app.post("/recommend-credit-card", tags=["calculators"])
@limiter.limit("20/minute")
def recommend_credit_card_route(request: Request, payload: CreditCardRecommendInput):
    try:
        return recommend_credit_cards(payload.monthly_income, payload.primary_need)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/calculate/credit-card-balance-cost", tags=["calculators"])
@limiter.limit("30/minute")
def credit_card_balance_cost_route(request: Request, payload: CreditCardBalanceCostInput):
    try:
        return credit_card_balance_cost(payload.balance, payload.monthly_interest_rate_percent, payload.min_payment_percent, payload.min_payment_floor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# ميزانية 50/30/20
# ---------------------------------------------------------------------------
@app.post("/calculate/budget-planner", tags=["calculators"])
@limiter.limit("30/minute")
def budget_planner_route(request: Request, payload: BudgetPlannerInput):
    try:
        return budget_planner(payload.monthly_net_income, payload.fixed_obligations)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# مقارنة أوعية الادخار: شهادة / توفير / ذهب
# ---------------------------------------------------------------------------
# آخر سعر ذهب عيار 21 موثّق بحثياً قبل بداية تشغيل هذا الموقع (21 سبتمبر 2025، bankygate.com).
# بمجرد ما يتراكم سجل price_history.json لمدة سنة كاملة من التشغيل الفعلي، الكود بيفضّل تلقائياً
# القيمة الحقيقية من السجل بدل هذا الرقم الثابت.
FALLBACK_GOLD_21K_YEAR_AGO = 4975.0


def _gold_price_year_ago() -> float:
    history = get_price_history(400)
    if len(history) >= 350:
        oldest = history[0]
        if oldest.get("gold_21k"):
            return oldest["gold_21k"]
    return FALLBACK_GOLD_21K_YEAR_AGO


@app.post("/compare-investments", tags=["calculators"])
@limiter.limit("20/minute")
async def compare_investments_route(request: Request, payload: CompareInvestmentsInput):
    prices, _ = await _market_snapshot()
    gold_now = prices.get("gold", {}).get("21k")
    try:
        return compare_investment_vehicles(payload.amount, payload.duration_years, gold_now, _gold_price_year_ago())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# لوحة الإدارة
# ---------------------------------------------------------------------------
@app.post("/admin/update-cbe", tags=["admin"], dependencies=[Depends(require_admin_token)])
@limiter.limit("6/minute")
async def update_cbe(request: Request):
    try:
        return await update_cbe_data()
    except DataSourceError as exc:
        logger.exception("CBE data refresh failed")
        raise HTTPException(status_code=502, detail="Could not refresh CBE data.") from exc


@app.post("/admin/update-market", tags=["admin"], dependencies=[Depends(require_admin_token)])
@limiter.limit("6/minute")
async def update_market(request: Request):
    return await update_market_prices()


@app.post("/admin/update-egx", tags=["admin"], dependencies=[Depends(require_admin_token)])
@limiter.limit("6/minute")
async def update_egx(request: Request):
    return await fetch_egx_data()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
