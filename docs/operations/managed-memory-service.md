# Run the managed-memory development service

This is the Free / Pro / Team service foundation. It does not enable paid service
with dummy Stripe keys and does not change the local operator profile.

## Render pilot fallback

When Railway is unavailable, create a Render Blueprint from `render.yaml` on the
`feat/public-product-page` branch. The Blueprint provisions the managed container
on Render's Free plan. The Free plan has ephemeral storage, so this is suitable
for a UI/API pilot only; managed SQLite data can reset when the service restarts.

After Render assigns the service URL, set `CORTEX_MANAGED_PUBLIC_URL` to that
exact `https://` origin and redeploy. Keep `CORTEX_MANAGED_ALLOW_SIGNUP=false`
until SMTP is configured. Add Stripe test credentials and the Pro/Team test
Price IDs in Render's environment settings before enabling billing; placeholder
keys are intentionally rejected. Stripe webhooks should target
`/api/managed/stripe/webhook`.

## Local development

From a Cortex checkout with the sibling `integrity-core/integrity-sdk` available:

```sh
uv sync --extra managed --extra otel
npm --prefix viewer ci
npm --prefix viewer run build
export CORTEX_MANAGED_HOME="$HOME/.local/share/xibalba-cortex-managed-dev"
export CORTEX_MANAGED_PUBLIC_URL="http://localhost:8430"
export STRIPE_SECRET_KEY="sk_test_dummy"
uv run xibalba-cortex-managed --viewer-dist viewer/dist
```

Open `http://localhost:8430/managed`. The catalog shows Free $0, Pro $29 and Team
$149 per month. Paid actions are unavailable until real sandbox configuration is
complete. Registration defaults to disabled. This run uses a separate data home;
never point it at `~/.hermes/xibalba-cortex` or an existing operator profile.

The liveness endpoint is `GET /healthz`. Before a private pilot, query `GET /readyz`;
it returns `200` only when the selected HTTPS origin, real Stripe test resources,
SMTP delivery, verified signup and writable managed storage are configured. With the
development values above it returns `503` and names each open gate. Liveness does not
authorize customer traffic.

To enable email-verified signup and password recovery, configure the existing
STARTTLS SMTP delivery settings `CORTEX_SMTP_HOST`, `CORTEX_SMTP_PORT` (587 by default),
`CORTEX_SMTP_FROM`, and optional matching `CORTEX_SMTP_USERNAME`/`CORTEX_SMTP_PASSWORD`.
Then set `CORTEX_MANAGED_ALLOW_SIGNUP=true`. A default global cap of 20 signups per
UTC day limits initial provisioning; tune `CORTEX_MANAGED_SIGNUP_DAILY_LIMIT` after
capacity testing. Verification email is required before any workspace/API key access.

For the Vite development server instead of a built bundle, run the backend with
`CORTEX_MANAGED_PUBLIC_URL=http://localhost:5190`, then run:

```sh
VITE_CORTEX_EDITION=managed npm --prefix viewer run dev
```

Open `http://localhost:5190`. Managed development proxies `/api/managed` to the
managed backend and does not issue or inject a local operator token.

## Public contact form

Both the local and managed landing pages submit inquiries to `/api/contact` on
that page's own origin. Configure the SMTP settings above and optionally
`CORTEX_CONTACT_TO` (defaults to the public company contact,
`jacob.v.universe@gmail.com`) on the server that serves the page. The recipient
is server configuration, never a value supplied by the visitor.

Without SMTP, submission returns a delivery error and preserves the visitor's
message; the page also offers a direct email link. No inquiry is silently stored
for later delivery. The endpoint accepts bounded JSON and limits each client to
three attempts per fifteen minutes. If a reverse proxy sits in front of the API,
its client address may share that limit; forwarded headers are not trusted by
the local API. Test delivery in the chosen deployment before advertising the
form as available.

## Stripe sandbox configuration

