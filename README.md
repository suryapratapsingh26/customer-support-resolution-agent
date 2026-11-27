# Customer Support Resolution Agent

An agentic AI system that investigates customer support issues, retrieves relevant business policies, proposes resolutions, executes approved actions, and records verified outcomes.

## Project Status

🚧 In development

## Overview

This project simulates a customer support system for a fictional online electronics retailer.

The system will handle customer issues such as:

- Order status
- Refund requests
- Damaged items

The goal is to demonstrate how an AI agent can work with business data, policies, APIs, and human approval while keeping sensitive actions controlled and auditable.

## Tech Stack

- Python
- LangGraph
- FastAPI
- PostgreSQL
- pgvector
- Docker

## Architecture

The system will consist of:

- **FastAPI** — API layer and request handling
- **LangGraph** — Agent workflow orchestration
- **PostgreSQL** — Application data, workflow state, approvals, and audit records
- **RAG** — Retrieval of applicable support policies
- **Mock Services** — Simulated payment, shipping, and ticketing APIs

## Key Principles

The project separates AI reasoning from business-critical execution.

The AI can:

- Investigate customer issues
- Retrieve relevant information
- Retrieve applicable policies
- Propose resolutions

Application code is responsible for:

- Authentication and authorization
- Ownership checks
- Financial calculations
- Eligibility enforcement
- Approval validation
- External API execution
- Retry and idempotency controls
- State transitions

## Initial Scope

The first version will:

- Use synthetic customer and business data
- Support one store and one currency
- Require human approval for refunds
- Use mock payment and shipping services
- Support one customer issue per workflow
- Keep customer communication inside the demo application

Complex cases such as chargebacks, fraud adjudication, and partial returns are outside the initial scope.

## Project Goals

The project aims to demonstrate:

1. Agentic workflow design
2. API and system integration
3. Retrieval-augmented generation
4. Human-in-the-loop approval
5. Safe execution of financial actions
6. Idempotent and recoverable workflows
7. Auditable system behavior
8. Evaluation based on verified business outcomes

## Knowledge retrieval (RAG)

The knowledge service indexes Markdown, plain text, and text-based PDFs. It extracts and normalizes text, splits it into overlapping chunks, embeds chunks locally with `sentence-transformers/all-MiniLM-L6-v2`, and persists vectors plus source metadata in a ChromaDB collection. Query text uses the same model. Search results include similarity distance and source metadata; context assembly labels each excerpt with its document and category for later grounded agent answers.

```mermaid
flowchart LR
  A[Policy files] --> B[Load and normalize]
  B --> C[Chunk with source metadata]
  C --> D[Local sentence-transformer]
  D --> E[(Persistent ChromaDB)]
  Q[Search query] --> D
  E --> F[Filtered top-k retrieval]
  F --> G[Source-labelled context]
```

### Add and index knowledge

Put `.md`, `.txt`, or text-based `.pdf` files under `knowledge_base/`. Use a category subdirectory such as `refunds/`, `shipping/`, or `faqs/`; the subdirectory name becomes the searchable category. The sample files are explicitly marked as synthetic demonstration policies. Scanned PDFs require OCR, which is not included.

Configure `KNOWLEDGE_BASE_DIR`, `CHROMA_PERSIST_DIR`, `CHROMA_COLLECTION_NAME`, `EMBEDDING_MODEL_NAME`, `EMBEDDING_DEVICE`, `KNOWLEDGE_CHUNK_SIZE`, `KNOWLEDGE_CHUNK_OVERLAP`, `KNOWLEDGE_TOP_K`, and `KNOWLEDGE_CONTEXT_MAX_CHARS` through the environment. Defaults use the repository's `knowledge_base/`, `.data/chroma/`, and the local MiniLM model. The first embedding run needs the model available in the local Hugging Face cache (otherwise the library downloads it).

Run ingestion as often as needed; unchanged content hashes are skipped and changed files replace their existing chunks:

```powershell
python -m pip install -e .
python scripts/ingest_knowledge_base.py
```

Example API calls (server: `uvicorn app.main:app --reload`):

```http
POST /api/v1/knowledge/ingest
Content-Type: application/json

{"filename": "refunds/refund-eligibility.md"}
```

