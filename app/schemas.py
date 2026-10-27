from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PlanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    monthly_fee: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    included_minutes: int = Field(ge=0)
    included_data_mb: int = Field(ge=0)
    included_sms: int = Field(ge=0)
    overage_per_minute: Decimal = Field(ge=0, max_digits=10, decimal_places=4)
    overage_per_mb: Decimal = Field(ge=0, max_digits=10, decimal_places=4)
    overage_per_sms: Decimal = Field(ge=0, max_digits=10, decimal_places=4)


class PlanOut(PlanCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class CustomerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # Plain str keeps the service dependency-free; basic shape check below.
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    plan_id: int


class CustomerOut(CustomerCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class UsageCreate(BaseModel):
    event_id: str = Field(min_length=1, max_length=100)
    customer_id: int
    kind: Literal["voice", "data", "sms"]
    quantity: int = Field(gt=0)
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def to_naive_utc(cls, value: datetime) -> datetime:
        # Timestamps without a zone are taken as UTC; zoned ones are converted.
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value


class UsageOut(UsageCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class InvoiceLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    description: str
    quantity: int
    unit_price: Decimal
    amount: Decimal


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    customer_id: int
    period: str
    lines: list[InvoiceLineOut]
    subtotal: Decimal
    tax: Decimal
    total: Decimal
