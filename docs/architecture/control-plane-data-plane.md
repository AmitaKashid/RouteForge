# Control-Plane and Data-Plane Separation

## Overview

RouteForge strictly distinguishes between the **Control Plane** (managing policies, configurations, and governance metadata) and the **Data Plane** (evaluating, routing, and executing inference requests).

## Control Plane (`Implemented in M1` & `Planned for M3`)

### Purpose
The control plane handles durable configuration and operational policy state. Control-plane operations occur infrequently compared to inference requests.

### Planned Responsibilities (`Planned for M3`)
* Model definition registration and configuration updates.
* Feature policy creation, versioning (`PolicyVersion`), activation, and rollback.
* Pricing configuration and cost schedule management.
* Team budget allocations and API key management.
* Governance classification rules.
* Audit trail logging for administrative actions.

### M1 Control-Plane State (`Implemented in M1`)
M1 implements a local control-plane foundation using:
* `ModelDefinition` and `FeaturePolicy` domain contracts.
* `ModelRegistry` and `FeaturePolicyRegistry` protocol interfaces.
* `InMemoryModelRegistry` and `InMemoryFeaturePolicyRegistry` in-memory implementations.
* Local JSON snapshot loading (`load_registry_snapshot`) reading UTF-8 files in `config/models/` and `config/policies/`.

## Data Plane (`Implemented in M1` & `Planned for M2/M7/M8`)

### Purpose
The data plane processes inference requests on the latency-critical path.

### Planned Responsibilities (`Planned for M2/M7/M8`)
* Receiving incoming OpenAI-compatible API requests (`FastAPI`).
* Authenticating requests and verifying team rate limits (`Redis`).
* Resolving active feature policies for feature IDs.
* Evaluating candidate model eligibility (`routeforge.routing.eligibility`).
* Selecting optimal candidates (`routeforge.routing.selection`).
* Executing attempts through provider adapters (`LLMProvider.complete`).
* Handling provider retries, fallbacks, and circuit breakers.
* Normalizing provider responses and reporting usage telemetry.

### M1 Data-Plane Logic (`Implemented in M1`)
M1 implements core data-plane evaluation and selection logic as pure functions:
* `evaluate_candidate`: Evaluates model permission, capabilities, quality thresholds, latency targets, cost limits, governance, and provider state.
* `route_request`: Evaluates candidates, sorts by model ID, selects lowest-cost eligible candidate, and returns an immutable `RoutingDecision`.
* `DeterministicMockProvider`: Provides isolated mock completion execution (`LLMProvider`) without network calls or wall-clock sleeping.

## Rationale for Separation

1. **Latency Preservation:** The data plane consumes immutable snapshot versions (`PolicyVersion`, `ModelDefinition`). It does not perform expensive database queries or administrative validation during request routing.
2. **Auditability:** Policy mutations produce new explicit policy versions. Routing decisions capture the exact policy ID and version active at decision time.
3. **Fault Isolation:** Control-plane storage or management failures do not corrupt active data-plane routing operations.
4. **Target Monolith Architecture:** Logical separation is maintained within a single Python modular monolith in V1. Physical microservice decomposition is explicitly prohibited (`AGENTS.md` Rule 5).