Omit the body to ingest the configured directory. Other endpoints are `GET /api/v1/knowledge/documents`, `GET /api/v1/knowledge/documents/{document_id}`, `DELETE /api/v1/knowledge/documents/{document_id}`, and `POST /api/v1/knowledge/search` with `{"query":"When will an approved refund arrive?","top_k":5,"category":"refunds"}`. Search responses contain source-labelled context and chunk distances, never embedding vectors or absolute source paths.

Run the project test suite with `python -m pytest`. Unit tests use fake embedders/stores; the Chroma persistence integration test runs when ChromaDB is installed. A semantic end-to-end test can use a locally cached model when `RUN_REAL_EMBEDDING_TESTS=1`.

## Resolution recommendation workflow

`POST /api/v1/tickets/{ticket_id}/resolution-recommendation` invokes a LangGraph `StateGraph`. Its nodes load the ticket, gather customer/order/item/payment/refund/shipment context, classify the issue and note missing records, search the existing knowledge service, ask the configured LLM for a recommendation, and validate the structured response. A missing ticket ends at the conditional ticket-input branch and returns HTTP 404. Provider, retrieval, or workflow failures return HTTP 503.

The recommendation is advisory. The graph has no payment, refund, order, shipment, or ticket mutation calls. The model is instructed not to decide refund eligibility or authoritative amounts, and the workflow always sets `human_review_recommended` to true. Returned policy sources retain chunk IDs and available document metadata.

The LLM adapter uses an OpenAI-compatible Chat Completions endpoint. Configure `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL`, and `LLM_TIMEOUT_SECONDS`; `LLM_BASE_URL` defaults to `https://api.openai.com/v1`, model defaults to `gpt-4o-mini`, and no key is required for the rest of the application. Copy `.env.example` to `.env` and supply a key locally. The API key is never returned to clients or included in application error messages.

Example:

```http
POST /api/v1/tickets/42/resolution-recommendation
```

The response includes `ticket_id`, `issue_category`, `issue_summary`, `customer_context_summary`, `retrieved_knowledge_sources`, `proposed_resolution`, `explanation`, `confidence_score`, `missing_information`, `human_review_recommended`, `action_required`, and `required_action`. Refund tickets set `action_required=true` and `required_action=refund_approval_review`; the recommendation graph pauses at this handoff and cannot execute the refund. Run the workflow tests with `python -m pytest tests/unit/test_agent_workflow.py`; these use an injected fake LLM and do not call a provider.

## Agent tools and refund approvals

Validated read-only support tools are in `app/tools/support.py`: customer/order lookup, payment and refund history, shipment tracking, deterministic refundable-balance checks, and order/shipping action preparation. Lookups verify the customer owns the order and associated ticket/payment/shipment. The order and shipping preparation tools only return proposals because no corresponding mutation services exist.

Refund approvals are persisted in `refund_approvals` and move through `pending -> approved -> executed` or `pending -> rejected`. A payment may have only one active (pending or approved) approval at a time. Create and review requests using the following operator endpoints:

| Method and path | Purpose |
| --- | --- |
| `POST /api/v1/refund-approvals/tickets/{ticket_id}` | Create a pending request with `order_id`, `payment_id`, `requested_amount`, `policy_basis`, and `reason` |
| `GET /api/v1/refund-approvals/pending` | List pending requests |
| `GET /api/v1/refund-approvals/{approval_id}` | View a request |
| `POST /api/v1/refund-approvals/{approval_id}/approve` | Approve with `{"confirm_policy_review": true}` |
| `POST /api/v1/refund-approvals/{approval_id}/reject` | Reject with `{"reason": "..."}` |
| `POST /api/v1/refund-approvals/{approval_id}/execute` | Resume the DB-backed workflow; runs only after approval |
| `GET /api/v1/refund-approvals/{approval_id}/execution` | View the resulting refund |

Request creation requires `X-Approval-Request-Token` matching `APPROVAL_REQUEST_API_KEY` and records `APPROVAL_REQUEST_ACTOR_ID`. Listing, viewing, approving, rejecting, executing, and reading results require `X-Approval-Token` matching `APPROVAL_API_KEY` and record `APPROVAL_ACTOR_ID`. Both distinct credentials must be configured with at least 32 characters, and the actor IDs must differ; the application disables these operations if role separation is misconfigured. The creator cannot approve their own request. All actor identities come from configuration rather than caller-supplied actor fields. Request amounts must come from trusted support/customer input, never LLM-generated amounts. Keep both credentials in a secret manager. This is a two-service shared-secret authorization model for the demo; replace it with per-user identity/role authorization before multi-operator production use.

