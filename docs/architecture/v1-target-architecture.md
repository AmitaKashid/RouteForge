# V1 Target Architecture

## Overview

This document describes the planned V1 target architecture for RouteForge (`Planned for later V1 milestones`). RouteForge is designed as a restrained Python 3.12 modular monolith backed by PostgreSQL and Redis.

## Target Request Pipeline (`Planned for later V1 milestones`)

```text
Client
  ↓
FastAPI Gateway (`Planned for M2`)
  ↓
Authentication & Tenant Validation (`Planned for M4`)
  ↓
Feature-Policy Resolution (`Planned for M3`)
  ↓
Rate-Limit & Budget Enforcement (`Planned for M4`)
  ↓
Request-Complexity & Metric Estimation (`Planned for M5`)
  ↓
Provider-Health Filtering (`Planned for M8`)
  ↓
Candidate Eligibility Evaluation (`Implemented in M1`)
  ↓
Deterministic Policy-Based Selection (`Implemented in M1`)
  ↓
Provider Attempt Execution (`Planned for M7`)
  ↓
Retry / Policy-Controlled Fallback (`Planned for M8`)
  ↓
Normalized Provider Response (`Implemented in M1`)
  ↓
Durable Logging & Telemetry (`Planned for M3/M6`)
  ↓
Sampled Asynchronous Verification Worker (`Planned for M9`)
```

## Target Infrastructure Components

* **Python 3.12 Modular Monolith (`src/routeforge`):** Core gateway process hosting API routing, domain logic, registry adapters, routing policy, and provider clients.
* **PostgreSQL (`Planned for M3`):** Single source of truth for persistent control-plane state, model definitions, feature policies, audit logs, and routing decisions (`AGENTS.md` Rule 11).
* **Redis (`Planned for M4` / `M8`):** High-frequency transient operational state, rate-limit sliding windows, provider health status, and circuit-breaker states (`AGENTS.md` Rule 12).
* **Verifier Worker (`Planned for M9`):** Single background process consuming sampled execution responses for asynchronous quality verification.
* **Observability Suite (`Planned for M6`):** OpenTelemetry tracing, Prometheus metrics, and structured JSON logging.

## Explicit V1 Non-Goals (`AGENTS.md` Rule 3 & Project Directives)

The following capabilities are strictly excluded from V1:

* **Semantic Caching:** No vector storage, embedding similarity, or prompt caching (`AGENTS.md` Rule 18).
* **Microservices:** No service mesh, distributed tracing mesh, or multiple microservice wrappers (`AGENTS.md` Rule 5).
* **Autonomous Online Retraining:** No online reinforcement learning routers or automatic policy mutations without explicit human review.
* **Fine-Tuning / Training Workflows:** No model training or weights optimization.
* **GUI Dashboard / Frontend:** Gateway provides pure OpenAI-compatible API interfaces.
* **Speculative Decoding:** No custom inference engine implementations.
* **Kubernetes / Multi-Region Infrastructure:** Deployment uses simple Docker Compose configurations for local development and single-region server instances.
