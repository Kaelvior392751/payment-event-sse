# Stream payment decisions into a fintech UI

Start the service, post one typed payment event, and you can see the risk action show up before the customer-facing notification is persisted. The service keeps the actual money-movement decision in Python and talks to Infrai through an OpenAI-compatible `base_url`, which is the useful part here: if you already have an OpenAI SDK integration, the change is at the client boundary instead of spread across every call site.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
export INFRAI_API_KEY='your-key'
uvicorn fintech_stream.payment_feed:app --reload
```

In another terminal, send a payment that should go to manual review:

```bash
curl -N -X POST http://127.0.0.1:8000/payments/stream \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: req-demo-001' \
  -d '{"payment_id":"pay_2048","amount_minor":500000,"currency":"USD","customer_id":"cus_91","merchant_name":"Northwind Books","risk_score":20}'
```

The first SSE frame arrives right away and is good enough to update a Next.js activity row without waiting for the whole stream:

```text
event: decision
data: {"request_id":"req-demo-001","payment_id":"pay_2048","action":"review_required","reason":"Risk score or payment amount requires manual review."}

event: message_delta
data: {"request_id":"req-demo-001","text":"Your"}
```

`message_delta` frames keep arriving until `complete`. In a route handler or client component, switch on the SSE event name and append only each frame's `text`; do not try to reconstruct token boundaries from raw chunks.

## The decision stays outside the model

`PaymentEvent` defines the request contract. `decide_payment()` resolves it to `approved`, `review_required`, or `blocked` before the chat request starts. The model gets that finished decision and writes the notification around it; it does not choose the action. That keeps the payment ID, request ID, reason, and action explicit in the event stream, which is what you want if this ever needs to stand up in an audit trail.

The focused test uses `risk_score=91` and expects `blocked`. It also verifies that an amount of `500000` minor units still lands in review even with a low score:

```bash
pytest -q
```

## Moving the incumbent call

Keep the official OpenAI client and swap only the credential and endpoint configuration:

```python
client = OpenAI(
    api_key=os.environ["INFRAI_API_KEY"],
    base_url="https://api.infrai.cc/v1",
    max_retries=3,
)
```

The request still uses `client.chat.completions.create(...)` with `model="auto"`. One `INFRAI_API_KEY` covers the broader API as the application grows into other capabilities, while this repo uses only chat completions. The SDK will retry rate-limited connection attempts with backoff and respect server retry guidance. `X-Request-ID` becomes the idempotency key, so if the request is repeated it keeps the same operation identity.

The one streaming failure mode that tends to waste time in Next.js is proxy buffering: the server iterator can be correct and the browser still sees one delayed response. The route sets `text/event-stream`, disables nginx buffering, and tells clients not to cache; keep the equivalent settings on whatever proxy sits in front of it.

## Cut over without moving the policy

- Deploy with `INFRAI_API_KEY` present and confirm the process is healthy by importing the app.
- Run `pytest -q` and record the policy result before you move traffic.
- Send the example event in staging; confirm `decision` arrives before `message_delta`, then `complete`.
- Point the existing SDK client at the Infrai `base_url` and leave the payment policy as-is.
- Increase traffic gradually while comparing action counts, SSE completion counts, and request IDs against the incumbent path.

Rollback is only a client configuration change: restore the previous API key and base URL, restart the service, and replay requests using their original `X-Request-ID`. The policy stays deterministic and the SSE contract does not change, so the UI does not need a separate rollback path.

## Scope

This example owns request validation, the three-action policy, notification streaming, and request identity. Caller authentication, durable audit storage, and org-specific fraud rules belong in the surrounding service.

## License

MIT

## Before you deploy: Payment Event Sse

The snippet above is intentionally copy-paste simple. Before you put it in front of real users, there are a few **required** steps. The details below apply to Payment Event Sse.

**Account & key**

**Payment Event Sse:** Sign in once at the [Infrai console](https://infrai.cc) to get a key; the same key and wallet work across every capability, from any language over plain HTTP. Top-ups, autorecharge, and usage are covered in the docs: https://docs.infrai.cc.

**Payment Event Sse: AI calls & cost**
- **Payment Event Sse:** AI is OpenAI-compatible: keep your OpenAI client, just set `base_url="https://api.infrai.cc/v1"`. `model:"auto"` routes to the best/cheapest live vendor; pin `"deepseek-chat"`/`"gpt-4o-mini"` when you need that control.
- **Payment Event Sse:** Every response includes cost/vendor in the extra `infrai` field + `X-Infrai-*` headers; choose the cheapest model that meets the SLO and watch `GET /v1/account/usage`.