The allowed `policy_basis` values are `unused_original_packaging`, `faulty_item`, `incorrect_item`, `partial_return`, `missing_item`, and `price_adjustment`. Approval creation, approval, and execution recheck ticket/order/payment ownership, successful payment status, and remaining captured balance in application code. For `unused_original_packaging`, the application enforces the 30-day delivery window; for `faulty_item` and `incorrect_item`, it enforces 90 days using the earliest recorded shipment delivery timestamp as a conservative order-level proxy. The schema does not link items to shipments or record return receipt/item condition, so the approving operator must explicitly confirm manual policy review. The approved request amount is checked against the current refundable balance again at execution. The execution transaction creates the refund and marks the approval executed together, uses an approval-scoped idempotency key, and leaves the approval approved if execution fails. The LLM cannot approve a refund or supply its authoritative amount. Refund recommendations use a fixed review handoff; a separate LangGraph resume graph re-reads persistent approval status and cannot resume from stale in-memory state.

Run approval/tool tests with `python -m pytest tests/unit/test_refund_approvals.py tests/unit/test_support_tools.py tests/api/test_refund_approvals_api.py`. Run the complete test suite with `python -m pytest`.

## Customer support agent API

The conversation API persists sessions, customer/assistant messages, execution state, and the structured recommendation (including retrieved policy citations) in `agent_sessions`, `agent_messages`, and `agent_executions`. A session is bound to one ticket and customer. Session creation and every customer-facing route validate that relationship. Requests require both `X-Agent-API-Key` and a short-lived `X-Agent-Customer-Token`; configure `AGENT_API_KEY` and the independent `AGENT_CUSTOMER_TOKEN_SECRET` with random secrets of at least 32 characters. The trusted upstream identity service authenticates the user and signs a customer scope token as `{customer_id}.{expiry_unix}.{hex_hmac_sha256}`, where the HMAC covers `{customer_id}.{expiry_unix}` and uses `AGENT_CUSTOMER_TOKEN_SECRET`. Tokens must expire within ten minutes. The API rejects tokens scoped to a different path customer ID, so the service key alone cannot select arbitrary customer records. Keep the signing secret only in the trusted identity service and this API. Approval review remains separately authenticated with the approval credentials described above.

| Method and path | Purpose |
| --- | --- |
| `POST /api/v1/customers/{customer_id}/tickets/{ticket_id}/agent-sessions` | Create or idempotently retrieve a session with `{"idempotency_key":"session-..."}` |
| `GET /api/v1/customers/{customer_id}/agent-sessions/{session_id}` | Read session and active execution status |
| `GET /api/v1/customers/{customer_id}/agent-sessions/{session_id}/messages` | Read conversation history |
| `POST /api/v1/customers/{customer_id}/agent-sessions/{session_id}/messages` | Submit `{"content":"Where is my order?","idempotency_key":"message-..."}` and run the recommendation workflow |
| `GET /api/v1/customers/{customer_id}/agent-executions/{execution_id}` | Read an execution |
| `GET /api/v1/customers/{customer_id}/tickets/{ticket_id}/agent-executions` | List ticket executions |
| `POST /api/v1/customers/{customer_id}/agent-executions/{execution_id}/cancel` | Cancel an eligible execution |
| `POST /api/v1/agent-executions/{execution_id}/resume` | Resume after review with `{"approval_id":123}`; requires the approval operator credential |

Supply both scope headers on session, message, read, and cancellation requests. Creation returns 201 (200 for an idempotent replay); message submission returns 200 after a recommendation, 202 while waiting for approval, and 503 with an execution ID if processing failed. A waiting response contains an action proposal only; it does not create an approval or execute a refund. Create and review the refund using the existing `/api/v1/refund-approvals` endpoints, then resume using its persistent approval ID. Resume reloads and verifies that approval in the existing refund workflow; only that service can execute a refund.

Executions move through `pending -> running -> completed`, `waiting_for_approval`, or `failed`; a failed execution can be retried by resubmitting through a new message, while eligible executions can be cancelled. A session allows one active execution at a time. Idempotency keys prevent duplicate session creation and message processing. A cancelled in-flight recommendation will not overwrite the cancellation when it returns. Cancellation does not interrupt an approved refund transaction. Ticket status is never changed by this API.

Example:

