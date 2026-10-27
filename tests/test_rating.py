from decimal import Decimal

import pytest

from app.rating import PlanTerms, money, parse_period, rate_usage

TAX = Decimal("0.0825")


def make_plan(**overrides) -> PlanTerms:
    values = dict(
        name="Standard",
        monthly_fee=Decimal("40.00"),
        included_minutes=300,
        included_data_mb=5000,
        included_sms=100,
        overage_per_minute=Decimal("0.10"),
        overage_per_mb=Decimal("0.02"),
        overage_per_sms=Decimal("0.05"),
    )
    values.update(overrides)
    return PlanTerms(**values)


def test_no_usage_charges_only_the_plan_fee_plus_tax():
    invoice = rate_usage(make_plan(), {}, TAX)
    assert [line.amount for line in invoice.lines] == [Decimal("40.00")]
    assert invoice.subtotal == Decimal("40.00")
    assert invoice.tax == Decimal("3.30")
    assert invoice.total == Decimal("43.30")


def test_usage_exactly_at_the_allowance_is_free():
    invoice = rate_usage(make_plan(), {"voice": 300, "data": 5000, "sms": 100}, TAX)
    assert len(invoice.lines) == 1  # plan fee only, no overage lines


def test_one_unit_over_the_allowance_is_charged():
    invoice = rate_usage(make_plan(), {"voice": 301}, TAX)
    overage = invoice.lines[1]
    assert overage.quantity == 1
    assert overage.amount == Decimal("0.10")
    assert "voice overage" in overage.description


def test_overage_on_all_three_kinds():
    invoice = rate_usage(make_plan(), {"voice": 320, "data": 5100, "sms": 130}, TAX)
    assert [line.amount for line in invoice.lines] == [
        Decimal("40.00"), Decimal("2.00"), Decimal("2.00"), Decimal("1.50"),
    ]
    assert invoice.subtotal == Decimal("45.50")
    assert invoice.tax == Decimal("3.75")  # 3.75375 rounded to cents
    assert invoice.total == Decimal("49.25")


def test_line_rounding_is_half_up_not_bankers_rounding():
    # 5 sms x 0.0050 = 0.025 exactly; half-up gives 0.03 (half-even would give 0.02)
    plan = make_plan(included_sms=0, overage_per_sms=Decimal("0.0050"))
    invoice = rate_usage(plan, {"sms": 5}, TAX)
    assert invoice.lines[1].amount == Decimal("0.03")


def test_tax_is_rounded_half_up_once_on_the_subtotal():
    plan = make_plan(monthly_fee=Decimal("0.10"))
    invoice = rate_usage(plan, {}, Decimal("0.05"))  # tax = 0.005 exactly
    assert invoice.tax == Decimal("0.01")
    assert invoice.total == Decimal("0.11")


def test_total_always_equals_sum_of_rounded_lines_plus_tax():
    plan = make_plan(overage_per_mb=Decimal("0.0033"))
    invoice = rate_usage(plan, {"data": 5000 + 777}, TAX)
    assert invoice.subtotal == sum(line.amount for line in invoice.lines)
    assert invoice.total == invoice.subtotal + invoice.tax


def test_free_plan_has_a_zero_fee_line_and_no_tax():
    invoice = rate_usage(make_plan(monthly_fee=Decimal("0.00")), {}, TAX)
    assert invoice.subtotal == Decimal("0.00")
    assert invoice.tax == Decimal("0.00")
    assert invoice.total == Decimal("0.00")


def test_all_amounts_are_decimal_never_float():
    invoice = rate_usage(make_plan(), {"voice": 999}, TAX)
    for line in invoice.lines:
        assert isinstance(line.amount, Decimal)
    assert isinstance(invoice.total, Decimal)


@pytest.mark.parametrize(
    "value, expected",
    [("0.005", "0.01"), ("0.004", "0.00"), ("1.005", "1.01"), ("2.675", "2.68")],
)
def test_money_rounds_half_up(value, expected):
    assert money(Decimal(value)) == Decimal(expected)


def test_parse_period_returns_a_half_open_month():
    start, end = parse_period("2026-10")
    assert (start.year, start.month, start.day) == (2026, 10, 1)
    assert (end.year, end.month, end.day) == (2026, 11, 1)


def test_parse_period_rolls_december_into_next_year():
    start, end = parse_period("2026-12")
    assert (end.year, end.month, end.day) == (2027, 1, 1)


@pytest.mark.parametrize("bad", ["2026-13", "2026-00", "2026-1", "26-10", "abc", "2026/10", "", "2026-10-01"])
def test_parse_period_rejects_malformed_input(bad):
    with pytest.raises(ValueError, match="YYYY-MM"):
        parse_period(bad)
