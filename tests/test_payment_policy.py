from fintech_stream.payment_policy import PaymentAction, PaymentEvent, decide_payment


def payment(risk_score: int, amount_minor: int = 12_500) -> PaymentEvent:
    return PaymentEvent(
        payment_id="pay_2048",
        amount_minor=amount_minor,
        currency="USD",
        customer_id="cus_91",
        merchant_name="Northwind Books",
        risk_score=risk_score,
    )


def test_high_risk_payment_is_blocked_before_notification_generation() -> None:
    decision = decide_payment(payment(risk_score=91))

    assert decision.action is PaymentAction.BLOCKED
    assert decision.reason == "Risk score meets the block threshold."


def test_large_payment_requires_review_even_with_low_risk_score() -> None:
    decision = decide_payment(payment(risk_score=20, amount_minor=500_000))

    assert decision.action is PaymentAction.REVIEW_REQUIRED

