# Usage Rating & Invoicing Service

A small billing backend for a mobile carrier: it records usage (voice, data, SMS),
rates it against each customer's plan, and generates monthly invoices through a REST API.
Built with Python, FastAPI, SQLAlchemy and PostgreSQL.

The focus is billing correctness: decimal money, half-up rounding, month boundaries,
time zones, and safe retries (idempotency). The rules are written down in
[docs/requirements.md](docs/requirements.md) and each one has an automated test.

## How it works
```
POST /usage  ->  usage_events  --(sum per kind for the month)-->  rate_usage()  ->  invoice + lines
```
- `app/rating.py` is pure logic (no database, no web), so every rule is unit tested directly.
- `app/main.py` holds the REST endpoints; `app/models.py` the PostgreSQL/SQLite schema.
- Database constraints back up the rules: unique `event_id` (no double-counted usage),
  unique (customer, period) (one invoice per month), `quantity > 0`.

## Run it
```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt     # Windows; use .venv/bin/pip elsewhere
.venv/Scripts/python -m uvicorn app.main:app --reload  # SQLite, zero setup
```
Interactive API docs: http://127.0.0.1:8000/docs

With PostgreSQL 16 in Docker (API on :8000, database exposed on host port 5433):
```bash
docker compose up --build
```

## Example
```bash
curl -X POST localhost:8000/plans -H "content-type: application/json" -d '{
  "name":"Standard","monthly_fee":"40.00","included_minutes":300,"included_data_mb":5000,
  "included_sms":100,"overage_per_minute":"0.10","overage_per_mb":"0.02","overage_per_sms":"0.05"}'
curl -X POST localhost:8000/customers -H "content-type: application/json" \
  -d '{"name":"Ana","email":"ana@example.com","plan_id":1}'
curl -X POST localhost:8000/usage -H "content-type: application/json" -d '{
  "event_id":"evt-1","customer_id":1,"kind":"voice","quantity":320,"occurred_at":"2026-10-05T12:00:00Z"}'
curl -X POST "localhost:8000/customers/1/invoices?period=2026-10"
```
320 minutes on a 300-minute plan: $40.00 fee + 20 x $0.10 overage = $42.00, + 8.25% tax = **$45.47**.

## Tests
```bash
.venv/Scripts/python -m pytest --cov=app --cov-report=term-missing
```
The same suite also runs against a real PostgreSQL 16 server (the tables are dropped and
recreated for every test, so use a throwaway database):
```bash
docker compose up -d db
docker exec billing-service-db-1 psql -U billing -d billing -c "CREATE DATABASE billing_test;"
TEST_DATABASE_URL=postgresql+psycopg2://billing:billing@127.0.0.1:5433/billing_test .venv/Scripts/python -m pytest
```
Covers allowance boundaries, rounding (half-up vs banker's), month boundaries, time-zone
conversion, duplicate events, conflicting events, repeat invoice generation, customer
isolation and input validation.

## Design notes
- **Money is `Decimal`, never float.** Lines are rounded to cents, subtotal = sum of lines,
  tax is rounded once on the subtotal.
- **Half-open months.** An event at exactly the next month's first instant belongs to the
  next month, so nothing is billed twice or dropped.
- **Idempotent writes.** Retrying a usage event or an invoice request is safe; a different
  event reusing an `event_id` is a 409, so stored billing data is never overwritten.
- **Consistent reads.** A new invoice is returned in its stored form, so it matches a later `GET`.
  (A test caught a scale mismatch here, `40.00` vs `40.0000`, which is now fixed.)

## Not included
Payments, mid-month plan changes/proration, discounts, authentication, PDF invoices.
