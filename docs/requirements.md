# Business Requirements: Usage Rating & Invoicing Service

**Version:** 1.0  **Status:** Implemented and tested  **Owner:** Somesh Kennedy

## 1. Purpose
Customers on a mobile plan generate usage (voice minutes, data, text messages). The
business needs a service that records that usage and produces a correct monthly
invoice: the plan fee plus charges for anything used beyond the plan's allowance.

## 2. Scope
**In scope:** plan and customer setup, usage ingestion, monthly invoice generation,
invoice retrieval.
**Out of scope:** payments, proration for mid-month plan changes, discounts/promotions,
multi-currency, authentication, PDF invoices.

## 3. Actors
| Actor | Needs |
|---|---|
| Network/usage source | Send usage events, including safe retries after failures |
| Billing operator | Create plans and customers, generate and look up invoices |
| Customer | Receive an accurate, explainable invoice |

## 4. Functional requirements
| ID | Requirement | Endpoint |
|---|---|---|
| FR-1 | Create a plan with a monthly fee, allowances and per-unit overage rates | `POST /plans` |
| FR-2 | Create a customer assigned to an existing plan | `POST /customers` |
| FR-3 | Record a usage event (voice, data or sms) for a customer | `POST /usage` |
| FR-4 | Generate the invoice for one customer and one month | `POST /customers/{id}/invoices?period=YYYY-MM` |
| FR-5 | Retrieve a stored invoice | `GET /invoices/{id}` |

## 5. Business rules
| ID | Rule |
|---|---|
| BR-1 | The plan fee is charged every month, even with no usage. |
| BR-2 | Usage up to the plan allowance is free; each unit above it is charged at the plan's overage rate for that kind. |
| BR-3 | Money uses decimal arithmetic (never floating point), rounded half-up to cents. |
| BR-4 | Each invoice line is rounded to cents; the subtotal is the sum of the rounded lines; tax is rounded once on the subtotal. |
| BR-5 | A billing month is the half-open interval [first day 00:00 UTC, first day of next month 00:00 UTC). An event at exactly the next month's start belongs to the next month. |
| BR-6 | Timestamps with a time-zone offset are converted to UTC before assigning a month. |
| BR-7 | Re-sending a usage event with the same `event_id` and identical content must not double-count it. The same `event_id` with different content is rejected. |
| BR-8 | There is exactly one invoice per customer per month. Generating again returns the stored invoice; later usage does not change an issued invoice. |
| BR-9 | Usage quantity must be a positive whole number; fees and rates cannot be negative. |

## 6. Non-functional requirements
- **Correctness first:** every business rule above has an automated test.
- **Safe retries:** usage ingestion and invoice generation are idempotent, including
  when two identical requests arrive at the same time (database unique constraints).
- **Consistency:** an invoice reads identically when first generated and when fetched later.
- **Portability:** runs on SQLite with no setup, and on PostgreSQL 16 via Docker.

## 7. Acceptance criteria
1. An invoice with no usage equals the plan fee plus tax.
2. Usage exactly at the allowance adds no overage line; one unit over adds a charge.
3. A duplicate usage event does not change the invoice total.
4. An event at 23:59:59 on the last day of a month appears only on that month's invoice,
   and one at 00:00:00 the next day appears only on the next month's invoice.
5. An event at `2026-10-31T20:00:00-05:00` is billed in November (01:00 UTC on Nov 1).
6. Generating the same invoice twice returns the same invoice id.
7. Invalid input (bad period, negative or zero quantity, unknown customer or plan,
   duplicate plan name or email) returns a clear 4xx error.

## 8. Assumptions
- Tax is a single flat rate (default 8.25%, configurable with `TAX_RATE`).
- Usage arrives already measured in whole minutes, MB or messages.
- Every customer has exactly one plan for the whole period.
