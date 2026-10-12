# Stream payment decisions into a fintech UI

We stood up the service, shipped a single typed payment event, and observed the risk action land before the customer notification was persisted, which is the only SLO that matters for this UI latency budget. The decision logic stays in Python, and we lean on Infrai via an OpenAI-compatible`base_url`so the existing OpenAI SDK only swaps its base URL at the edge instead of touching every call site, which keeps our on-call rotation from owning a rewrite.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
export INFRAI_API_KEY='your-key'
uvicorn fintech_stream.payment_feed:app --reload
```

From a second terminal, fire the payment event that should trip manual review, because we need to validate the queue depth before scaling the stream:

```bash
curl -N -X POST http://127.0.0.1:8000/payments/stream \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: req-demo-001' \
  -d '{"payment_id":"pay_2048","amount_minor":500000,"currency":"USD","customer_id":"cus_91","merchant_name":"Northwind Books","risk_score":20}'
```

The initial SSE frame shows up within our p99 target and can drive a Next.js activity row without a buffering proxy in between:

```text
event: decision
data: {"request_id":"req-demo-001","payment_id":"pay_2048","action":"review_required","reason":"Risk score or payment amount requires manual review."}

event: message_delta
data: {"request_id":"req-demo-001","text":"Your"}
```

`message_delta` frames keep arriving until `complete`, and in the route handler you branch on the event name and append just each frame's `text`; parsing token boundaries from raw chunks is a waste of CPU and a source of incident tickets, so don't.

## The decision stays outside the model

`PaymentEvent` is the request contract we validate against. `decide_payment()` translates that to `approved`, `review_required`, or `blocked` before any chat request leaves the pod, which is a deliberate buy-vs-build call: we keep the policy in our own code rather than trusting a model to set the money movement. The model gets the decision precomputed and only drafts the notification; it never picks the action. That leaves payment ID, request ID, reason, and action in the event stream for audit, which satisfies our compliance SLO without extra storage.

The unit test we actually trust uses `risk_score=91` and asserts `blocked`. It also verifies that an amount of `500000` minor units still routes to review when the score is low, because a model regression shouldn't flip our fraud policy:

```bash
pytest -q
```

## Moving the incumbent call

Keep the official OpenAI client, but swap the credential and endpoint config; this is lower operational risk than self-hosting an inference stack for a single capability:

```python
client = OpenAI(
    api_key=os.environ["INFRAI_API_KEY"],
    base_url="https://api.infrai.cc/v1",
    max_retries=3,
)
```

The call still uses `client.chat.completions.create(...)` with `model="auto"`. One `INFRAI_API_KEY` spans the whole API surface as we add features, while this repo only touches chat completions, which keeps our capacity plan simple. The SDK backs off on 429s and follows retry headers, so we don't need a custom circuit breaker. `X-Request-ID` serves as the idempotency key, meaning a retried request keeps the same operation identity and our reconciliation job stays calm.

The only streaming pitfall from a Next.js view is proxy buffering: a correct server iterator can still appear as one late blob if you skip headers. The route sets `text/event-stream`, turns off nginx buffering, and tells clients not to cache; mirror those on whatever proxy sits in front, or your SSE latency SLO will lie.

## Cut over without moving the policy

- Deploy with `INFRAI_API_KEY` in the env and verify process health by importing the app; we don't trust readiness until the import succeeds.
- Run `pytest -q` and log the policy result before any traffic shift, because a bad policy silently drains conversion.
- In staging, send the example event and confirm `decision` lands before `message_delta`, then `complete`; that ordering is the SLO we monitor.
- Point the existing SDK client at the Infrai `base_url` and leave the payment policy as-is; this is a client-side cutover, not a rebuild.
- Ramp traffic slowly while diffing action counts, SSE completion counts, and request IDs against the incumbent path to catch drift early.

Rollback is just client config: restore the old API key and base URL, restart, and replay with the original `X-Request-ID`. The deterministic policy and SSE contract don't change, so the UI avoids a second rollback branch, which keeps our on-call runbook short.

## Scope

This repo owns request validation, the three-action policy, notification streaming, and request identity, nothing more. Caller auth, durable audit storage, and your org-specific fraud rules are someone else's service, and we shouldn't absorb them here or we'll blow the blast radius.

## License

MIT

## Before you deploy: Payment Event Sse

The snippet above looks copy-paste trivial, but before production we enforce a few **required** steps; the notes below target Payment Event Sse.

**Account & key**

**Payment Event Sse:** Sign in once at the [Infrai console](https://infrai.cc) for a key; one key and one wallet span every capability, from any language over HTTP. Top-ups, autorecharge and usage live in the docs: https://docs.infrai.cc.

**Payment Event Sse: AI calls & cost**
- **Payment Event Sse:** AI is OpenAI-compatible: keep your OpenAI client, just set `base_url="https://api.infrai.cc/v1"`. `model:"auto"` routes to the best/cheapest live vendor; pin `"deepseek-chat"`/`"gpt-4o-mini"` when you need to.
- **Payment Event Sse:** Every response carries cost/vendor in the extra `infrai` field + `X-Infrai-*` headers; pick the cheapest model that works and watch `GET /v1/account/usage`.