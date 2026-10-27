import os
from contextlib import asynccontextmanager
from decimal import Decimal

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from . import models, schemas
from .db import Base, engine, get_db
from .rating import PlanTerms, parse_period, rate_usage

TAX_RATE = Decimal(os.getenv("TAX_RATE", "0.0825"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Usage Rating & Invoicing Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/plans", response_model=schemas.PlanOut, status_code=201)
def create_plan(body: schemas.PlanCreate, db: Session = Depends(get_db)):
    plan = models.Plan(**body.model_dump())
    db.add(plan)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"A plan named '{body.name}' already exists") from None
    return plan


@app.post("/customers", response_model=schemas.CustomerOut, status_code=201)
def create_customer(body: schemas.CustomerCreate, db: Session = Depends(get_db)):
    if db.get(models.Plan, body.plan_id) is None:
        raise HTTPException(404, f"Plan {body.plan_id} not found")
    customer = models.Customer(**body.model_dump())
    db.add(customer)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"A customer with email '{body.email}' already exists") from None
    return customer


@app.post("/usage", response_model=schemas.UsageOut, status_code=201)
def record_usage(body: schemas.UsageCreate, response: Response, db: Session = Depends(get_db)):
    """Record one usage event. Re-sending the same event_id is safe (idempotent):
    an identical event returns 200 with the stored record; a different event
    reusing the id is rejected with 409 so billing data is never overwritten."""
    if db.get(models.Customer, body.customer_id) is None:
        raise HTTPException(404, f"Customer {body.customer_id} not found")

    def existing_event():
        return db.scalar(select(models.UsageEvent).where(models.UsageEvent.event_id == body.event_id))

    def resolve_duplicate(event):
        same = (event.customer_id, event.kind, event.quantity, event.occurred_at) == (
            body.customer_id, body.kind, body.quantity, body.occurred_at,
        )
        if not same:
            raise HTTPException(409, f"event_id '{body.event_id}' already used by a different event")
        response.status_code = 200
        return event

    event = existing_event()
    if event is not None:
        return resolve_duplicate(event)

    event = models.UsageEvent(**body.model_dump())
    db.add(event)
    try:
        db.commit()
    except IntegrityError:  # lost a race with a concurrent identical request
        db.rollback()
        return resolve_duplicate(existing_event())
    return event


@app.post("/customers/{customer_id}/invoices", response_model=schemas.InvoiceOut, status_code=201)
def generate_invoice(
    customer_id: int,
    response: Response,
    period: str = Query(..., description="Billing period, YYYY-MM"),
    db: Session = Depends(get_db),
):
    """Generate the invoice for one customer and month. Generating again for the
    same period returns the stored invoice (200) instead of billing twice."""
    customer = db.get(models.Customer, customer_id)
    if customer is None:
        raise HTTPException(404, f"Customer {customer_id} not found")
    try:
        start, end = parse_period(period)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None

    def existing_invoice():
        return db.scalar(
            select(models.Invoice)
            .options(selectinload(models.Invoice.lines))
            .where(models.Invoice.customer_id == customer_id, models.Invoice.period == period)
        )

    invoice = existing_invoice()
    if invoice is not None:
        response.status_code = 200
        return invoice

    totals = dict(
        db.execute(
            select(models.UsageEvent.kind, func.sum(models.UsageEvent.quantity))
            .where(
                models.UsageEvent.customer_id == customer_id,
                models.UsageEvent.occurred_at >= start,
                models.UsageEvent.occurred_at < end,  # half-open: next month's first instant is excluded
            )
            .group_by(models.UsageEvent.kind)
        ).all()
    )
    plan = customer.plan
    rated = rate_usage(
        PlanTerms(
            name=plan.name,
            monthly_fee=plan.monthly_fee,
            included_minutes=plan.included_minutes,
            included_data_mb=plan.included_data_mb,
            included_sms=plan.included_sms,
            overage_per_minute=plan.overage_per_minute,
            overage_per_mb=plan.overage_per_mb,
            overage_per_sms=plan.overage_per_sms,
        ),
        {kind: int(total) for kind, total in totals.items()},
        TAX_RATE,
    )

    invoice = models.Invoice(
        customer_id=customer_id,
        period=period,
        subtotal=rated.subtotal,
        tax=rated.tax,
        total=rated.total,
        lines=[
            models.InvoiceLine(
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                amount=line.amount,
            )
            for line in rated.lines
        ],
    )
    db.add(invoice)
    try:
        db.commit()
    except IntegrityError:  # concurrent request generated it first
        db.rollback()
        response.status_code = 200
        return existing_invoice()
    # Return the stored form so a new invoice reads exactly like a fetched one
    # (e.g. unit_price scale), instead of the in-memory pre-save values.
    db.expire_all()
    return existing_invoice()


@app.get("/invoices/{invoice_id}", response_model=schemas.InvoiceOut)
def get_invoice(invoice_id: int, db: Session = Depends(get_db)):
    invoice = db.scalar(
        select(models.Invoice).options(selectinload(models.Invoice.lines)).where(models.Invoice.id == invoice_id)
    )
    if invoice is None:
        raise HTTPException(404, f"Invoice {invoice_id} not found")
    return invoice
