# Milestone M2: OpenAI-Compatible Gateway

## Milestone Objective

Establish an OpenAI-compatible HTTP API gateway layer using FastAPI and Pydantic V2 wire contracts, backed by explicit API-to-domain translation, request context propagation, development authentication, deterministic routing, and mock provider attempt execution.

## Reason Milestone Exists

Exposing a standardized OpenAI-compatible HTTP interface enables external application integration without exposing internal gateway routing mechanics. Isolating API wire contracts from internal domain models ensures that external API changes do not corrupt internal domain invariants.

## Milestone Tasks (M2.1 – M2.7)

### M2.1: FastAPI Gateway Bootstrap and API Boundary Contracts (Complete)
* **Objective:** Create the FastAPI application factory, `/healthz` endpoint, and gateway-isolated Pydantic wire models for chat completions and errors.
* **Main Deliverable:** `src/routeforge/gateway/` package with `create_app()`, `/healthz` endpoint, and wire schemas (`ChatCompletionsRequest`, `ChatCompletionsResponse`, `ApiErrorResponse`).
* **Explicit Boundary:** No API-to-domain translation, no routing execution, no `/v1/chat/completions` endpoint registration.

### M2.2: Functional Mock-Backed Chat Completion (Complete)
* **Objective:** Implement `POST /v1/chat/completions` endpoint translating API wire requests to domain contracts, building candidate estimates, executing deterministic routing, and invoking the mock provider.
* **Main Deliverable:** Functional `POST /v1/chat/completions` route, request/response translation (`src/routeforge/gateway/translation.py`), candidate estimator (`src/routeforge/gateway/estimation.py`), and error handling for `NO_ELIGIBLE_MODEL` (HTTP 503) and provider failures (HTTP 502).
* **Explicit Boundary:** Fixed development team ID `local-development`, mock provider execution only, no authentication, no real cloud providers.

### M2.3: Functional Chat-Completion Endpoint with Mock Execution
* **Objective:** Register `POST /v1/chat/completions` executing end-to-end request translation, candidate eligibility evaluation, lowest-cost routing selection, and mock provider completion attempt.
* **Main Deliverable:** `POST /v1/chat/completions` route returning normalized `ChatCompletionsResponse`.
* **Explicit Boundary:** No real cloud providers, no retries/fallbacks, no persistence.

### M2.4: Read-Only Query APIs and Metadata Endpoints
* **Objective:** Expose read-only HTTP query endpoints for model definitions, active feature policies, and routing decisions.
* **Main Deliverable:** `GET /v1/models`, `GET /v1/policies`, `GET /v1/routing-decisions/{request_id}`.
* **Explicit Boundary:** In-memory configuration read access only; no durable database storage.

### M2.5: Development Authentication, Governance Context, and Error Handling
* **Objective:** Implement development API key authentication, team identity resolution, and unified exception mapping to OpenAI-compatible error payloads.
* **Main Deliverable:** Authentication dependencies and custom FastAPI exception handlers.
* **Explicit Boundary:** Development key mapping only; no PostgreSQL key database or OAuth.

### M2.6: OpenAPI Compatibility, Integration Hardening, and Validation
* **Objective:** Harden OpenAPI documentation, add end-to-end integration test suites, and enforce gateway architecture boundary rules.
* **Main Deliverable:** Comprehensive gateway integration test suite under `tests/integration/gateway/`.
* **Explicit Boundary:** No future milestone functionality.

### M2.7: Gateway Demonstration and Milestone 2 Closure
* **Objective:** Provide a working Uvicorn HTTP gateway demonstration and lock Milestone M2.
* **Main Deliverable:** `docs/milestones/M02-completion.md` and demonstration scripts.
* **Explicit Boundary:** Closure of Milestone M2.
