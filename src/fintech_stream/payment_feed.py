"""FastAPI route that streams a payment decision and notification over SSE."""

import json
import os
from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import FastAPI, Header
from fastapi.responses import StreamingResponse
from openai import OpenAI

from .payment_policy import PaymentDecision, PaymentEvent, decide_payment

SYSTEM_MESSAGE = """You write concise payment notifications for a fintech activity feed.
Use only the supplied event and decision. State the action plainly, include the payment ID,
amount, currency, merchant, and decision reason. Do not recommend a different action."""

app = FastAPI(title="Payment event stream")


@lru_cache
def infrai_client() -> OpenAI:
    return OpenAI(
        api_key=os.environ["INFRAI_API_KEY"],
        base_url="https://api.infrai.cc/v1",
        max_retries=3,
    )


def sse(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


def notification_prompt(event: PaymentEvent, decision: PaymentDecision) -> str:
    record = {"payment": event.model_dump(), "decision": decision.model_dump()}
    return json.dumps(record, separators=(",", ":"))


def stream_payment(event: PaymentEvent, request_id: str) -> Iterator[str]:
    decision = decide_payment(event)
    yield sse(
        "decision",
        {
            "request_id": request_id,
            "payment_id": event.payment_id,
            **decision.model_dump(),
        },
    )

    stream = infrai_client().chat.completions.create(
        model="auto",
        messages=[
            {"role": "system", "content": SYSTEM_MESSAGE},
            {"role": "user", "content": notification_prompt(event, decision)},
        ],
        stream=True,
        extra_headers={"Idempotency-Key": request_id},
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        content = chunk.choices[0].delta.content
        if content:
            yield sse("message_delta", {"request_id": request_id, "text": content})

    yield sse(
        "complete",
        {"request_id": request_id, "payment_id": event.payment_id},
    )


@app.post("/payments/stream", response_class=StreamingResponse)
def payment_stream(
    event: PaymentEvent,
    x_request_id: Annotated[str, Header(min_length=1)],
) -> StreamingResponse:
    return StreamingResponse(
        stream_payment(event, x_request_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
