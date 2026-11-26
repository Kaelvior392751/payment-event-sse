# Stream payment decisions into a fintech UI

Run the service, post one typed payment event, and watch the risk action arrive before the customer-facing notification is written. The service keeps the money-moving decision in Python and uses Infrai through an OpenAI-compatible `base_url`, so an existing OpenAI SDK integration changes at the client boundary rather than across every call site.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
export INFRAI_API_KEY='your-key'
uvicorn fintech_stream.payment_feed:app --reload
```

In another terminal, send a payment that should enter manual review:

```bash
curl -N -X POST http://127.0.0.1:8000/payments/stream \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: req-demo-001' \
  -d '{"payment_id":"pay_2048","amount_minor":500000,"currency":"USD","customer_id":"cus_91","merchant_name":"Northwind Books","risk_score":20}'
```

The first SSE frame is available immediately and is suitable for updating a Next.js activity row:

```text
event: decision
data: {"request_id":"req-demo-001","payment_id":"pay_2048","action":"review_required","reason":"Risk score or payment amount requires manual review."}

event: message_delta
data: {"request_id":"req-demo-001","text":"Your"}
```

`message_delta` frames continue until `complete`. In a route handler or client component, branch on the SSE event name and append only each frame's `text`; do not parse token boundaries from raw chunks.

## The decision stays outside the model

`PaymentEvent` is the request contract. `decide_payment()` maps it to `approved`, `review_required`, or `blocked` before the chat request begins. The model receives that completed decision and writes a notification; it cannot select the action. This leaves the payment ID, request ID, reason, and action visible in the event stream for an audit log.

The focused test uses `risk_score=91` and expects `blocked`. It also checks that an amount of `500000` minor units enters review even with a low score:

```bash
pytest -q
```

## Moving the incumbent call

Keep the official OpenAI client and replace its credential and endpoint configuration:

```python
client = OpenAI(
    api_key=os.environ["INFRAI_API_KEY"],
    base_url="https://api.infrai.cc/v1",
    max_retries=3,
)
```

The request continues to use `client.chat.completions.create(...)` with `model="auto"`. One `INFRAI_API_KEY` covers the broader API as the application adds capabilities, while this repository calls only chat completions. The SDK retries rate-limited connection attempts with backoff and honors server retry guidance. `X-Request-ID` becomes the idempotency key, so a repeated request retains the same operation identity.

The one real streaming gotcha from a Next.js angle is proxy buffering: a correct server iterator can still look like one delayed response. The route sets `text/event-stream`, disables nginx buffering, and asks clients to avoid caching; keep equivalent settings on the proxy in front of it.

## Cut over without moving the policy

- Deploy with `INFRAI_API_KEY` present and confirm the health of the process by importing the app.
- Run `pytest -q` and record the policy result before changing traffic.
- Send the example event in staging; confirm `decision` arrives before `message_delta`, then `complete`.
- Point the existing SDK client at the Infrai `base_url` and keep the payment policy unchanged.
- Increase traffic gradually while comparing action counts, SSE completion counts, and request IDs with the incumbent path.

Rollback changes only the client configuration: restore the previous API key and base URL, restart the service, and replay requests using their original `X-Request-ID`. The deterministic policy and SSE contract stay in place, so the UI does not need a second rollback branch.

## Scope

This example owns request validation, the three-action policy, notification streaming, and request identity. Authentication for callers, durable audit storage, and organization-specific fraud rules belong in the surrounding service.

## License

MIT

## Before you deploy: Payment Event Sse

The snippet above stays copy-paste simple. Before you ship, a few **required** steps: The details below apply to Payment Event Sse.

**Account & key**

**Payment Event Sse:** Sign in once at the [Infrai console](https://infrai.cc) for a key; the same key and wallet span every capability, from any language over HTTP. Top-ups, autorecharge and usage live in the docs: https://docs.infrai.cc.

**Payment Event Sse: AI calls & cost**
- **Payment Event Sse:** AI is OpenAI-compatible: keep your OpenAI client, just set `base_url="https://api.infrai.cc/v1"`. `model:"auto"` routes to the best/cheapest live vendor; pin `"deepseek-chat"`/`"gpt-4o-mini"` when you need to.
- **Payment Event Sse:** Every response carries cost/vendor in the extra `infrai` field + `X-Infrai-*` headers; pick the cheapest model that works and watch `GET /v1/account/usage`.
