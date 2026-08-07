# Architecture Overview

## Project Purpose

RouteForge is a quality-aware, multi-provider LLM gateway designed to dynamically route requests across eligible language models based on quality thresholds, latency targets, cost budgets, governance classifications, and provider health states.

The target optimization rule is:
> **Among eligible candidates, select the lowest-cost model.**

## Current M1 Architecture (`Implemented in M1`)

The repository is currently structured as a modular monolith in Python 3.12 (`src/routeforge`). Milestone M1 establishes the typed domain contracts, configuration-backed registries, deterministic mock provider execution, candidate eligibility evaluation, and deterministic candidate selection logic.

Implemented components:

* **Contracts (`src/routeforge/contracts/`)**: Provider-neutral, immutable domain dataclasses and enums (`ChatRequest`, `ModelDefinition`, `FeaturePolicy`, `CandidateEstimate`, `CandidateEvaluation`, `RoutingDecision`, `ProviderRequest`, `ProviderResponse`, `ProviderError`).
* **Registries (`src/routeforge/registries/`)**: Repository-neutral protocols (`ModelRegistry`, `FeaturePolicyRegistry`), in-memory implementations (`InMemoryModelRegistry`, `InMemoryFeaturePolicyRegistry`), strict JSON file loader (`load_registry_snapshot`), and cross-reference validation rules (`validate_cross_references`).
* **Providers (`src/routeforge/providers/`)**: Provider-neutral execution protocol (`LLMProvider`), exception boundary (`ProviderExecutionError`), and credential-free deterministic mock provider (`DeterministicMockProvider`) supporting controllable success and error test scenarios (`MockScenario`, `MockOutcome`).
* **Routing Eligibility (`src/routeforge/routing/eligibility.py`)**: Pure deterministic function `evaluate_candidate` evaluating single candidates against effective request and policy constraints.
* **Routing Selection (`src/routeforge/routing/selection.py`)**: Pure deterministic function `route_request` evaluating all candidates, sorting deterministically by model ID, and selecting the lowest-cost eligible model.
* **Configuration (`config/models/`, `config/policies/`)**: Declarative JSON configuration files for mock models (`mock-economy`, `mock-premium`) and feature policies (`general-chat`).
* **Gateway Bootstrap & Wire Schemas (`src/routeforge/gateway/`)**: FastAPI application factory (`create_app()`), `/healthz` status route, and isolated Pydantic wire models (`ChatCompletionsRequest`, `ChatCompletionsResponse`, `ApiErrorResponse`, `HealthResponse`).
* **Validation Script (`scripts/validate.py`)**: Central 6-stage validation script executing formatting checks, linting, strict mypy type checks, AST architecture dependency validation (`validate_architecture.py`), configuration validation (`validate_config.py`), and pytest suites.

## Current Limitations (`Planned for later V1 milestones`)

M1 establishes core contracts and deterministic routing logic in memory, but intentionally excludes the following operational capabilities:

* **HTTP Gateway:** FastAPI OpenAI-compatible API routes (`Planned for M2`).
* **Real Cloud Provider Adapters:** OpenAI, Anthropic, and OpenRouter integration clients (`Planned for M7`).
* **Dynamic Estimation:** Real-time request complexity classification, quality prediction, cost estimation, and latency prediction (`Planned for M5`).
* **Resilience Mechanics:** Retries, provider fallbacks, and circuit breakers (`Planned for M8`).
* **Durable Persistence:** PostgreSQL control-plane storage (`Planned for M3`).
* **Transient Coordination State:** Redis rate-limiting and circuit-breaker storage (`Planned for M4` / `M8`).
* **Governance & Observability:** Team budget tracking, rate limits, OpenTelemetry traces, and Prometheus metrics (`Planned for M4` / `M6`).
* **Asynchronous Verification:** Post-execution quality sampling workers (`Planned for M9`).
* **Shadow Evaluation:** Parallel candidate policy testing without user traffic impact (`Planned for M10`).

## Design Principles

1. **Deterministic Core Before Distributed Infrastructure:** Core contracts and routing decisions must be 100% deterministic and testable without network access or databases.
2. **Hard Constraints Before Optimization:** Hard policy, governance, capability, quality, cost, and latency constraints filter candidates prior to cost optimization.
3. **Provider Isolation:** Core routing logic interacts strictly with vendor-neutral domain contracts, avoiding vendor SDK leakages.
4. **Immutable and Auditable Decisions:** Every routing decision produces an immutable `RoutingDecision` capturing all evaluated candidates and explicit rejection reasons.
5. **Durable and Transient State Separation:** Single source of truth for durable configuration in PostgreSQL (`Planned for M3`) and transient health/rate-limiting counters in Redis (`Planned for M4`).
6. **Explicit Policy Versioning:** Routing consumes specific immutable policy versions (`PolicyVersion`).
7. **No Autonomous Policy Changes:** System policies and weights are changed explicitly through versioned deployments, not online reinforcement learning (`Explicit V1 non-goal`).
8. **No Unsubstantiated Claims:** Quality, cost, and latency metrics remain explicit fixtures until measured by reproducible benchmark suites (`Planned for M11`).

## Current Repository Map (`Implemented in M1`)

```text
RouteForge/
├── config/
│   ├── models/            # Declarative model definition JSON fixtures
│   └── policies/          # Declarative feature policy JSON fixtures
├── docs/
│   ├── architecture/      # Architecture documentation
│   ├── decisions/         # Architecture Decision Records (ADRs)
│   ├── milestones/        # Milestone definitions and exit criteria
│   ├── CURRENT_STATE.md   # Active task status tracker
│   └── ROADMAP.md         # Milestone roadmap M0-M11
├── scripts/
│   ├── validate.py        # Central 5-stage validation script
│   └── validate_config.py # Standalone JSON config validation script
├── src/
│   └── routeforge/
│       ├── contracts/     # Domain data contracts and error enums
│       ├── providers/     # Provider execution interfaces and mock implementation
│       ├── registries/    # Model and policy registry contracts and loaders
│       └── routing/       # Eligibility evaluation and candidate selection
└── tests/
    ├── contract/          # Serialization and provider contract verification
    ├── integration/       # End-to-end integration tests on committed config
    └── unit/              # Isolated unit tests for contracts, registries, providers, routing
```
