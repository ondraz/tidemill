"""
Data models for subscription analytics.
"""
from pydantic import BaseModel
from datetime import datetime
from enum import Enum
from typing import Optional


class MetricType(str, Enum):
    """Types of metrics supported by the analytics engine."""
    MRR = "mrr"
    ARR = "arr"
    RENEWAL_RATE = "renewal_rate"
    LTV = "ltv"
    RETENTION = "retention"
    CHURN_RATE = "churn_rate"
    CUSTOMER_COUNT = "customer_count"


class MetricData(BaseModel):
    """Data point for a metric time series."""
    date: str
    value: float
    label: Optional[str] = None


class Customer(BaseModel):
    """Customer record from Stripe."""
    id: str
    email: str
    created_at: datetime
    name: Optional[str] = None
    description: Optional[str] = None


class Subscription(BaseModel):
    """Subscription record from Stripe."""
    id: str
    customer_id: str
    status: str
    current_period_start: datetime
    current_period_end: datetime
    created_at: datetime
    canceled_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    plan_id: str
    plan_amount: float
    plan_currency: str
    plan_interval: str


class Invoice(BaseModel):
    """Invoice record from Stripe."""
    id: str
    customer_id: str
    subscription_id: Optional[str] = None
    amount_paid: float
    currency: str
    created_at: datetime
    status: str
    period_start: datetime
    period_end: datetime