Use the user's Stripe account, in test mode. Keep secrets out of source control.

1. Create monthly USD prices for Pro ($29) and Team ($149). Free has no Checkout
   subscription. Set `STRIPE_PRO_MONTHLY_PRICE_ID` and `STRIPE_TEAM_MONTHLY_PRICE_ID`.
2. Configure `STRIPE_SECRET_KEY` with an actual `sk_test_...` key and set the webhook
   signing secret as `STRIPE_WEBHOOK_SECRET=whsec_...`. Placeholder/dummy keys are
   intentionally rejected. `CORTEX_STRIPE_LIVE=false` stays the default.
3. Configure the Stripe customer portal for these two paid products/prices, invoice
   history, payment-method updates, cancellation, and plan changes. The app obtains
   short-lived portal sessions for the authenticated owner.
4. Register a webhook at the selected public HTTPS origin plus
   `/api/managed/stripe/webhook`, or forward Stripe CLI test events to localhost.
   Use snapshot events and the pinned API version `2025-06-30.basil`.
5. Subscribe to `checkout.session.completed`, `customer.subscription.created`,
   `customer.subscription.updated`, and `customer.subscription.deleted`.
6. Test checkout completion, authentication-required payment, duplicate delivery,
   upgrade, failed renewal, period-end cancellation, and retained export before
   considering live mode. Returning to the success URL alone grants no paid access.

The service validates each configured Price's amount/currency/monthly interval
against the approved catalog. A misconfigured price is rejected before Checkout.
API keys are used only on the backend. The app stores no card details.

Live mode requires explicitly setting `CORTEX_STRIPE_LIVE=true`, matching live
credentials/Price IDs and a live webhook secret. It has not been configured or tested
with live Stripe resources. Domain, hosting, inference budget and retention policy
remain separate launch decisions.

## Agent API

Sign in through the managed web workspace and create a 30-day workspace API key.
The raw key is shown once. List and revoke keys in the same panel. Credentials must
be supplied in an `Authorization: Bearer` header, never in a URL or query string.

- `POST /api/managed/memories`: JSON `{"content":"..."}` plus a unique
  `Idempotency-Key` header (8–128 characters). Identical retries reuse the memory
  and quota reservation; changing input under the same key is rejected.
- `GET /api/managed/memories?q=...`: bounded lexical search, or list up to 50 rows.
- `GET /api/managed/memories/<id>`: read one memory from the authenticated workspace.
- `GET /api/managed/memories/<id>/verify`: recompute and verify its event chain.
- `GET /api/managed/export?offset=0`: page all memory statuses, 100 rows at a time.
- `GET /api/managed/export-download`: streamed JSON attachment, with at most two
  export streams running simultaneously. Pause ingestion for a stable export.

Machine API keys cannot access billing, mint keys, or choose another tenant.
Cookie-authenticated mutations additionally require the session's CSRF token and
an Origin matching `CORTEX_MANAGED_PUBLIC_URL` exactly.

## Container template

The repository-scoped Docker build requires Compose 2.17+ and BuildKit named contexts.
The SDK is supplied separately rather than sending the parent Projects directory
as a build context.

```sh
cp deploy/managed/managed.env.example deploy/managed/.env
# Fill local environment values; do not add .env to Git.
docker compose -f deploy/managed/compose.yaml config --quiet
docker compose -f deploy/managed/compose.yaml up --build -d
```

Port 8430 binds to loopback. For a public pilot, terminate HTTPS at the chosen domain
and reverse proxy to this service. Match the configured public origin; retain the
managed-data volume and back up identity, control-plane and every tenant database.
Do not run multiple replicas or use ephemeral filesystems. Keep raw query-string
logging disabled because verification/recovery links contain one-time tokens.

The container template must be image-built and smoke-tested on the target host before
use; configuration validation and a Python/browser test run do not establish a
production deployment. No cloud infrastructure or Stripe account resources are
created by these files.
