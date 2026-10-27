"""Pure rating logic: turns a month's usage totals into invoice line items.

No database or web code lives here, so every billing rule can be unit tested
directly. All money is Decimal and rounded half-up to cents (never float).
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")

# usage kind -> (unit label, plan allowance field, plan overage-rate field)
USAGE_KINDS = {
    "voice": ("minutes", "included_minutes", "overage_per_minute"),
    "data": ("MB", "included_data_mb", "overage_per_mb"),
    "sms": ("messages", "included_sms", "overage_per_sms"),
}


def money(value: Decimal) -> Decimal:
    """Round to whole cents, half-up (the usual billing convention)."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PlanTerms:
    name: str
    monthly_fee: Decimal
    included_minutes: int
    included_data_mb: int
    included_sms: int
    overage_per_minute: Decimal
    overage_per_mb: Decimal
    overage_per_sms: Decimal


@dataclass(frozen=True)
class LineItem:
    description: str
    quantity: int
    unit_price: Decimal
    amount: Decimal


@dataclass(frozen=True)
class RatedInvoice:
    lines: list[LineItem]
    subtotal: Decimal
    tax: Decimal
    total: Decimal


def rate_usage(plan: PlanTerms, usage: dict[str, int], tax_rate: Decimal) -> RatedInvoice:
    """Rate one billing period.

    Rules:
      * The monthly plan fee is always charged.
      * Usage up to the plan allowance is free; each unit beyond it is charged
        at the plan's overage rate for that kind (voice, data, sms).
      * Each line is rounded to cents, the subtotal is the sum of the rounded
        lines, and tax is rounded once on the subtotal.
    """
    lines = [LineItem(f"Monthly plan fee ({plan.name})", 1, plan.monthly_fee, money(plan.monthly_fee))]

    for kind, (unit, allowance_field, rate_field) in USAGE_KINDS.items():
        used = usage.get(kind, 0)
        allowance = getattr(plan, allowance_field)
        overage_units = max(0, used - allowance)
        if overage_units == 0:
            continue
        unit_price = getattr(plan, rate_field)
        lines.append(
            LineItem(
                f"{kind} overage ({overage_units} {unit} over {allowance} included)",
                overage_units,
                unit_price,
                money(overage_units * unit_price),
            )
        )

    subtotal = sum((line.amount for line in lines), Decimal("0.00"))
    tax = money(subtotal * tax_rate)
    return RatedInvoice(lines=lines, subtotal=subtotal, tax=tax, total=subtotal + tax)


def parse_period(period: str) -> tuple[datetime, datetime]:
    """'2026-10' -> (2026-10-01 00:00, 2026-11-01 00:00), a half-open UTC interval.

    An event at exactly the next month's first instant belongs to the next
    period, so no event is ever billed twice or dropped.
    """
    try:
        year_text, month_text = period.split("-")
        if len(year_text) != 4 or len(month_text) != 2:
            raise ValueError
        year, month = int(year_text), int(month_text)
        start = datetime(year, month, 1)
    except ValueError:
        raise ValueError("period must look like YYYY-MM, e.g. 2026-10") from None
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    return start, end