```http
POST /api/v1/customers/7/tickets/42/agent-sessions
X-Agent-API-Key: <configured service secret>
X-Agent-Customer-Token: <signed token scoped to customer 7>
Content-Type: application/json

{"idempotency_key":"session-customer-7-001"}
```

```http
POST /api/v1/customers/7/agent-sessions/15/messages
X-Agent-API-Key: <configured service secret>
X-Agent-Customer-Token: <signed token scoped to customer 7>
Content-Type: application/json

{"content":"My order has not arrived.","idempotency_key":"message-customer-7-001"}
```

The message response includes the persisted message, structured recommendation, source metadata/excerpts, execution status, proposed action, approval reference when resumed, and sanitized error information. The conversation API uses the existing recommendation graph and read-only support tools; the LLM has no mutation tool access. Run agent service tests with `python -m pytest tests/unit/test_agent_api_service.py tests/unit/test_agent_workflow.py`.

## Customer support dashboard

The React, TypeScript, and Vite application lives in `frontend/`. It is organized into route pages in `src/App.tsx`, shared layout/status components in `src/components/`, typed API services in `src/api/`, dashboard loading logic in `src/hooks/`, and shared backend contracts in `src/types.ts`. The interface includes an overview, searchable/status-filtered ticket queue, authenticated ticket/customer/order/payment/refund/shipment context, a persistent agent conversation with saved recommendation citations and execution refresh/cancellation, a customer-scoped refund request/history view, and a reviewer workspace for approval history, decisions, execution, and verified results.

Install and run it from the frontend directory:

```powershell
cd frontend
npm install
npm run dev
npm test
npm run build
```

The dashboard uses the same-origin FastAPI BFF under `/api/bff`; it no longer depends on `window.supportDashboardHost`. Configure a provider-neutral OIDC authorization-code client and return the callback to `OIDC_REDIRECT_URI`. The BFF performs discovery, validates the signed ID token against issuer, audience, configured signing algorithms, required time/identity claims, nonce, state, and PKCE, then stores an opaque session token hash in the database. The browser receives only a Secure/HttpOnly/SameSite=Lax session cookie and a CSRF token for state-changing requests. Login state is bound to a short-lived HttpOnly browser cookie. Raw provider tokens are not retained.

Set `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, and `OIDC_REDIRECT_URI`. Optionally set `OIDC_JWKS_URL`; otherwise the BFF uses the issuer discovery document. Configure `OIDC_ROLES_CLAIM` and `OIDC_CUSTOMER_IDS_CLAIM` to point to signed ID-token claims. The roles claim must contain `support_agent` and/or `support_reviewer` (configurable through `OIDC_AGENT_ROLE` and `OIDC_REVIEWER_ROLE`). The customer IDs claim is a list of positive integer IDs authorized for that identity. Reviewers require the reviewer role; customer access still requires an authorized customer ID. The identity provider must issue these claims only after applying the organization's own customer assignment policy.

Generate independent high-entropy secrets for `BACKEND_SERVICE_API_KEY`, `AGENT_API_KEY`, and `AGENT_CUSTOMER_TOKEN_SECRET`. The service API key protects direct customer, ticket, order, and knowledge routes; the BFF attaches the agent API key and customer-scoped HMAC token only to its internal agent API call. Refund approval actions call the existing approval service with the verified OIDC subject and require the reviewer role, CSRF token, trusted origin, and the existing requester/reviewer separation. These credentials must remain server-side and must not be placed in `VITE_*` variables or browser storage.

Configure `BFF_TRUSTED_ORIGINS` to the exact dashboard origin(s), `BFF_SESSION_TTL_SECONDS` for session lifetime, and `BFF_SESSION_COOKIE_NAME` as needed. Set `BFF_SESSION_COOKIE_SECURE=true` in production and serve both dashboard and API over HTTPS. For local HTTP development only, use `BFF_SESSION_COOKIE_SECURE=false`, set the trusted origin to `http://localhost:5173`, and run the API at `http://localhost:8000`. `frontend/.env.example` uses the same-origin `/api/bff` base path; Vite proxies that path to the local API. Do not expose internal `/api/v1` service endpoints directly to untrusted clients.

