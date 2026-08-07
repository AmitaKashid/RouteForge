# RouteForge

RouteForge is a quality-aware multi-provider LLM gateway designed to route requests dynamically across eligible language models based on quality, latency, cost, reliability, governance, and feature-policy constraints. It provides an OpenAI-compatible interface backed by deterministic routing policies and multi-provider failover mechanics.

## Current Development Status

RouteForge is currently in early active development (Milestone M1 — Repository Foundation and Deterministic Routing Skeleton). The foundational package layout, strict static typing environment, linting rules, typed core domain contracts, configuration-backed registries, deterministic mock provider, candidate eligibility evaluator, deterministic routing policy, architecture documentation, ADRs, and central validation workflows are established. Real cloud provider integrations and live gateway endpoints are planned for subsequent V1 milestones.

## Architecture & Decision Documentation

* [Architecture Overview](file:///c:/Users/Admin/.gemini/antigravity-ide/scratch/RouteForge/docs/architecture/overview.md) — Implemented M1 architecture, limitations, and design principles.
* [Current Request Flow](file:///c:/Users/Admin/.gemini/antigravity-ide/scratch/RouteForge/docs/architecture/current-request-flow.md) — Step-by-step candidate evaluation and routing flow diagram.
* [Module Boundaries](file:///c:/Users/Admin/.gemini/antigravity-ide/scratch/RouteForge/docs/architecture/module-boundaries.md) — Responsibilities and forbidden dependencies across package boundaries.
* [Control-Plane & Data-Plane Separation](file:///c:/Users/Admin/.gemini/antigravity-ide/scratch/RouteForge/docs/architecture/control-plane-data-plane.md) — Rationale for logical plane isolation inside a modular monolith.
* [V1 Target Architecture](file:///c:/Users/Admin/.gemini/antigravity-ide/scratch/RouteForge/docs/architecture/v1-target-architecture.md) — Planned end-to-end V1 pipeline and target infrastructure.
* [Architecture Decision Records (ADRs)](file:///c:/Users/Admin/.gemini/antigravity-ide/scratch/RouteForge/docs/decisions/README.md) — Index of project ADRs (ADR-001 through ADR-008).

## Milestone 1 Demonstration

RouteForge includes a credential-free CLI command interface for demonstrating deterministic candidate eligibility, lowest-cost model selection, and mock provider execution across pre-estimated candidate models.

```bash
# 1. General Chat (cheapest eligible model selected)
uv run routeforge demo examples/m1/general-chat.json --pretty

# 2. Constrained Routing (higher-quality model selected over cheaper ineligible candidate)
uv run routeforge demo examples/m1/constrained-routing.json --pretty

# 3. No Eligible Model (all candidates rejected, exit code 2)
uv run routeforge demo examples/m1/no-eligible-model.json --pretty
```

Note:
* All candidate quality ratings, latencies, and costs in demonstration scenarios are explicit deterministic fixtures, not live cloud measurements.
* The mock provider uses no network access or paid API credentials.
* The demonstration CLI is an isolated CLI wrapper for testing and validation; it is not the future HTTP gateway.
* Scenarios with no eligible models exit with code `2` and produce a complete decision audit record.
* Provider execution can be skipped using `--route-only`.

## Gateway Development

RouteForge provides a FastAPI HTTP gateway application factory (`create_app`) and OpenAPI documentation.

```powershell
# Sync dependencies
uv sync --locked

# Start development gateway server using Uvicorn application factory mode
uv run uvicorn routeforge.gateway.app:create_app --factory --reload
```

Gateway endpoints & documentation:
* Health Status Endpoint: `GET http://localhost:8000/healthz`
* Swagger UI Documentation: `http://localhost:8000/docs`
* OpenAPI JSON Schema: `http://localhost:8000/openapi.json`
* ReDoc Documentation: `http://localhost:8000/redoc`

Note:
* The HTTP inference endpoint `POST /v1/chat/completions` is fully functional using deterministic candidate estimation, deterministic policy routing, and `DeterministicMockProvider` attempt execution.
* Authentication is not yet implemented; request context uses the fixed development team identity `local-development`.
* Candidate estimates are calculated by a deterministic gateway estimator, not measured production models.
* The CLI demonstration (`uv run routeforge demo ...`) remains available.

## Deterministic Selection & Request Routing

RouteForge evaluates multiple pre-estimated candidate models (`route_request`) against policy and request constraints, selecting the lowest-cost eligible model deterministically. Equal-cost candidates are resolved predictably by model ID. Routing currently stops after producing the decision record prior to provider execution. Metric estimates remain deterministic fixtures in M1.

## Candidate Eligibility Evaluation

RouteForge can evaluate individual candidate models against feature policy and request-level constraints (`evaluate_candidate`). Candidate eligibility evaluates model permission, capabilities, minimum quality thresholds, latency targets, cost budgets, governance sensitivity, and provider operating state. Evaluating eligibility does not yet select a winning candidate or execute a provider. Quality, latency, and cost inputs remain deterministic fixtures at this stage.

## Provider Execution

RouteForge includes a deterministic, credential-free mock provider (`DeterministicMockProvider`) for tests and local development, as well as an `OllamaProvider` adapter for direct local model execution.

### Ollama Provider Adapter & Baseline Tools

The `OllamaProvider` adapter enables direct asynchronous completion attempts against a local Ollama server instance.

**Prerequisites & Setup:**
1. Install Ollama from [ollama.com](https://ollama.com) and start the local server daemon (`ollama serve` or host on `http://localhost:11434`).
2. Pull a local model using Ollama CLI:
   ```bash
   ollama pull llama3.2:latest
   ```

**Ollama Tools:**
- **Smoke Test:** Execute a single normalized request directly against Ollama:
  ```bash
  uv run python scripts/smoke_ollama.py --model llama3.2:latest
  ```
- **Baseline Benchmark:** Run the 10-case baseline dataset and record metrics:
  ```bash
  uv run python scripts/benchmark_ollama.py --model llama3.2:latest --output benchmarks/results/ollama-baseline.jsonl
  ```

**Important Notes:**
* RouteForge **does not auto-pull or download** Ollama models automatically.
* Automatic HTTP gateway routing (`POST /v1/chat/completions`) **still uses the mock-backed development path** in M3.1.
* Semantic caching remains deferred and explicitly out of scope for V1.

## Configuration Directories

Local JSON configurations are maintained in:

* `config/models/`: Declarative JSON model definitions (e.g. `mock_economy.json`, `mock_premium.json`). Note: Current model quality ratings, latencies, and costs are deterministic test fixtures, not measured claims.
* `config/policies/`: Declarative JSON feature routing policies (e.g. `general_chat.json`).

## Planned V1 Capabilities

* **OpenAI-Compatible Gateway:** Standardized API endpoints for chat completion routing.
* **Deterministic Policy Routing:** Multi-constraint route selection considering quality thresholds, cost budgets, and latency SLAs.
* **Multi-Provider Execution:** Resilient adapter interfaces supporting OpenAI, Anthropic, OpenRouter, and custom providers.
* **Durable & Transient Control Planes:** PostgreSQL for persistent policy/config management and Redis for high-frequency rate limiting and health checks.
* **Resilience Semantics:** Automatic retries, provider fallback chains, and circuit-breaker isolation.
* **Governance & Observability:** Team budget enforcement, rate limits, structured JSON telemetry, and OpenTelemetry instrumentation.

## Explicit V1 Non-Goals

* Semantic caching or vector database integration.
* Fine-tuning or model training workflows.
* GUI dashboard or frontend user interfaces.
* Speculative decoding or custom inference engine implementations.

## Local Setup

Ensure Python 3.12 and [`uv`](https://github.com/astral-sh/uv) are installed.

```bash
# Sync dependencies and create virtual environment
uv sync

# Lock dependencies
uv lock
```

## Validation Command

Run the central cross-platform validation script prior to committing code:

```bash
uv run python scripts/validate.py
```

This executes formatting checks, linting rules, strict static type checking, configuration validation, and unit test suites sequentially.

## Measured Two-Model Ollama Routing (M3.2)

RouteForge supports measured two-model routing between local Ollama instances (`ollama-economy` and `ollama-quality`).

### Cost Equivalents
Local Ollama models do not charge API prices. Configured cost equivalents ($0.10 input / $0.20 output per 1M tokens for `ollama-economy`; $0.50 input / $1.00 output per 1M tokens for `ollama-quality`) represent assumed infrastructure allocations for routing experiments (`source = "configured-local-cost-v1"`).

### Benchmarking & Offline Profile Generation
1. Run the benchmark workload against two local Ollama models:
   ```bash
   uv run python scripts/benchmark_models.py \
     --economy-model llama3.2:latest \
     --quality-model llama3.2:latest \
     --output benchmarks/results/two-model-baseline.jsonl
   ```

2. Build measured versioned model profiles:
   ```bash
   uv run python scripts/build_model_profiles.py \
     --input benchmarks/results/two-model-baseline.jsonl \
     --output config/profiles/routing-profile-v1.json
   ```

### Gateway Ollama Mode Execution
Start the gateway in Ollama runtime mode:
```bash
$env:ROUTEFORGE_PROVIDER_MODE="ollama"
$env:ROUTEFORGE_OLLAMA_ECONOMY_MODEL="llama3.2:latest"
$env:ROUTEFORGE_OLLAMA_QUALITY_MODEL="llama3.2:latest"

uv run uvicorn routeforge.gateway.app:create_app --factory
```

### Deterministic Evaluator Limitations
Profiles are offline-generated from 35 fixed benchmark test cases covering classification, structured extraction, JSON generation, summarization, grounded Q&A, and reasoning. Model profiles require explicit manual activation; the running gateway never modifies active profile files at runtime.

## Sampled Asynchronous Quality Verification (M6.1)

RouteForge supports policy-controlled, asynchronous quality verification for deterministic features (e.g. `classification` and `structured-extraction`).

### Asynchronous Flow & Sampling
1. **Response Path**: The client submits an inference request and receives the selected model's response immediately without added latency.
2. **Deterministic Sampling**: The gateway evaluates pure SHA-256 bucket sampling (`should_sample_verification`) over `request_id`, `policy_id`, and `policy_version` modulo 10,000 basis points.
3. **Queue Publication**: For sampled requests where `selected_model_id != reference_model_id`, job payloads are published to Redis Stream (`routeforge:quality-verification:v1`) with `MAXLEN ~ 1000` and a `QUEUED` record is written to PostgreSQL (`quality_verifications`).
4. **Reference Skip**: If `selected_model_id == reference_model_id`, the call is skipped with reason `REFERENCE_MODEL_ALREADY_USED` and no background call is made.

### Comparison Strategies
* **`NORMALIZED_EXACT`**: Text normalization (Unicode NFC, line endings, whitespace trimming, optional case folding). Score is 1.0 on exact match, 0.0 otherwise.
* **`JSON_FIELD_AGREEMENT`**: Parses root JSON objects, recursively flattens leaf paths, compares values using exact decimal semantics, and calculates matching leaf paths divided by total unioned leaf paths.

### Verification Worker
Run the background worker to consume stream entries, execute the fixed reference model, evaluate comparison strategies, and record outcomes in PostgreSQL:
```bash
# Continuous background consumption
uv run python -m routeforge.verification.worker --consumer-name worker-1

# Single-job dry run
uv run python -m routeforge.verification.worker --once
```

### Cost Accounting & Endpoint
* Verification cost is recorded as control-plane QA overhead (`reference_cost_source = "configured-model-pricing-v1"`) and is **not** charged against the team's inference budget.
* Retrieval: `GET /v1/routing-decisions/{request_id}` returns a `verification` summary object when present.
* Summary: `GET /v1/quality-summary` returns calendar-month statistics (eligible requests, sampled, completed, passed, failed, pass rate, total reference tokens, total verification cost) for the authenticated team.

## Documentation Links

* [Implementation Contract (AGENTS.md)](file:///c:/Users/Admin/.gemini/antigravity-ide/scratch/RouteForge/AGENTS.md)
* [Milestone Roadmap (ROADMAP.md)](file:///c:/Users/Admin/.gemini/antigravity-ide/scratch/RouteForge/docs/ROADMAP.md)
* [Current Repository State (CURRENT_STATE.md)](file:///c:/Users/Admin/.gemini/antigravity-ide/scratch/RouteForge/docs/CURRENT_STATE.md)
* [Milestone M1 Specification](file:///c:/Users/Admin/.gemini/antigravity-ide/scratch/RouteForge/docs/milestones/M01-foundation.md)
