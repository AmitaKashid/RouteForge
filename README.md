# RouteForge

**Cost- and Quality-Aware Multi-Provider LLM Gateway**

RouteForge is an LLM control plane that sits between applications and language-model providers. Instead of letting each application choose a model directly, RouteForge evaluates each request against **quality, latency, cost, governance, availability, and feature-policy constraints**, selects the lowest-cost eligible model, executes it through a normalized provider interface, and records the decision for audit and cost accounting.

The project addresses a production problem: once multiple teams and models share the same inference infrastructure, model selection stops being a simple API call. It becomes an operational decision involving **cost control, reliability, tenant limits, provider health, and quality assurance**.

> **Current status:** active development. The repository already contains deterministic routing, a FastAPI gateway, mock and Ollama execution, PostgreSQL-backed audit and budget state, Redis-backed rate limiting and circuit state, retry/fallback behavior, and sampled asynchronous quality verification. Shadow-policy evaluation and the final observability/load-testing milestone remain.

---

## What RouteForge Solves

A typical LLM application starts with one provider and one model. That works initially, but creates predictable problems as usage grows:

- expensive models are used for requests cheaper models could handle;
- teams lack centralized budget and rate-limit enforcement;
- provider outages propagate directly to users;
- routing decisions are difficult to explain after the fact;
- quality can silently degrade when cheaper models are introduced;
- every application team reimplements the same reliability and governance logic.

RouteForge centralizes these concerns at the gateway boundary.

For each request, the gateway answers:

1. **Which models are allowed for this feature and governance context?**
2. **Which candidates satisfy the requested quality, latency, and cost limits?**
3. **Which eligible candidate has the lowest estimated cost?**
4. **Is the selected provider-model pair healthy enough to use?**
5. **Can the authenticated team admit and afford the request?**
6. **If execution fails, can RouteForge retry or fall back without weakening constraints?**
7. **Should the completed response be sampled for asynchronous quality verification?**

The result is a routing decision that is **deterministic, explainable, and auditable**.

---

## Core Capabilities

| Capability | What RouteForge does | Why it matters |
| --- | --- | --- |
| **Policy-aware routing** | Filters models by feature policy, request constraints, capabilities, governance, quality, latency, cost, and provider state | Cost optimization never bypasses product or governance requirements |
| **Deterministic selection** | Chooses the lowest-cost eligible candidate with stable tie-breaking | Routing behavior stays reproducible and testable |
| **Provider abstraction** | Normalizes model execution behind a common provider contract | Routing logic stays independent of provider-specific APIs |
| **Measured model profiles** | Builds versioned routing profiles from repeatable offline benchmarks | Runtime routing can be backed by evidence rather than arbitrary constants |
| **Team authentication** | Resolves team identity from Bearer API keys and stores only key digests | Establishes tenant identity without persisting recoverable secrets |
| **Rate limiting** | Uses Redis for per-team request and estimated-token limits | Protects shared inference capacity |
| **Budget enforcement** | Uses PostgreSQL for monthly budgets, cost reservation, and reconciliation | Makes economic controls durable and concurrency-safe |
| **Retry and fallback** | Retries bounded transient failures and re-routes when policy allows | Improves resilience without silently relaxing constraints |
| **Circuit breaking** | Tracks passive `CLOSED`, `OPEN`, and `HALF_OPEN` state per provider-model pair | Stops repeatedly failing backends from receiving normal traffic |
| **Inference audit trail** | Records candidates, selection, token usage, latency, cost, retries, fallback, and execution attempts | Makes routing decisions inspectable |
| **Async quality verification** | Samples completed requests and compares them with a fixed reference model outside the response path | Measures whether cheaper routing preserves quality |

---

## Architecture

