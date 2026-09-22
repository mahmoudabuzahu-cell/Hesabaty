"""محركات الحساب المالي لموقع (حساباتى).

كل الحسابات تستخدم Decimal لتفادي أخطاء التقريب في الأرقام المالية.
لا تحتوي هذه الوحدة على أي قواعد ضريبية أو تأمينية أو أسعار بنكية "مبنية على تخمين":
كل رقم قانوني أو بنكي يأتي من config/*.json وله تاريخ تحقق ومصدر (راجع README).
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional

from sources import get_salary_rules

BASE_DIR = Path(__file__).resolve().parent
CERTIFICATES_FILE = BASE_DIR / "config" / "bank_certificates.json"
SAVINGS_ACCOUNTS_FILE = BASE_DIR / "config" / "savings_accounts.json"
CREDIT_CARDS_FILE = BASE_DIR / "config" / "credit_cards.json"

TWO_PLACES = Decimal("0.01")


# ---------------------------------------------------------------------------
# أدوات مساعدة عامة
# ---------------------------------------------------------------------------
def round_decimal(value: Decimal, places: int = 2) -> Decimal:
    quant = Decimal("1").scaleb(-places)
    return value.quantize(quant)


def _to_decimal(value, field_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"قيمة غير صالحة في الحقل: {field_name}") from exc


def validate_positive(value, field_name: str) -> Decimal:
    dec = _to_decimal(value, field_name)
    if dec <= 0:
        raise ValueError(f"يجب أن تكون قيمة '{field_name}' أكبر من صفر")
    return dec


def validate_non_negative(value, field_name: str) -> Decimal:
    dec = _to_decimal(value, field_name)
    if dec < 0:
        raise ValueError(f"لا يمكن أن تكون قيمة '{field_name}' سالبة")
    return dec


def _load_json_config(path: Path, default: Dict) -> Dict:
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return default


# ---------------------------------------------------------------------------
# القروض
# ---------------------------------------------------------------------------
LOAN_PRESETS = {
    "personal": {"label": "قرض شخصي", "default_years": 3, "max_years": 7},
    "mortgage": {"label": "تمويل عقاري", "default_years": 20, "max_years": 30},
    "car": {"label": "قرض سيارة", "default_years": 5, "max_years": 7},
    "certificate_backed": {"label": "قرض بضمان شهادة / وديعة", "default_years": 3, "max_years": 5},
}


def _standard_payment(principal: Decimal, monthly_rate: Decimal, n: int) -> Decimal:
    if monthly_rate == 0:
        return round_decimal(principal / Decimal(n))
    factor = (Decimal("1") + monthly_rate) ** n
    payment = principal * monthly_rate * factor / (factor - Decimal("1"))
    return round_decimal(payment)


def _amortization_schedule(principal: Decimal, monthly_rate: Decimal, n: int, payment: Decimal) -> List[Dict]:
    balance = principal
    schedule = []
    for month in range(1, n + 1):
        interest = round_decimal(balance * monthly_rate)
        principal_part = payment - interest
        if month == n or principal_part >= balance:
            principal_part = balance
            current_payment = round_decimal(balance + interest)
            balance = Decimal("0.00")
        else:
            current_payment = payment
            balance = round_decimal(balance - principal_part)
        schedule.append(
            {
                "month": month,
                "payment": current_payment,
                "interest": interest,
                "principal": round_decimal(principal_part),
                "balance": balance,
            }
        )
        if balance <= 0:
            break
    return schedule


def loan_calculator(principal, annual_rate, years: int, admin_fee_percent=0) -> Dict:
    principal = validate_positive(principal, "principal")
    annual_rate = validate_non_negative(annual_rate, "annual_rate")
    years = int(validate_positive(years, "years"))
    admin_fee_percent = validate_non_negative(admin_fee_percent, "admin_fee_percent")

    monthly_rate = annual_rate / Decimal("100") / Decimal("12")
    n = years * 12
    payment = _standard_payment(principal, monthly_rate, n)
    schedule = _amortization_schedule(principal, monthly_rate, n, payment)
    total_paid = sum((item["payment"] for item in schedule), Decimal("0.00"))
    admin_fee = round_decimal(principal * admin_fee_percent / Decimal("100"))

    return {
        "monthly_payment": payment,
        "total_paid": round_decimal(total_paid),
        "total_interest": round_decimal(total_paid - principal),
        "admin_fee": admin_fee,
        "net_disbursed": round_decimal(principal - admin_fee),
        "schedule": schedule,
    }


def debt_burden_check(monthly_installment, monthly_net_income, existing_monthly_debts=0) -> Dict:
    monthly_installment = validate_non_negative(monthly_installment, "monthly_installment")
    monthly_net_income = validate_positive(monthly_net_income, "monthly_net_income")
    existing_monthly_debts = validate_non_negative(existing_monthly_debts, "existing_monthly_debts")

    total_obligations = monthly_installment + existing_monthly_debts
    ratio = (total_obligations / monthly_net_income) * Decimal("100")
    max_recommended = monthly_net_income * Decimal("0.5") - existing_monthly_debts

    return {
        "ratio_percent": round_decimal(ratio, 1),
        "within_cbe_guideline": total_obligations <= monthly_net_income * Decimal("0.5"),
        "max_recommended_installment": round_decimal(max(max_recommended, Decimal("0"))),
    }


def loan_early_settlement(principal, annual_rate, years, months_paid, penalty_percent=2.0) -> Dict:
    principal = validate_positive(principal, "principal")
    annual_rate = validate_non_negative(annual_rate, "annual_rate")
    years = int(validate_positive(years, "years"))
    months_paid = int(validate_non_negative(months_paid, "months_paid"))
    penalty_percent = validate_non_negative(penalty_percent, "penalty_percent")

    n = years * 12
    if months_paid >= n:
        raise ValueError("عدد الأقساط المسددة يجب أن يكون أقل من إجمالي عدد أقساط القرض")

    monthly_rate = annual_rate / Decimal("100") / Decimal("12")
    payment = _standard_payment(principal, monthly_rate, n)
    schedule = _amortization_schedule(principal, monthly_rate, n, payment)

    balance_after = schedule[months_paid - 1]["balance"] if months_paid > 0 else principal
    remaining_interest = sum((item["interest"] for item in schedule[months_paid:]), Decimal("0.00"))
    penalty = round_decimal(balance_after * penalty_percent / Decimal("100"))

    return {
        "remaining_balance": round_decimal(balance_after),
        "penalty": penalty,
        "penalty_percent": penalty_percent,
        "payoff_amount": round_decimal(balance_after + penalty),
        "remaining_interest_saved": round_decimal(remaining_interest),
        "note": "نسبة غرامة السداد المبكر استرشادية (تحدّد افتراضياً بـ2%) وتختلف فعلياً حسب سياسة البنك وشروط عقد القرض.",
    }


# ---------------------------------------------------------------------------
# شهادات الادخار
# ---------------------------------------------------------------------------
def certificate_calculator(principal, annual_rate, years: int, payout: str = "monthly") -> Dict:
    principal = validate_positive(principal, "principal")
    annual_rate = validate_non_negative(annual_rate, "annual_rate")
    years = int(validate_positive(years, "years"))

    annual_income = principal * annual_rate / Decimal("100")
    periods = {"monthly": 12, "quarterly": 4, "yearly": 1, "maturity": 1}.get(payout, 12)
    per_period_income = round_decimal(annual_income / Decimal(periods)) if payout != "maturity" else Decimal("0.00")
    total_income = round_decimal(annual_income * Decimal(years))

    return {
        "annual_income": round_decimal(annual_income),
        "payout": payout,
        "periods_per_year": periods,
        "income_per_period": per_period_income,
        "total_income": total_income,
        "maturity_value": round_decimal(principal + total_income) if payout == "maturity" else round_decimal(principal),
    }


def certificate_early_redemption(principal, annual_rate, years, months_held) -> Dict:
    principal = validate_positive(principal, "principal")
    annual_rate = validate_non_negative(annual_rate, "annual_rate")
    years = int(validate_positive(years, "years"))
    months_held = int(validate_positive(months_held, "months_held"))

    total_months = years * 12
    if months_held > total_months:
        raise ValueError("عدد الأشهر لا يمكن أن يتجاوز مدة الشهادة")

    earned_to_date = round_decimal(principal * (annual_rate / Decimal("100")) / Decimal("12") * Decimal(months_held))

    if months_held < 6:
        return {
            "redemption_value": round_decimal(principal),
            "earned_income": earned_to_date,
            "penalty": earned_to_date,
            "message": (
                "لا يمكن كسر الشهادة عادة قبل مرور 6 أشهر على الشراء. في حال السماح بذلك استثنائياً "
                "يتم خصم العائد المكتسب بالكامل غالباً، ويسترد صاحب الشهادة رأس المال فقط."
            ),
        }

    penalty = round_decimal(earned_to_date * Decimal("0.5"))
    return {
        "redemption_value": round_decimal(principal + earned_to_date - penalty),
        "earned_income": earned_to_date,
        "penalty": penalty,
        "message": (
            "بعد 6 أشهر، يُخصم عادة 50% من العائد المكتسب كغرامة فك الشهادة. "
            "هذه نسبة استرشادية شائعة، وتحدَّد فعلياً حسب تعليمات البنك وشروط الشهادة."
        ),
    }


def load_bank_certificates() -> Dict:
    return _load_json_config(CERTIFICATES_FILE, {"certificates": [], "checked_at": None})


def certificates_meta() -> Dict:
    data = load_bank_certificates()
    certs = data.get("certificates", [])
    return {
        "terms": sorted({c["term_years"] for c in certs}),
        "banks": sorted({c["bank"] for c in certs}),
        "count": len(certs),
        "checked_at": data.get("checked_at"),
    }


def _certificate_effective_rate(cert: Dict) -> Decimal:
    if cert.get("type") == "decreasing":
        rates = cert["annual_rates"]
        return round_decimal(sum(Decimal(str(r)) for r in rates) / Decimal(len(rates)))
    return Decimal(str(cert["rate"]))


def _certificate_total_profit(cert: Dict, money: Decimal, term_years: int) -> Decimal:
    if cert.get("type") == "decreasing":
        rates = cert["annual_rates"]
        total = Decimal("0")
        for i in range(term_years):
            rate = Decimal(str(rates[i])) if i < len(rates) else Decimal(str(rates[-1]))
            total += money * rate / Decimal("100")
        return round_decimal(total)
    rate = Decimal(str(cert["rate"]))
    return round_decimal(money * rate / Decimal("100") * Decimal(term_years))


def compare_certificates(money, term_years: int, bank: Optional[str] = None) -> Dict:
    money = validate_positive(money, "money")
    term_years = int(validate_positive(term_years, "term_years"))

    certificates = load_bank_certificates().get("certificates", [])
    results, excluded = [], []

    for cert in certificates:
        if cert["term_years"] != term_years:
            continue
        if bank and cert["bank"] != bank:
            continue
        min_amount = Decimal(str(cert.get("min_amount", 0)))
        if money < min_amount:
            excluded.append({"bank": cert["bank"], "name": cert["name"], "min_amount": cert.get("min_amount", 0)})
            continue

        effective_rate = _certificate_effective_rate(cert)
        total_profit = _certificate_total_profit(cert, money, term_years)
        monthly_income = round_decimal((money * effective_rate / Decimal("100")) / Decimal("12"))

        results.append(
            {
                "bank": cert["bank"],
                "name": cert["name"],
                "type": cert.get("type", "fixed"),
                "rate": effective_rate,
                "annual_rates": cert.get("annual_rates"),
                "min_amount": cert.get("min_amount", 0),
                "loanable": cert.get("loanable", False),
                "customer_type": cert.get("customer_type", "individual"),
                "notes": cert.get("notes", ""),
                "source_url": cert.get("source_url", ""),
                "checked_at": cert.get("checked_at", ""),
                "total_profit": total_profit,
                "monthly_income": monthly_income,
                "is_best": False,
            }
        )

    results.sort(key=lambda x: x["total_profit"], reverse=True)
    if results:
        results[0]["is_best"] = True

    return {"results": results, "excluded_below_minimum": excluded}


# ---------------------------------------------------------------------------
# حسابات التوفير
# ---------------------------------------------------------------------------
def savings_calculator(initial, monthly_contribution, annual_rate, years: int) -> Dict:
    initial = validate_non_negative(initial, "initial")
    monthly_contribution = validate_non_negative(monthly_contribution, "monthly_contribution")
    annual_rate = validate_non_negative(annual_rate, "annual_rate")
    years = int(validate_positive(years, "years"))

    monthly_rate = annual_rate / Decimal("100") / Decimal("12")
    balance = initial
    total_contributed = initial
    yearly_snapshots = []

    for month in range(1, years * 12 + 1):
        balance += monthly_contribution
        total_contributed += monthly_contribution
        balance += balance * monthly_rate
        if month % 12 == 0:
            yearly_snapshots.append(
                {
                    "year": month // 12,
                    "balance": round_decimal(balance),
                    "contributed": round_decimal(total_contributed),
                }
            )

    balance = round_decimal(balance)
    total_contributed = round_decimal(total_contributed)
    return {
        "final_balance": balance,
        "total_contributed": total_contributed,
        "total_profit": round_decimal(balance - total_contributed),
        "yearly_snapshots": yearly_snapshots,
    }


def investment_reinvestment_income(initial, annual_rate, years, monthly_contribution=0) -> Dict:
    return savings_calculator(initial, monthly_contribution, annual_rate, years)


def _tiered_annual_income(amount: Decimal, tiers: List[Dict]) -> Decimal:
    previous = Decimal("0")
    income = Decimal("0")
    for tier in tiers:
        upper = tier.get("up_to")
        rate = Decimal(str(tier["rate"]))
        if upper is None:
            slice_amount = max(Decimal("0"), amount - previous)
            income += slice_amount * rate / Decimal("100")
            break
        upper = Decimal(str(upper))
        slice_amount = max(Decimal("0"), min(amount, upper) - previous)
        income += slice_amount * rate / Decimal("100")
        previous = upper
        if amount <= upper:
            break
    return income


def load_savings_accounts() -> Dict:
    return _load_json_config(SAVINGS_ACCOUNTS_FILE, {"accounts": [], "checked_at": None})


def savings_accounts_meta() -> Dict:
    data = load_savings_accounts()
    accounts = data.get("accounts", [])
    return {
        "banks": sorted({a["bank"] for a in accounts}),
        "count": len(accounts),
        "checked_at": data.get("checked_at"),
    }


def compare_savings_accounts(money, years: int, bank: Optional[str] = None) -> Dict:
    money = validate_positive(money, "money")
    years = int(validate_positive(years, "years"))

    accounts = load_savings_accounts().get("accounts", [])
    results, excluded = [], []

    for acct in accounts:
        if bank and acct["bank"] != bank:
            continue
        min_amount = Decimal(str(acct.get("min_amount", 0)))
        if money < min_amount:
            excluded.append({"bank": acct["bank"], "name": acct["name"], "min_amount": acct.get("min_amount", 0)})
            continue

        if "tiers" in acct:
            annual_income = _tiered_annual_income(money, acct["tiers"])
            display_rate = round_decimal((annual_income / money) * Decimal("100")) if money > 0 else Decimal("0")
        else:
            rate = Decimal(str(acct.get("annual_rate", 0)))
            annual_income = money * rate / Decimal("100")
            display_rate = rate

        results.append(
            {
                "bank": acct["bank"],
                "name": acct["name"],
                "rate": display_rate,
                "min_amount": acct.get("min_amount", 0),
                "account_type": acct.get("account_type", "regular"),
                "notes": acct.get("notes", ""),
                "source_url": acct.get("source_url", ""),
                "checked_at": acct.get("checked_at", ""),
                "annual_income": round_decimal(annual_income),
                "total_income": round_decimal(annual_income * Decimal(years)),
                "is_best": False,
            }
        )

    results.sort(key=lambda x: x["total_income"], reverse=True)
    if results:
        results[0]["is_best"] = True

    return {"results": results, "excluded_below_minimum": excluded}


# ---------------------------------------------------------------------------
# التضخم
# ---------------------------------------------------------------------------
def inflation_calculator(amount, annual_inflation, years: int) -> Dict:
    amount = validate_positive(amount, "amount")
    annual_inflation = validate_non_negative(annual_inflation, "annual_inflation")
    years = int(validate_positive(years, "years"))

    rate = Decimal("1") + annual_inflation / Decimal("100")
    future_value_needed = amount * (rate**years)
    purchasing_power_today = amount / (rate**years)

    return {
        "future_value_needed": round_decimal(future_value_needed),
        "purchasing_power_remaining": round_decimal(purchasing_power_today),
        "value_lost_percent": round_decimal((Decimal("1") - purchasing_power_today / amount) * Decimal("100"), 1),
    }


# ---------------------------------------------------------------------------
# الراتب والضريبة
# ---------------------------------------------------------------------------
def progressive_tax(taxable_income: Decimal, brackets: List[Dict]) -> Decimal:
    tax = Decimal("0")
    previous = Decimal("0")
    for bracket in brackets:
        upper = bracket.get("up_to")
        rate = Decimal(str(bracket["rate"]))
        if upper is None:
            slice_amount = max(Decimal("0"), taxable_income - previous)
            tax += slice_amount * rate
            break
        upper = Decimal(str(upper))
        slice_amount = max(Decimal("0"), min(taxable_income, upper) - previous)
        tax += slice_amount * rate
        previous = upper
        if taxable_income <= upper:
            break
    return tax


def _calculate_net_from_gross(gross_annual: Decimal, rules: Dict) -> Decimal:
    insurance_rate = Decimal(str(rules["insurance_employee_rate"]))
    insurance_cap = Decimal(str(rules["annual_insurance_wage_cap"]))
    insurance = min(gross_annual, insurance_cap) * insurance_rate

    exemption = Decimal(str(rules["annual_personal_exemption"]))
    taxable = max(Decimal("0"), gross_annual - insurance - exemption)
    tax = progressive_tax(taxable, rules["tax_brackets"])

    return gross_annual - insurance - tax


def salary_calculator(net_monthly, year: int) -> Dict:
    net_monthly = validate_positive(net_monthly, "net_monthly")
    rules = get_salary_rules(year)
    if not rules:
        raise ValueError(
            f"قواعد ضريبة المرتبات والتأمينات لسنة {year} غير متاحة أو غير موثقة بعد. "
            "لن نقوم بتخمين هذه القواعد لتجنب عرض بيانات غير دقيقة."
        )

    target_net_annual = net_monthly * Decimal("12")
    gross_annual = target_net_annual * Decimal("1.3")

    for _ in range(50):
        computed_net = _calculate_net_from_gross(gross_annual, rules)
        diff = target_net_annual - computed_net
        if abs(diff) < Decimal("0.5"):
            break
        gross_annual += diff * Decimal("1.05")
        if gross_annual < 0:
            gross_annual = target_net_annual

    insurance_rate = Decimal(str(rules["insurance_employee_rate"]))
    insurance_cap = Decimal(str(rules["annual_insurance_wage_cap"]))
    insurance = min(gross_annual, insurance_cap) * insurance_rate
    exemption = Decimal(str(rules["annual_personal_exemption"]))
    taxable = max(Decimal("0"), gross_annual - insurance - exemption)
    tax = progressive_tax(taxable, rules["tax_brackets"])

    return {
        "gross_monthly": round_decimal(gross_annual / Decimal("12")),
        "gross_annual": round_decimal(gross_annual),
        "insurance_monthly": round_decimal(insurance / Decimal("12")),
        "insurance_annual": round_decimal(insurance),
        "tax_monthly": round_decimal(tax / Decimal("12")),
        "tax_annual": round_decimal(tax),
        "net_monthly": round_decimal(net_monthly),
        "net_annual": round_decimal(net_monthly * Decimal("12")),
        "rules_source": rules.get("source"),
        "rules_effective_from": rules.get("effective_from"),
    }


# ---------------------------------------------------------------------------
# مكافأة مدة الخدمة غير المؤمن عليها
# ---------------------------------------------------------------------------
SCOPE_NOTE_END_OF_SERVICE = (
    "في القانون المصري لا توجد \"مكافأة نهاية خدمة\" عامة يصرفها كل صاحب عمل لكل موظف عند ترك العمل، "
    "كما هو الحال في بعض دول الخليج. أغلب المستحقات عند انتهاء الخدمة تُصرف معاشاً أو تعويض دفعة واحدة "
    "من الهيئة القومية للتأمين الاجتماعي حسب تاريخ الاشتراك. هذه الحاسبة خاصة بمكافأة مدة الخدمة غير "
    "المؤمن عليها فقط (مثل مدة عمل قبل سن 18 سنة، أو الاستمرار في العمل بعد سن 60)، طبقاً لقانون العمل "
    "رقم 14 لسنة 2025 وقانون التأمينات الاجتماعية رقم 148 لسنة 2019."
)


def end_of_service_calculator(salary, uncovered_years) -> Dict:
    salary = validate_positive(salary, "salary")
    uncovered_years = int(validate_non_negative(uncovered_years, "uncovered_years"))

    first_slice = min(uncovered_years, 5)
    remaining = uncovered_years - first_slice
    total = salary * Decimal("0.5") * Decimal(first_slice) + salary * Decimal(remaining)

    return {
        "total_gratuity": round_decimal(total),
        "years_at_half_month": first_slice,
        "years_at_full_month": remaining,
        "scope_note": SCOPE_NOTE_END_OF_SERVICE,
    }


# ---------------------------------------------------------------------------
# الزكاة (حاسبة شاملة متعددة الأصول)
# ---------------------------------------------------------------------------
def zakat_nisab_amount(basis: str, gold_price_21k_gram: Optional[Decimal], silver_price_gram: Optional[Decimal]) -> Decimal:
    if basis == "silver":
        if not silver_price_gram:
            raise ValueError("سعر جرام الفضة مطلوب لحساب نصاب الفضة")
        return Decimal("595") * silver_price_gram
    if not gold_price_21k_gram:
        raise ValueError("سعر جرام الذهب عيار 21 مطلوب لحساب نصاب الذهب")
    return Decimal("85") * gold_price_21k_gram


def zakat_calculator_full(
    cash_egp=0,
    gold_grams_21k=0,
    gold_grams_18k=0,
    gold_grams_24k=0,
    worn_gold_grams_21k=0,
    worn_gold_grams_18k=0,
    worn_gold_grams_24k=0,
    exclude_worn_gold=False,
    silver_grams=0,
    stocks_value=0,
    receivables=0,
    debts=0,
    nisab_basis="gold",
    gold_price_21k_gram=None,
    gold_price_18k_gram=None,
    gold_price_24k_gram=None,
    silver_price_gram=None,
    hawl_passed=True,
) -> Dict:
    cash_egp = validate_non_negative(cash_egp, "cash_egp")
    gold_21 = validate_non_negative(gold_grams_21k, "gold_grams_21k")
    gold_18 = validate_non_negative(gold_grams_18k, "gold_grams_18k")
    gold_24 = validate_non_negative(gold_grams_24k, "gold_grams_24k")
    worn_21 = validate_non_negative(worn_gold_grams_21k, "worn_gold_grams_21k")
    worn_18 = validate_non_negative(worn_gold_grams_18k, "worn_gold_grams_18k")
    worn_24 = validate_non_negative(worn_gold_grams_24k, "worn_gold_grams_24k")
    silver_grams = validate_non_negative(silver_grams, "silver_grams")
    stocks_value = validate_non_negative(stocks_value, "stocks_value")
    receivables = validate_non_negative(receivables, "receivables")
    debts = validate_non_negative(debts, "debts")

    g21 = Decimal(str(gold_price_21k_gram)) if gold_price_21k_gram else Decimal("0")
    g18 = Decimal(str(gold_price_18k_gram)) if gold_price_18k_gram else Decimal("0")
    g24 = Decimal(str(gold_price_24k_gram)) if gold_price_24k_gram else Decimal("0")
    silver_price = Decimal(str(silver_price_gram)) if silver_price_gram else Decimal("0")

    if exclude_worn_gold:
        counted_21 = max(Decimal("0"), gold_21 - worn_21)
        counted_18 = max(Decimal("0"), gold_18 - worn_18)
        counted_24 = max(Decimal("0"), gold_24 - worn_24)
    else:
        counted_21, counted_18, counted_24 = gold_21, gold_18, gold_24

    gold_value = round_decimal(counted_21 * g21 + counted_18 * g18 + counted_24 * g24)
    silver_value = round_decimal(silver_grams * silver_price)

    total_wealth = cash_egp + gold_value + silver_value + stocks_value + receivables
    net_wealth = max(Decimal("0"), total_wealth - debts)

    nisab = zakat_nisab_amount(nisab_basis, g21 if g21 else None, silver_price if silver_price else None)
    meets_nisab = net_wealth >= nisab
    zakat_due = round_decimal(net_wealth * Decimal("0.025")) if (meets_nisab and hawl_passed) else Decimal("0.00")

    return {
        "total_wealth": round_decimal(total_wealth),
        "debts": round_decimal(debts),
        "net_wealth": round_decimal(net_wealth),
        "nisab_basis": nisab_basis,
        "nisab_amount": round_decimal(nisab),
        "meets_nisab": meets_nisab,
        "hawl_passed": hawl_passed,
        "zakat_due": zakat_due,
        "breakdown": {
            "cash": round_decimal(cash_egp),
            "gold": gold_value,
            "silver": silver_value,
            "stocks": round_decimal(stocks_value),
            "receivables": round_decimal(receivables),
        },
        "progress_ratio": float(min(Decimal("1"), net_wealth / nisab)) if nisab > 0 else 0.0,
    }


# ---------------------------------------------------------------------------
# ماذا أفعل بفلوسي؟ — سيناريوهات تعليمية تُبنى على حاسبات حقيقية
# ---------------------------------------------------------------------------
GOLD_HEDGE_NOTE = (
    "الذهب هنا مخزن قيمة وتحوّط ضد التضخم وتراجع الجنيه، مش أداة دخل ثابت زي الشهادات أو حسابات "
    "التوفير. سعره بيرتفع وينخفض حسب السوق العالمي والمحلي، فمفيش نسبة عائد سنوي مضمونة نقدر نحسبها له."
)

MONEY_PLAN_DISCLAIMER = (
    "دي مقارنة تعليمية بين سيناريوهات عامة بُنيت على إجاباتك وعلى أسعار وبيانات معلنة وقت الحساب، "
    "وليست توصية استثمارية شخصية. قرارك المالي بيتأثر بعوامل تانية كتير — التزاماتك، أهدافك، ومدى "
    "تحمّلك للمخاطرة — يستاهل تناقشها مع مستشار مالي مرخّص قبل قرار كبير."
)

_LIQUIDITY_ALLOCATIONS = {
    "full": {"certificate": Decimal("0.20"), "savings": Decimal("0.60"), "gold": Decimal("0.20")},
    "partial": {"certificate": Decimal("0.50"), "savings": Decimal("0.30"), "gold": Decimal("0.20")},
    "none": {"certificate": Decimal("0.80"), "savings": Decimal("0.10"), "gold": Decimal("0.10")},
}


def _best_certificate_for(amount: Decimal, term_years: int) -> Optional[Dict]:
    result = compare_certificates(amount, term_years)
    return result["results"][0] if result["results"] else None


def _best_savings_for(amount: Decimal, years: int) -> Optional[Dict]:
    result = compare_savings_accounts(amount, years)
    return result["results"][0] if result["results"] else None


def money_plan_scenarios(
    amount,
    liquidity_need: str,
    needs_income: bool,
    duration_years: int,
    gold_price_21k_gram: Optional[Decimal] = None,
) -> Dict:
    amount = validate_positive(amount, "amount")
    duration_years = int(validate_positive(duration_years, "duration_years"))
    if liquidity_need not in _LIQUIDITY_ALLOCATIONS:
        raise ValueError("قيمة غير صحيحة لاحتياج السيولة (المتاح: full أو partial أو none)")

    certs = load_bank_certificates().get("certificates", [])
    available_terms = sorted({c["term_years"] for c in certs}) or [3]
    closest_term = min(available_terms, key=lambda t: abs(t - duration_years))
    gold_price = Decimal(str(gold_price_21k_gram)) if gold_price_21k_gram else None

    best_cert = _best_certificate_for(amount, closest_term)
    best_savings = _best_savings_for(amount, max(duration_years, 1))

    scenarios = []

    # سيناريو A: التركيز الكامل في أداة واحدة، الأنسب لاحتياج السيولة والدخل
    if liquidity_need == "full" and best_savings:
        scenarios.append(
            {
                "id": "A",
                "title": f"التركيز الكامل في {best_savings['name']} ({best_savings['bank']})",
                "strategy": "سيولة شبه كاملة — تقدر تسحب فلوسك في أي وقت تقريباً بدون كسر شهادة أو خسارة عائد متراكم.",
                "allocation": [
                    {
                        "instrument": "savings",
                        "label": f"{best_savings['name']} — {best_savings['bank']}",
                        "percent": 100,
                        "amount": float(amount),
                        "rate": float(best_savings["rate"]),
                        "expected_total": float(best_savings["annual_income"] * Decimal(duration_years)),
                    }
                ],
            }
        )
    elif best_cert:
        if needs_income:
            expected_total = float(best_cert["total_profit"])
            note = "العائد بيتوزع دورياً كدخل شهري بدل ما يتراكم."
        else:
            reinvest = investment_reinvestment_income(amount, best_cert["rate"], duration_years, 0)
            expected_total = float(reinvest["total_profit"])
            note = "بافتراض إعادة استثمار العائد الدوري بدل صرفه، لأنك حددت إنك مش محتاج دخل شهري ثابت."
        scenarios.append(
            {
                "id": "A",
                "title": f"التركيز الكامل في {best_cert['name']} ({best_cert['bank']})",
                "strategy": f"أعلى عائد متوقع بين الخيارات، في المقابل فلوسك شبه مقفولة طول مدة الشهادة. {note}",
                "allocation": [
                    {
                        "instrument": "certificate",
                        "label": f"{best_cert['name']} — {best_cert['bank']}",
                        "percent": 100,
                        "amount": float(amount),
                        "rate": float(best_cert["rate"]),
                        "expected_total": expected_total,
                    }
                ],
            }
        )

    # سيناريو B: تنويع بين شهادة وسيولة وذهب حسب احتياج السيولة
    alloc = _LIQUIDITY_ALLOCATIONS[liquidity_need]
    cert_amount = round_decimal(amount * alloc["certificate"])
    savings_amount = round_decimal(amount * alloc["savings"])
    gold_amount = round_decimal(amount - cert_amount - savings_amount)

    b_allocation = []
    if cert_amount > 0:
        picked = _best_certificate_for(cert_amount, closest_term)
        if picked:
            b_allocation.append(
                {
                    "instrument": "certificate",
                    "label": f"{picked['name']} — {picked['bank']}",
                    "percent": float(round_decimal(alloc["certificate"] * 100, 0)),
                    "amount": float(cert_amount),
                    "rate": float(picked["rate"]),
                    "expected_total": float(picked["total_profit"]),
                }
            )
        else:
            b_allocation.append(
                {
                    "instrument": "certificate",
                    "label": "لا توجد شهادة متاحة بهذا المبلغ حالياً (أقل من الحد الأدنى)",
                    "percent": float(round_decimal(alloc["certificate"] * 100, 0)),
                    "amount": float(cert_amount),
                    "rate": None,
                    "expected_total": None,
                }
            )
    if savings_amount > 0:
        picked_s = _best_savings_for(savings_amount, max(duration_years, 1))
        if picked_s:
            b_allocation.append(
                {
                    "instrument": "savings",
                    "label": f"{picked_s['name']} — {picked_s['bank']}",
                    "percent": float(round_decimal(alloc["savings"] * 100, 0)),
                    "amount": float(savings_amount),
                    "rate": float(picked_s["rate"]),
                    "expected_total": float(picked_s["annual_income"] * Decimal(duration_years)),
                }
            )
        else:
            b_allocation.append(
                {
                    "instrument": "savings",
                    "label": "لا يوجد حساب توفير متاح بهذا المبلغ حالياً",
                    "percent": float(round_decimal(alloc["savings"] * 100, 0)),
                    "amount": float(savings_amount),
                    "rate": None,
                    "expected_total": None,
                }
            )
    if gold_amount > 0:
        grams = round_decimal(gold_amount / gold_price) if gold_price else None
        b_allocation.append(
            {
                "instrument": "gold",
                "label": "ذهب عيار 21 (تحوّط، بدون عائد ثابت)",
                "percent": float(round_decimal(alloc["gold"] * 100, 0)),
                "amount": float(gold_amount),
                "grams": float(grams) if grams is not None else None,
                "rate": None,
                "expected_total": None,
            }
        )

    scenarios.append(
        {
            "id": "B",
            "title": "تنويع بين شهادة وسيولة وذهب",
            "strategy": "توازن بين العائد والسيولة والتحوّط، بدل ما تحط كل الفلوس في سلة واحدة.",
            "allocation": b_allocation,
        }
    )

    # سيناريو C: أقصى مرونة، كنقطة مقارنة على الطرف الآخر من سيناريو A
    already_all_savings = scenarios[0]["allocation"][0]["instrument"] == "savings" and scenarios[0]["allocation"][0]["percent"] == 100
    if best_savings and not already_all_savings:
        scenarios.append(
            {
                "id": "C",
                "title": f"أقصى مرونة: {best_savings['name']} ({best_savings['bank']})",
                "strategy": "أقل قفل لفلوسك، مناسب لو مش متأكد إنك مش هتحتاجهم فجأة، غالباً على حساب عائد أقل من الشهادات.",
                "allocation": [
                    {
                        "instrument": "savings",
                        "label": f"{best_savings['name']} — {best_savings['bank']}",
                        "percent": 100,
                        "amount": float(amount),
                        "rate": float(best_savings["rate"]),
                        "expected_total": float(best_savings["annual_income"] * Decimal(duration_years)),
                    }
                ],
            }
        )

    return {
        "amount": float(round_decimal(amount)),
        "duration_years": duration_years,
        "liquidity_need": liquidity_need,
        "needs_income": needs_income,
        "scenarios": scenarios,
        "gold_note": GOLD_HEDGE_NOTE,
        "disclaimer": MONEY_PLAN_DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# مقارنة البطاقات الائتمانية + استخدامها بحرص
# ---------------------------------------------------------------------------
CREDIT_CARD_NEEDS = ["عام", "سفر", "كاش باك"]


def load_credit_cards() -> Dict:
    return _load_json_config(CREDIT_CARDS_FILE, {"cards": [], "market_facts": {}, "checked_at": None})


def credit_cards_meta() -> Dict:
    data = load_credit_cards()
    cards = data.get("cards", [])
    return {
        "banks": sorted({c["bank"] for c in cards}),
        "needs": CREDIT_CARD_NEEDS,
        "count": len(cards),
        "checked_at": data.get("checked_at"),
        "market_facts": data.get("market_facts", {}),
    }


def recommend_credit_cards(monthly_income, primary_need: str) -> Dict:
    monthly_income = validate_positive(monthly_income, "monthly_income")
    if primary_need not in CREDIT_CARD_NEEDS:
        raise ValueError(f"احتياج غير معروف. القيم المتاحة: {', '.join(CREDIT_CARD_NEEDS)}")

    data = load_credit_cards()
    cards = data.get("cards", [])
    eligible = [c for c in cards if Decimal(str(c.get("min_monthly_income", 0))) <= monthly_income]

    def sort_key(card):
        matches_need = card.get("best_for") == primary_need
        return (matches_need, Decimal(str(card.get("min_monthly_income", 0))))

    eligible.sort(key=sort_key, reverse=True)

    return {
        "recommended": eligible[:3],
        "eligible_count": len(eligible),
        "total_cards": len(cards),
        "market_facts": data.get("market_facts", {}),
    }


def credit_card_balance_cost(balance, monthly_interest_rate_percent, min_payment_percent=5.0, min_payment_floor=100) -> Dict:
    """يحاكي سداد رصيد بطاقة ائتمان بالحد الأدنى فقط، لتوضيح التكلفة الحقيقية لو اتأخرت في السداد الكامل."""
    balance = validate_positive(balance, "balance")
    monthly_rate = validate_non_negative(monthly_interest_rate_percent, "monthly_interest_rate_percent") / Decimal("100")
    min_payment_percent = validate_positive(min_payment_percent, "min_payment_percent") / Decimal("100")
    min_payment_floor = validate_non_negative(min_payment_floor, "min_payment_floor")

    remaining = balance
    total_interest = Decimal("0")
    months = 0
    MAX_MONTHS = 600

    while remaining > 0 and months < MAX_MONTHS:
        interest = round_decimal(remaining * monthly_rate)
        payment = max(round_decimal(remaining * min_payment_percent), min_payment_floor)
        payment = min(payment, remaining + interest)
        principal_payment = payment - interest
        if principal_payment <= 0:
            return {
                "never_paid_off": True,
                "message": (
                    "بالحد الأدنى ده، قيمة الفايدة الشهرية بتساوي أو تتجاوز مبلغ السداد — يعني الدين "
                    "مش هيتسدد أبداً وهيفضل يكبر. لازم تدفع أكتر من الحد الأدنى المطلوب."
                ),
            }
        remaining = round_decimal(remaining - principal_payment)
        total_interest += interest
        months += 1

    return {
        "never_paid_off": False,
        "months_to_payoff": months,
        "total_interest_paid": float(round_decimal(total_interest)),
        "total_paid": float(round_decimal(balance + total_interest)),
        "note": "المحاكاة بتفترض سداد الحد الأدنى بس شهرياً وعدم إضافة أي مشتريات جديدة على البطاقة خلال المدة دي.",
    }


# ---------------------------------------------------------------------------
# مُحاكي الميزانية الذكي (قاعدة 50/30/20)
# ---------------------------------------------------------------------------
def budget_planner(monthly_net_income, fixed_obligations=0) -> Dict:
    income = validate_positive(monthly_net_income, "monthly_net_income")
    fixed = validate_non_negative(fixed_obligations, "fixed_obligations")

    needs_target = income * Decimal("0.5")
    wants_target = income * Decimal("0.3")
    savings_target = income * Decimal("0.2")
    over_needs = fixed > needs_target

    if over_needs:
        remaining = max(Decimal("0"), income - fixed)
        wants_budget = round_decimal(remaining * Decimal("0.6"))
        savings_budget = round_decimal(remaining - wants_budget)
        variable_needs_budget = Decimal("0.00")
    else:
        variable_needs_budget = round_decimal(needs_target - fixed)
        wants_budget = round_decimal(wants_target)
        savings_budget = round_decimal(income - fixed - variable_needs_budget - wants_budget)

    return {
        "income": round_decimal(income),
        "fixed_obligations": round_decimal(fixed),
        "needs_target": round_decimal(needs_target),
        "savings_target": round_decimal(savings_target),
        "variable_needs_budget": variable_needs_budget,
        "wants_budget": wants_budget,
        "savings_budget": savings_budget,
        "daily_spending_allowance": round_decimal(wants_budget / Decimal("30")),
        "over_needs_budget": over_needs,
        "rule_note": "قاعدة 50/30/20 الاسترشادية: 50% احتياجات أساسية (سكن، أقساط، مواصلات، أكل)، 30% كماليات ورغبات، 20% ادخار أو سداد ديون إضافية.",
    }


# ---------------------------------------------------------------------------
# مقارنة مباشرة بين أوعية الادخار: شهادة مقابل توفير مقابل ذهب
# ---------------------------------------------------------------------------
GOLD_HISTORICAL_NOTE = (
    "أداء الذهب هنا تاريخي فقط (سعره الفعلي خلال آخر 12 شهر معروفة لدينا)، وليس عائداً مضموناً أو متوقعاً — "
    "على عكس الشهادة وحساب التوفير اللي عائدهما معلن ومحدد تعاقدياً. الأداء الماضي لا يضمن تكرار نفس النتيجة."
)


def compare_investment_vehicles(amount, duration_years: int, gold_price_21k_now=None, gold_price_21k_year_ago=None) -> Dict:
    amount = validate_positive(amount, "amount")
    duration_years = int(validate_positive(duration_years, "duration_years"))

    certs = load_bank_certificates().get("certificates", [])
    available_terms = sorted({c["term_years"] for c in certs}) or [3]
    closest_term = min(available_terms, key=lambda t: abs(t - duration_years))

    rows = []

    best_cert = _best_certificate_for(amount, closest_term)
    if best_cert:
        rows.append(
            {
                "option": "certificate",
                "label": f"{best_cert['name']} — {best_cert['bank']}",
                "rate": float(best_cert["rate"]),
                "expected_total_profit": float(best_cert["total_profit"]),
                "liquidity": "منخفضة نسبياً — غرامة أو فقدان جزء من العائد لو فُكّت قبل 6 أشهر على الأقل",
                "risk": "منخفض جداً (عائد تعاقدي من بنك مصري)",
            }
        )

    best_savings = _best_savings_for(amount, duration_years)
    if best_savings:
        rows.append(
            {
                "option": "savings",
                "label": f"{best_savings['name']} — {best_savings['bank']}",
                "rate": float(best_savings["rate"]),
                "expected_total_profit": float(best_savings["annual_income"] * Decimal(duration_years)),
                "liquidity": "عالية — تقدر تسحب في أي وقت تقريباً",
                "risk": "منخفض جداً (عائد تعاقدي من بنك مصري)",
            }
        )

    gold_row = None
    if gold_price_21k_now and gold_price_21k_year_ago:
        now_p = Decimal(str(gold_price_21k_now))
        year_ago_p = Decimal(str(gold_price_21k_year_ago))
        if year_ago_p > 0:
            historical_change_percent = round_decimal((now_p - year_ago_p) / year_ago_p * Decimal("100"), 1)
            grams = round_decimal(amount / now_p)
            gold_row = {
                "option": "gold",
                "label": "ذهب عيار 21 (تحوّط، ليس دخلاً ثابتاً)",
                "historical_change_percent_last_year": float(historical_change_percent),
                "grams_today": float(grams),
                "liquidity": "عالية نسبياً (بيع فوري في أي محل صاغة) لكن بفارق سعر بيع/شراء",
                "risk": "متوسط إلى مرتفع — القيمة تتقلب صعوداً وهبوطاً حسب السوق العالمي والمحلي",
            }
            rows.append(gold_row)

    return {
        "amount": float(round_decimal(amount)),
        "duration_years": duration_years,
        "rows": rows,
        "gold_note": GOLD_HISTORICAL_NOTE if gold_row else None,
        "disclaimer": MONEY_PLAN_DISCLAIMER,
    }
