# RouteForge Roadmap

This document outlines the sequential milestones for RouteForge V1.

---

### M0: Scope and Architecture Lock
* **Objective:** Define V1 scope, architecture principles, and boundary requirements.
* **Primary Deliverable:** Architectural decisions, V1 non-goals lock, and boundary definitions.
* **Exclusions:** Code implementation.

---

### M1: Repository Foundation and Deterministic Routing Skeleton
* **Objective:** Establish engineering foundation, core domain types, and in-memory deterministic router skeleton.
* **Primary Deliverable:** Python package setup, validation suite, core domain contracts, and in-memory deterministic router.
* **Exclusions:** HTTP gateway endpoints, external databases, network provider calls.

---

### M2: OpenAI-Compatible Gateway
* **Objective:** Expose OpenAI-compliant REST endpoints for chat completions.
* **Tasks:**
  * M2.1: FastAPI Gateway Bootstrap and API Boundary Contracts (Complete)
  * M2.2: API-to-Domain Translation and Request Context
  * M2.3: Functional Chat-Completion Endpoint with Mock Execution
  * M2.4: Read-Only Query APIs and Metadata Endpoints
  * M2.5: Development Authentication, Governance Context, and Error Handling
  * M2.6: OpenAPI Compatibility, Integration Hardening, and Validation
  * M2.7: Gateway Demonstration and Milestone 2 Closure
* **Primary Deliverable:** FastAPI gateway supporting `/v1/chat/completions` request parsing, translation, deterministic routing, and mock execution.
* **Exclusions:** Database persistence, live provider execution (uses mock provider).

---

### M3: Durable PostgreSQL Control Plane
* **Objective:** Store routing policies, provider configs, and model metadata persistently.
* **Primary Deliverable:** PostgreSQL schema, migrations, and repository access layer.
* **Exclusions:** Redis state management, live HTTP provider calls.

---

### M4: Provider Execution Layer
* **Objective:** Execute live requests against external LLM provider APIs.
* **Primary Deliverable:** Provider adapter interfaces for OpenAI, Anthropic, and OpenRouter with payload translation.
* **Exclusions:** Complex fallback chains, Redis rate limiting.

---

### M5: Constraint-Aware Routing
* **Objective:** Evaluate quality thresholds, cost budgets, and latency SLAs during route selection.
* **Primary Deliverable:** Multi-constraint evaluation engine in deterministic routing pipeline.
* **Exclusions:** Async shadow routing, background benchmark updates.

---

### M6: Reliability and Redis State
* **Objective:** Introduce transient state management for resilience and health monitoring.
* **Primary Deliverable:** Redis-backed rate limiting, provider health tracking, circuit breakers, and retries/fallbacks.
* **Exclusions:** Multi-region cluster replication.

---

### M7: Team Governance and Economic Controls
* **Objective:** Enforce multi-tenant access rules, cost quotas, and policy overrides.
* **Primary Deliverable:** Tenant key management, team budget caps, and governance policy rules.
* **Exclusions:** GUI admin interface.

---

### M8: Observability
* **Objective:** Instrument gateway operations with structured metrics, logs, and telemetry.
* **Primary Deliverable:** Structured JSON logging, OpenTelemetry integration, and Prometheus metric exporters.
* **Exclusions:** External SaaS telemetry UI integration.

---

### M9: Asynchronous Quality Verification
* **Objective:** Continuously verify response quality out-of-band.
* **Primary Deliverable:** Background worker for response quality sampling and automated model scoring.
* **Exclusions:** Synchronous inline model evaluation during request path.

---

### M10: Policy Lifecycle and Shadow Evaluation
* **Objective:** Safely evaluate new routing policies without impacting live traffic.
* **Primary Deliverable:** Shadow routing pipeline, diff logging, and policy versioning lifecycle.
* **Exclusions:** Fully automated dynamic prompt rewrites.

---

### M11: Benchmarking, Hardening, and V1 Release
* **Objective:** Validate system performance, establish baseline metrics, and declare V1 readiness.
* **Primary Deliverable:** Load test suite, security audit documentation, reproducible benchmarks, and V1 release tag.
* **Exclusions:** Post-V1 roadmap features (e.g. semantic caching).
