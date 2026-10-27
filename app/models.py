from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    monthly_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    included_minutes: Mapped[int] = mapped_column(Integer)
    included_data_mb: Mapped[int] = mapped_column(Integer)
    included_sms: Mapped[int] = mapped_column(Integer)
    overage_per_minute: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    overage_per_mb: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    overage_per_sms: Mapped[Decimal] = mapped_column(Numeric(10, 4))


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320), unique=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    plan: Mapped[Plan] = relationship()


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_usage_quantity_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Client-supplied id: lets the same event be re-sent safely (idempotency).
    event_id: Mapped[str] = mapped_column(String(100), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # voice | data | sms
    quantity: Mapped[int] = mapped_column(Integer)  # minutes, MB or messages
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # naive UTC


class Invoice(Base):
    __tablename__ = "invoices"
    # One invoice per customer per period: generating twice returns the same one.
    __table_args__ = (UniqueConstraint("customer_id", "period", name="uq_invoice_customer_period"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    period: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    tax: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    lines: Mapped[list["InvoiceLine"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceLine.id"
    )


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    description: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    invoice: Mapped[Invoice] = relationship(back_populates="lines")