The BFF provides `/auth/status`, `/auth/login`, `/auth/callback`, `/auth/logout`; customer-authorized ticket context at `GET /customers/{customer_id}/tickets/{ticket_id}/context`; agent-session and execution routes; and customer-scoped refund request/history routes. Reviewers can use `GET /refund-approvals/pending`, `GET /refund-approvals/history`, and `/refund-approvals/{approval_id}` for approval review, `POST /refund-approvals/{approval_id}/execute` to execute an approved request, and `POST /agent-executions/{execution_id}/resume` to resume a matching waiting run. The browser never supplies reviewer identity or backend credentials. Every state-changing BFF call requires the session CSRF token and a trusted origin. The agent proposes a review handoff only; staff provide request amount/reason, deterministic services validate eligibility, a different authorized reviewer approves, and execution uses the existing idempotent refund service. See the API docs at `/docs` for request and response schemas after configuring the application.

### Optional local Keycloak identity provider

The `keycloak` service is guarded by the `local-oidc` Compose profile and is bound only to `127.0.0.1`; ordinary `docker compose up` does not start it. It uses the development-only Keycloak 26.8.2 container, imports `customer-support-dev` at startup, and overwrites the imported placeholder client/user passwords from `.env.keycloak`. Keycloak realm import is skipped if the realm already exists, as designed by Keycloak; remove/re-import only the local realm when changing the imported realm definition. This profile and its sample credentials are for local development only and must not be enabled in a deployed environment.

On a fresh checkout, first configure the regular local database and application values in `.env` as described above. Then create the separate local identity-provider file and launch the profile:

```powershell
Copy-Item .env.keycloak.example .env.keycloak
docker compose --env-file .env --env-file .env.keycloak --profile local-oidc up --build --wait -d
docker compose exec backend python scripts/seed_mock_services.py
```

Set `POSTGRES_PASSWORD`, `APP_DB_PASSWORD`, and `MIGRATION_DB_PASSWORD` in `.env` before startup. `.env.keycloak.example` contains explicitly local-only sample credentials that are not production secrets; change them if the machine is shared. The imported client secret is set from `OIDC_CLIENT_SECRET` at Keycloak startup, and the app receives that same local value through its backend-only environment. The realm has a confidential OIDC client with PKCE S256 and the exact redirect `http://localhost:8080/api/bff/auth/callback`.

The browser uses `http://localhost:8081` for the login page and callback round-trip. The backend discovers Keycloak through `http://keycloak:8080`; the Keycloak hostname configuration keeps the OIDC issuer and browser authorization endpoint at the localhost URL while using the Docker-network backchannel for token and JWKS requests. Keep `OIDC_ISSUER` set to `http://localhost:8081/realms/customer-support-dev`; do not set it to the Docker-only `keycloak` hostname. This split preserves issuer validation and does not add a login bypass.

Local test users are `dev-agent` and `dev-reviewer`. Their sample passwords are in `.env.keycloak.example`; the bootstrap admin is only for `http://localhost:8081/admin`. The agent user receives the `support_agent` realm role and the reviewer receives `support_reviewer`. Both receive the configured positive `OIDC_DEV_CUSTOMER_IDS` claim as an integer array in their ID token. The example uses IDs `1,2,3`, matching the three customers created by `scripts/seed_mock_services.py` in a fresh database. For an existing DB, set the variable to actual customer IDs. These identity roles still pass through the same signed ID-token validation, server-side role checks, customer scope checks, CSRF checks, and self-approval prevention as any configured OIDC provider.

Troubleshooting:

- Verify the browser-visible discovery document at `http://localhost:8081/realms/customer-support-dev/.well-known/openid-configuration`; its `issuer` must match `OIDC_ISSUER` and its authorization endpoint must use `localhost:8081`.
- If the login redirect or callback is rejected, verify the exact redirect URI in `.env.keycloak` and the realm client, then restart the profile.
- If backend discovery/JWKS fails, confirm `OIDC_BACKCHANNEL_BASE_URL=http://keycloak:8080`, that the Keycloak service is healthy, and that the backend shares the `frontend_backend` network.
- If login succeeds but no customers/tickets appear, align `OIDC_DEV_CUSTOMER_IDS` with DB IDs and run the seed command above.
- Inspect local-only logs with `docker compose --profile local-oidc logs keycloak`. Realm import runs only when the realm is absent; for an import-definition reset, delete only `customer-support-dev` using the local Keycloak admin console and restart Keycloak. Do not remove PostgreSQL volumes to reset Keycloak.

