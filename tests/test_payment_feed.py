import json
from types import SimpleNamespace
from unittest.mock import Mock

from fintech_stream import payment_feed
from fintech_stream.payment_policy import PaymentEvent


def test_empty_choice_chunk_does_not_interrupt_completion(monkeypatch) -> None:
    client = Mock()
    client.chat.completions.create.return_value = iter(
        [
            SimpleNamespace(choices=[]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Ready"))]),
            SimpleNamespace(choices=[]),
        ]
    )
    monkeypatch.setattr(payment_feed, "infrai_client", lambda: client)
    event = PaymentEvent(
        payment_id="pay_2048",
        amount_minor=500_000,
        currency="USD",
        customer_id="cus_91",
        merchant_name="Northwind Books",
        risk_score=20,
    )

    frames = list(payment_feed.stream_payment(event, "req-test"))

    assert [frame.split("\n", 1)[0] for frame in frames] == [
        "event: decision",
        "event: message_delta",
        "event: complete",
    ]
    assert json.loads(frames[1].split("data: ", 1)[1])["text"] == "Ready"
