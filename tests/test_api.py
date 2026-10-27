from decimal import Decimal

PLAN = {
    "name": "Standard",
    "monthly_fee": "40.00",
    "included_minutes": 300,
    "included_data_mb": 5000,
    "included_sms": 100,
    "overage_per_minute": "0.10",
    "overage_per_mb": "0.02",
    "overage_per_sms": "0.05",
}


def make_customer(client, email="ana@example.com", plan=None):
    plan_id = client.post("/plans", json=plan or PLAN).json()["id"]
    return client.post("/customers", json={"name": "Ana", "email": email, "plan_id": plan_id}).json()["id"]


def usage(client, customer_id, event_id, kind, quantity, occurred_at):
    return client.post(
        "/usage",
        json={
            "event_id": event_id, "customer_id": customer_id,
            "kind": kind, "quantity": quantity, "occurred_at": occurred_at,
        },
    )


def invoice(client, customer_id, period):
    return client.post(f"/customers/{customer_id}/invoices", params={"period": period})


def amounts(response):
    return [Decimal(line["amount"]) for line in response.json()["lines"]]


# ---- plans & customers -------------------------------------------------------

def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_duplicate_plan_name_is_rejected(client):
    assert client.post("/plans", json=PLAN).status_code == 201
    assert client.post("/plans", json=PLAN).status_code == 409


def test_negative_plan_fee_is_rejected(client):
    assert client.post("/plans", json={**PLAN, "monthly_fee": "-1.00"}).status_code == 422


def test_customer_needs_an_existing_plan(client):
    response = client.post("/customers", json={"name": "Ana", "email": "ana@example.com", "plan_id": 999})
    assert response.status_code == 404


def test_duplicate_customer_email_is_rejected(client):
    make_customer(client)
    plan_id = client.post("/plans", json={**PLAN, "name": "Other"}).json()["id"]
    response = client.post("/customers", json={"name": "Ana 2", "email": "ana@example.com", "plan_id": plan_id})
    assert response.status_code == 409


def test_invalid_email_is_rejected(client):
    plan_id = client.post("/plans", json=PLAN).json()["id"]
    response = client.post("/customers", json={"name": "Ana", "email": "not-an-email", "plan_id": plan_id})
    assert response.status_code == 422


# ---- usage ingestion ---------------------------------------------------------

def test_usage_event_is_recorded(client):
    cid = make_customer(client)
    response = usage(client, cid, "e1", "voice", 10, "2026-10-05T12:00:00")
    assert response.status_code == 201
    assert response.json()["quantity"] == 10


def test_resending_the_same_event_is_idempotent(client):
    cid = make_customer(client)
    assert usage(client, cid, "e1", "voice", 400, "2026-10-05T12:00:00").status_code == 201
    assert usage(client, cid, "e1", "voice", 400, "2026-10-05T12:00:00").status_code == 200
    # the duplicate must not be counted twice: 400 min -> 100 over allowance -> $10.00
    result = invoice(client, cid, "2026-10")
    assert amounts(result)[1] == Decimal("10.00")


def test_reusing_an_event_id_for_a_different_event_is_a_conflict(client):
    cid = make_customer(client)
    usage(client, cid, "e1", "voice", 10, "2026-10-05T12:00:00")
    assert usage(client, cid, "e1", "voice", 99, "2026-10-05T12:00:00").status_code == 409


def test_usage_for_unknown_customer_is_404(client):
    assert usage(client, 42, "e1", "voice", 10, "2026-10-05T12:00:00").status_code == 404


def test_zero_or_negative_quantity_is_rejected(client):
    cid = make_customer(client)
    assert usage(client, cid, "e1", "voice", 0, "2026-10-05T12:00:00").status_code == 422
    assert usage(client, cid, "e2", "voice", -5, "2026-10-05T12:00:00").status_code == 422


def test_unknown_usage_kind_is_rejected(client):
    cid = make_customer(client)
    assert usage(client, cid, "e1", "fax", 1, "2026-10-05T12:00:00").status_code == 422