```mermaid
flowchart LR
    C[Client Application] --> API[FastAPI Gateway]

    API --> AUTH[Team Authentication]
    AUTH --> RL[Redis Rate Limits]
    RL --> REG[Model + Policy Registries]
    REG --> ROUTER[Deterministic Router]

    ROUTER --> CIRCUIT[Redis Circuit State]
    CIRCUIT --> ROUTER
    ROUTER --> BUDGET[PostgreSQL Budget Reservation]

    BUDGET --> EXEC[Inference Coordinator]
    EXEC --> MOCK[Deterministic Mock Provider]
    EXEC --> OLLAMA[Ollama Provider]

    EXEC --> RETRY[Bounded Retry / Fallback]
    RETRY --> EXEC

    EXEC --> LEDGER[(PostgreSQL Inference Ledger)]
    EXEC --> RESP[Normalized Chat Completion]
    RESP --> C

    EXEC --> SAMPLE{Verification Sample?}
    SAMPLE -->|yes| STREAM[(Redis Stream)]
    STREAM --> WORKER[Verification Worker]
    WORKER --> REF[Reference Model]
    REF --> VERIFY[(PostgreSQL Quality Verification)]
```

### Durable vs. transient state

| State | Storage | Rationale |
| --- | --- | --- |
| Teams, API-key digests, limits, budgets, inference records, verification results | **PostgreSQL** | Must survive restarts and remain auditable |
| Rate counters, circuit state, probe locks, verification queue | **Redis** | High-frequency transient operational state |
| Model definitions and routing policies | **Versioned JSON** | Reviewable in Git and deterministic to load |
| Measured routing profiles | **Versioned offline-generated files** | Prevents runtime self-modification of evidence |

A central architectural rule is that the **routing engine remains pure**. It does not query PostgreSQL, inspect Redis, or call providers. Infrastructure state is resolved by the application layer and supplied to the router as explicit inputs.

---

## Request Lifecycle

A successful request follows this sequence:

```text
1. Authenticate the team
2. Apply request and token rate limits
3. Resolve the active feature policy
4. Load permitted model definitions
5. Read provider-model circuit state
6. Build candidate quality, latency, and cost estimates
7. Evaluate candidate eligibility
8. Select the lowest-cost eligible model
9. Reserve estimated cost against the team budget
10. Execute the selected provider-model pair
11. Retry bounded transient failures when permitted
12. Re-route to another eligible candidate if fallback is allowed
13. Reconcile reserved cost against actual token usage
14. Persist the routing and execution audit record
15. Return the normalized response
16. Optionally enqueue asynchronous quality verification
```

Fallback is not a hardcoded backup. RouteForge performs another constrained routing decision with the failed provider-model pair excluded. If no remaining candidate satisfies the original requirements, the request fails rather than silently weakening policy.

---

## Routing Model

RouteForge separates **eligibility** from **selection**.

A candidate can be rejected because of:

- feature-policy restrictions;
- missing capabilities;
- minimum quality requirements;
- maximum latency requirements;
- maximum estimated request cost;
- governance restrictions;
- provider operating state;
- explicit model pinning.

Only candidates that survive all checks are eligible.

Among eligible candidates, RouteForge selects the one with the lowest estimated cost. Equal-cost candidates are resolved deterministically by model ID.

> **Cost optimization happens only inside the safe set of eligible models.**

---

## Reliability Semantics

### Retryable failures

Examples:

- provider timeout;
- rate limiting;
- connection failure;
- transient provider unavailability.

These failures may receive a bounded retry with exponential backoff. After retry exhaustion, the router may select another eligible candidate if fallback is enabled.

### Non-retryable failures

Examples:

- authentication failure;
- invalid provider request;
- unsupported model;
- malformed provider response;
- domain or policy violations.

These stop execution. RouteForge does not hide invalid requests or configuration defects by trying unrelated models.

### Circuit breaker

Circuit state is maintained independently for each `(provider, model)` pair.

| State | Routing meaning | Behavior |
| --- | --- | --- |
| `CLOSED` | Healthy | Receives normal traffic |
| `OPEN` | Unavailable | Rejected before execution |
| `HALF_OPEN` | Degraded | One controlled recovery probe may test the pair |

The health signal is passive: normal inference outcomes update the circuit. V1 does not require a separate provider-polling service.

---

## Quality Verification

