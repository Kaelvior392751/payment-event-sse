"""Deterministic payment risk policy used before model narration."""

from enum import StrEnum

from pydantic import BaseModel, Field


class PaymentEvent(BaseModel):
    payment_id: str = Field(min_length=1)
    amount_minor: int = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    customer_id: str = Field(min_length=1)
    merchant_name: str = Field(min_length=1)
    risk_score: int = Field(ge=0, le=100)


class PaymentAction(StrEnum):
    APPROVED = "approved"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"


class PaymentDecision(BaseModel):
    action: PaymentAction
    reason: str


def decide_payment(event: PaymentEvent) -> PaymentDecision:
    """Keep the money-moving decision deterministic and auditable."""
    if event.risk_score >= 85:
        return PaymentDecision(
            action=PaymentAction.BLOCKED,
            reason="Risk score meets the block threshold.",
        )
    if event.risk_score >= 60 or event.amount_minor >= 500_000:
        return PaymentDecision(
            action=PaymentAction.REVIEW_REQUIRED,
            reason="Risk score or payment amount requires manual review.",
        )
    return PaymentDecision(
        action=PaymentAction.APPROVED,
        reason="Payment is within automatic approval thresholds.",
    )