# ---- invoicing ---------------------------------------------------------------

def test_invoice_with_no_usage_is_just_the_plan_fee(client):
    cid = make_customer(client)
    response = invoice(client, cid, "2026-10")
    assert response.status_code == 201
    body = response.json()
    assert (Decimal(body["subtotal"]), Decimal(body["tax"]), Decimal(body["total"])) == (
        Decimal("40.00"), Decimal("3.30"), Decimal("43.30"),
    )


def test_invoice_totals_overage_across_events_and_kinds(client):
    cid = make_customer(client)
    usage(client, cid, "a", "voice", 200, "2026-10-02T09:00:00")
    usage(client, cid, "b", "voice", 120, "2026-10-20T09:00:00")  # 320 total -> 20 over
    usage(client, cid, "c", "data", 5100, "2026-10-10T09:00:00")  # 100 over
    usage(client, cid, "d", "sms", 130, "2026-10-11T09:00:00")  # 30 over
    body = invoice(client, cid, "2026-10").json()
    assert [Decimal(line["amount"]) for line in body["lines"]] == [
        Decimal("40.00"), Decimal("2.00"), Decimal("2.00"), Decimal("1.50"),
    ]
    assert Decimal(body["total"]) == Decimal("49.25")


def test_month_boundary_is_half_open(client):
    cid = make_customer(client)
    usage(client, cid, "last", "voice", 400, "2026-10-31T23:59:59")  # October
    usage(client, cid, "first", "voice", 400, "2026-11-01T00:00:00")  # November
    assert amounts(invoice(client, cid, "2026-10"))[1] == Decimal("10.00")
    assert amounts(invoice(client, cid, "2026-11"))[1] == Decimal("10.00")
    # nothing double-billed: each event shows up in exactly one invoice
    assert amounts(invoice(client, cid, "2026-09")) == [Decimal("40.00")]


def test_timezone_offsets_are_converted_to_utc_before_billing(client):
    cid = make_customer(client)
    # 20:00 on Oct 31 at UTC-5 is 01:00 UTC on Nov 1 -> belongs to November
    usage(client, cid, "tz", "voice", 400, "2026-10-31T20:00:00-05:00")
    assert amounts(invoice(client, cid, "2026-10")) == [Decimal("40.00")]
    assert amounts(invoice(client, cid, "2026-11"))[1] == Decimal("10.00")


def test_generating_an_invoice_twice_returns_the_same_invoice(client):
    cid = make_customer(client)
    usage(client, cid, "a", "voice", 400, "2026-10-02T09:00:00")
    first = invoice(client, cid, "2026-10")
    second = invoice(client, cid, "2026-10")
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]


def test_usage_added_after_invoicing_does_not_change_the_issued_invoice(client):
    cid = make_customer(client)
    first = invoice(client, cid, "2026-10").json()
    usage(client, cid, "late", "voice", 900, "2026-10-15T09:00:00")
    again = invoice(client, cid, "2026-10").json()
    assert again["total"] == first["total"]


def test_customers_are_billed_only_for_their_own_usage(client):
    a = make_customer(client, "a@example.com")
    b = client.post(
        "/customers",
        json={"name": "Ben", "email": "b@example.com", "plan_id": 1},
    ).json()["id"]
    usage(client, a, "ea", "voice", 400, "2026-10-02T09:00:00")
    assert amounts(invoice(client, b, "2026-10")) == [Decimal("40.00")]
    assert amounts(invoice(client, a, "2026-10"))[1] == Decimal("10.00")


def test_invalid_period_is_rejected(client):
    cid = make_customer(client)
    assert invoice(client, cid, "2026-13").status_code == 422
    assert invoice(client, cid, "October").status_code == 422


def test_invoice_for_unknown_customer_is_404(client):
    assert invoice(client, 777, "2026-10").status_code == 404


def test_get_invoice_by_id(client):
    cid = make_customer(client)
    created = invoice(client, cid, "2026-10").json()
    fetched = client.get(f"/invoices/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == created
    assert client.get("/invoices/9999").status_code == 404