Keycloak containers, users, URLs, and credentials are local-only. No mock-authentication path or authenticated user is added to the application. The production deployment continues to use its separately configured OIDC provider and does not start the profile unless explicitly requested.

Frontend tests cover dashboard rendering, ticket search/filtering and context, agent session/message and citation display, refund request and history, approval/rejection/execution, and authentication/error handling. Run `npm test` and `npm run build` from `frontend/`. The backend suite remains `python -m pytest` from the repository root.

## Container deployment and operations

### Architecture and prerequisites

The backend container runs FastAPI/Uvicorn as an unprivileged `app` user. The frontend container builds the Vite application and serves it with Nginx; Nginx forwards same-origin `/api/` requests to the backend, so browser code receives no backend credentials. PostgreSQL is on a data-only internal network and its data is stored in a named volume. A one-shot `migrate` service runs Alembic after PostgreSQL is healthy and before the API service starts; API replicas never run migrations at startup. The API connects with a restricted runtime role; only the migration job uses the schema-owner role, and a separate bootstrap account initializes the roles on a fresh Compose volume. Chroma vectors and the Hugging Face model cache use separate persistent volumes.

Requirements: Docker Engine with the Compose v2 plugin, and OpenSSL for generating local secrets. For production, use an HTTPS ingress/load balancer in front of the dashboard container, a managed PostgreSQL service with encrypted backups, a real OIDC provider, and an LLM provider. Payment and shipping are still repository mocks.

### Local Compose startup

```sh
cp .env.example .env
openssl rand -hex 32 # create separate values for POSTGRES_PASSWORD and each server credential
# Edit .env: use a different generated value for every REPLACE_* entry.
docker compose up --build -d
docker compose ps
```

Open `http://localhost:8080`. OIDC sign-in will remain unavailable until a provider is configured and its client is registered with the callback URL in `.env`. For developer-only, host-run API use, install with `python -m pip install -e ".[dev]"`, set `DATABASE_URL` to a separately installed/local PostgreSQL instance, then run `uvicorn app.main:app --reload`; run the frontend separately with `cd frontend && npm ci && npm run dev`. The Vite development proxy targets `http://127.0.0.1:8000` unless `BFF_TARGET` is set. Compose does not publish PostgreSQL on a host port.

### Environment and production configuration

`.env.example` documents all application settings and contains placeholders, not usable secrets. Keep `.env` out of source control. At minimum production requires:

- `DATABASE_URL` using `postgresql+psycopg` and a reachable PostgreSQL server.
- `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, and HTTPS `OIDC_REDIRECT_URI` ending in `/api/bff/auth/callback`. The ID token must include the configured role and positive integer customer ID claims (`OIDC_ROLES_CLAIM`, `OIDC_CUSTOMER_IDS_CLAIM`). Register the exact callback and trusted origins with the provider and identity administrators; this repository does not configure a real IdP.
- Independent random values of at least 32 characters for `BACKEND_SERVICE_API_KEY`, `AGENT_API_KEY`, `AGENT_CUSTOMER_TOKEN_SECRET`, `APPROVAL_API_KEY`, and `APPROVAL_REQUEST_API_KEY`. The configuration validator rejects reused service secrets and identical requester/reviewer identities.
- Distinct `APPROVAL_ACTOR_ID` and `APPROVAL_REQUEST_ACTOR_ID`, an `LLM_API_KEY`, and an HTTPS `LLM_BASE_URL`.
- `BFF_SESSION_COOKIE_SECURE=true` and `BFF_TRUSTED_ORIGINS` containing only exact HTTPS dashboard origins. Terminate TLS at a trusted ingress; expose the dashboard publicly and keep backend/PostgreSQL ports private. Do not place any server credential in a `VITE_*` variable.

Non-development startup fails if required values are missing or insecure. Local Compose defaults to development mode and HTTP only; never use that mode for an internet-facing deployment. Configure `ENVIRONMENT=production`, HTTPS OIDC callback/origins, and the secure cookie flag in the deployment secret manager. Use hex-encoded database passwords because Compose builds the connection URL from PostgreSQL environment variables.

### Migrations and schema validation

Never run migrations against an existing production database as an experiment. Back it up first, then run the one-shot migration job during a controlled release:

```sh
docker compose run --rm migrate
# or, from a configured Python environment:
alembic upgrade head
```

Compose runs the job once before starting this stack's backend. In multi-replica deployments, run the migration job once in the release pipeline before scaling/restarting API replicas. The app does not auto-migrate. To validate the full migration graph on a disposable, initially empty PostgreSQL database, use a database name ending in `_migration_test`:

```sh
$env:MIGRATION_TEST_DATABASE_URL='postgresql+psycopg://user:password@localhost:5432/customer_support_migration_test'
python scripts/validate_migrations.py
```

The script refuses an existing application schema, applies all revisions, checks critical tables/indexes/foreign keys/JSON type, downgrades the latest revision, then reapplies head. CI runs this against a fresh PostgreSQL service. SQLite unit/API tests do not substitute for this database-specific check.

### Backups, restores, and application rollback

For Compose, create a logical backup before upgrading:

```sh
docker compose exec -T db pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB" > support-$(date +%F-%H%M%S).dump
```

Restore into a separately provisioned database first, verify it, and then direct the application at that database. For the Compose demo, run backup and restore commands with the bootstrap account from the database container; production managed PostgreSQL should use its backup/PITR tooling:

```sh
docker compose exec -T db pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists < support-backup.dump
```

Treat restore as destructive to the selected target database: confirm its name and contents before running `--clean`. Prefer managed PostgreSQL snapshots/PITR for production and test restores regularly. The Compose bootstrap superuser is `POSTGRES_USER`; its password is only used by the database service and is not passed to the API or migration containers. The runtime user is `APP_DB_USER`; Alembic connects as `MIGRATION_DB_USER`. Existing volumes are not reinitialized, so provision and grant these roles explicitly when adopting an existing database. Roll back an application deployment by redeploying the prior immutable image. Do not automatically downgrade a production schema: forward-fix or restore a tested backup unless the specific migration's downgrade has been reviewed against data written by the newer app.

### Health, logs, and shutdown

- `GET /health/live` reports process liveness without exposing configuration.
- `GET /health/ready` executes `SELECT 1`; it returns a generic 503 while PostgreSQL is unavailable.
- Legacy `GET /health` remains a liveness alias.
- Backend logs are structured JSON with timestamp, level, logger, and message. Request bodies, cookies, authorization headers, and exception payloads are not added by the application logger. Uvicorn handles SIGTERM and graceful worker shutdown; the app disposes its SQLAlchemy engine at shutdown.

Check a local stack with `docker compose ps` and `curl -fsS http://localhost:8080/health/ready`. Troubleshoot failed startup with `docker compose logs db migrate backend frontend`; redact credentials and customer data before sharing logs. A failed migration blocks backend startup by design. After changing environment values, recreate the affected services (`docker compose up -d --force-recreate backend frontend`).

### Automated validation and real-infrastructure status

Run backend unit/API tests with `python -m pytest -q`, Python compilation with `python -m compileall -q app migrations tests scripts`, frontend tests/build with `cd frontend && npm ci && npm test && npm run build`, and Compose parsing with `docker compose config --quiet`. The GitHub Actions workflow runs backend tests and compilation, PostgreSQL migration upgrade/downgrade/re-upgrade validation, plus frontend tests and production build.

The BFF dashboard workflow tests use a test database and mock the LLM response; OIDC callback tests mock discovery/token/JWKS verification, and payment/shipping operations use local mock services. Only the PostgreSQL migration job uses a real PostgreSQL server in CI. No real identity provider, LLM account, payment processor, carrier service, or production environment is exercised by those tests.

### Production limitations and release checklist

Before deployment, the operator must configure real OIDC clients/claims and HTTPS ingress, secret-manager values, a production LLM endpoint, PostgreSQL backup/restore, monitoring/alerting, and payment/shipping adapters. The included payment and shipping services are mocks and must not be used to represent actual settlements or parcel events. Refund eligibility also lacks item-condition and return-receipt records; a reviewer must verify those facts. The application is deployment-ready as a containerized demo, but this change does not deploy it to production or claim that external integrations are configured.

- [ ] Production HTTPS origin, OIDC issuer/audience/client/callback, role/customer claims verified
- [ ] Independent secrets stored in secret manager; secure session cookie enabled
- [ ] Managed PostgreSQL connectivity, migration reviewed, backup and restore rehearsed
- [ ] LLM provider and knowledge data/model availability confirmed
- [ ] Mock payment/shipping adapters replaced and their idempotency/failure behavior tested
- [ ] Health/readiness, logs, alerts, ingress limits, and rollback plan verified