Cost-aware routing is useful only if quality remains acceptable. RouteForge therefore treats routing quality as something to **measure**, not assume.

For deterministic feature types, a configured percentage of successful requests can be sampled after the user-facing response is complete. Sampling is deterministic: request and policy identifiers are hashed into a stable basis-point bucket.

A sampled verification job is placed on a Redis Stream. A background worker calls a fixed reference model and stores the comparison result in PostgreSQL.

Current deterministic comparison strategies include:

- **`NORMALIZED_EXACT`** — suited to classification and short deterministic answers;
- **`JSON_FIELD_AGREEMENT`** — compares structured JSON leaf fields using stable semantics.

A quality disagreement is stored as a completed verification with `passed = false`; it is not treated as an infrastructure failure.

Verification is currently **observational only**. It does not automatically:

- alter the response already returned to the user;
- retrain the router;
- rewrite model profiles;
- activate another policy;
- trigger automatic rollback.

---

## Technology Choices

| Component | Tool / Library | Why this choice |
| --- | --- | --- |
| Language | **Python 3.12** | Strong async and AI-infrastructure ecosystem |
| API | **FastAPI + Pydantic** | Typed request boundaries, async serving, generated OpenAPI |
| Provider HTTP | **HTTPX** | Async transport with explicit lifecycle and testable mocks |
| Local inference | **Ollama** | Real local model execution without paid cloud credentials |
| Durable state | **PostgreSQL** | Transactional source of truth for teams, budgets, audit data, and verification |
| ORM / migrations | **SQLAlchemy 2.x + Alembic** | Async persistence and versioned schema evolution |
| Transient state | **Redis** | Atomic rate counters, circuit state, locks, and stream-based jobs |
| Money arithmetic | **`Decimal`** | Avoids binary floating-point errors in cost accounting |
| Packaging | **uv + Hatchling** | Reproducible Python dependency management |
| Quality gates | **Ruff + mypy + pytest** | Formatting, linting, strict typing, and automated tests |

---

## API Surface

| Endpoint | Purpose |
| --- | --- |
| `POST /v1/chat/completions` | Authenticated OpenAI-style inference request routed by RouteForge |
| `GET /healthz` | Process liveness |
| `GET /readyz` | Runtime dependency readiness |
| `GET /v1/routing-decisions/{request_id}` | Routing, execution, cost, retry/fallback, and verification audit |
| `GET /v1/usage` | Current-month team usage |
| `GET /v1/costs` | Current-month cost and budget state |
| `GET /v1/quality-summary` | Current-month asynchronous verification statistics |
| `/docs` | Swagger UI |
| `/openapi.json` | OpenAPI schema |

### Example request

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer <ROUTEFORGE_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "routeforge",
    "messages": [
      {
        "role": "user",
        "content": "Explain why deterministic routing is useful in an LLM gateway."
      }
    ],
    "stream": false,
    "routeforge": {
      "feature_id": "general-chat",
      "minimum_quality": 0.75,
      "maximum_latency_ms": 2000,
      "maximum_estimated_cost_usd": "0.01",
      "required_governance": "internal"
    }
  }'
```

The client addresses the virtual model `routeforge`; RouteForge chooses the actual backend.

---

## Local Development

### Requirements

- Python `3.12`
- [`uv`](https://docs.astral.sh/uv/)
- PostgreSQL
- Redis
- Docker for local infrastructure
- Ollama only when exercising real local model execution

### Install dependencies

```bash
uv sync --locked
```

### Start the gateway

```bash
uv run uvicorn routeforge.gateway.app:create_app --factory --reload
```

### Start PostgreSQL

```bash
docker compose -f deploy/docker-compose/postgres.yml up -d
uv run alembic upgrade head
```

Default development database:

```text
postgresql+asyncpg://routeforge:routeforge_pass@localhost:5432/routeforge_dev
```

Override with:

```text
ROUTEFORGE_DATABASE_URL
```

### Create a development team and API key

```bash
uv run python scripts/create_development_team.py \
  --team-id team-dev \
  --name "Development Team"
```

The plaintext API key is shown once. RouteForge stores its SHA-256 digest rather than the recoverable secret.

### Configure team limits

```bash
uv run python scripts/set_team_limits.py \
  --team-id team-dev \
  --requests-per-minute 60 \
  --tokens-per-minute 50000 \
  --monthly-budget-usd 25.00
```

---

## Ollama Execution

RouteForge includes an async Ollama provider adapter for real local inference.

RouteForge does **not** automatically download models.

### Smoke test

```bash
uv run python scripts/smoke_ollama.py --model llama3.2:latest
```

### Single-model baseline

```bash
uv run python scripts/benchmark_ollama.py \
  --model llama3.2:latest \
  --output benchmarks/results/ollama-baseline.jsonl
```

### Two-model benchmark

```bash
uv run python scripts/benchmark_models.py \
  --economy-model <small-model> \
  --quality-model <strong-model> \
  --output benchmarks/results/two-model-baseline.jsonl
```

### Build an offline routing profile

```bash
uv run python scripts/build_model_profiles.py \
  --input benchmarks/results/two-model-baseline.jsonl \
  --output config/profiles/routing-profile-v1.json
```

Runtime serving does not rewrite measured profiles automatically.

---

## Configuration

```text
config/
├── models/       # model/provider capabilities, cost metadata, governance
├── policies/     # feature-specific routing and resilience policy
└── profiles/     # offline-generated quality and latency evidence
```

A feature policy can define:

- allowed model IDs;
- required capabilities;
- minimum quality;
- maximum latency;
- maximum estimated cost;
- governance ceiling;
- degraded-provider behavior;
- retry behavior;
- fallback behavior;
- optional model pinning.

The router consumes these definitions; it does not hardcode model-specific business rules.

---

## Repository Structure

```text
RouteForge/
├── config/
├── benchmarks/
├── deploy/
├── docs/
├── examples/
├── scripts/
├── src/routeforge/
│   ├── contracts/
│   ├── evaluation/
│   ├── gateway/
│   ├── providers/
│   ├── registries/
│   ├── resilience/
│   ├── routing/
│   ├── storage/
│   └── verification/
└── tests/
```

### Module responsibilities

- `contracts/` — framework-independent domain types and policies
- `routing/` — pure eligibility and deterministic selection logic
- `providers/` — normalized execution adapters
- `gateway/` — FastAPI boundary and inference coordination
- `storage/` — PostgreSQL and Redis infrastructure
- `resilience/` — circuit-breaker behavior
- `evaluation/` — deterministic quality scoring and profile generation
- `verification/` — background reference-model verification

---

## Key Architecture Decisions

### Keep the router pure

The router does not access databases, Redis, or provider clients. That keeps the core routing logic deterministic and independently testable.

### Optimize cost only after eligibility

The cheapest model does not automatically win. It must first satisfy policy, capability, quality, latency, governance, and provider-state requirements.

### Separate durable and transient state

Budgets and audit records belong in PostgreSQL. Rate counters and circuit state belong in Redis.

### Treat fallback as constrained re-routing

A fallback candidate must satisfy the same original request constraints. Fallback is not a privileged bypass route.

### Keep quality verification off the response path

Reference execution happens asynchronously so verification does not add reference-model latency to user requests.

### Keep evidence separate from policy

Benchmarks generate evidence. Policies make routing decisions. Runtime serving does not silently rewrite either.

---

## Evidence and Benchmarking Policy

RouteForge does not publish a headline cost-savings number until it is backed by a reproducible benchmark against an explicit baseline.

The repository includes benchmark tooling for:

- model quality;
- latency;
- token usage;
- routing profiles;
- provider behavior.

The final production-evidence milestone will add the complete observability stack and repeatable load testing before claims such as **cost reduction**, **quality parity**, **gateway overhead**, or **fallback success rate** are promoted in this README.

Configured local-model cost equivalents are routing inputs, not provider invoices.

---

## Project Principle

> **The cheapest model is useful only when it is eligible, available, affordable for the team, and good enough for the feature.**

RouteForge makes that decision explicit.
