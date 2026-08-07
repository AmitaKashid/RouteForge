# Milestone M1: Repository Foundation and Deterministic Routing Skeleton

## Milestone Objective

Establish a clean Python 3.12 package infrastructure, strict typing and linting standards, central validation tooling, CI workflows, core domain model definitions, configuration-backed registries, deterministic mock provider execution, candidate eligibility evaluation, an in-memory deterministic router policy, formal architecture documentation, hardened test/validation verification, and a credential-free CLI demonstration interface.

## Reason Milestone Exists

A reliable multi-provider LLM gateway requires absolute code quality, strict typing contracts, reproducible environment management, and deterministic routing guarantees. Establishing this foundation upfront prevents downstream technical debt and ensures that subsequent provider and routing features build upon a secure base.

## Milestone Tasks (M1.1 – M1.9)

* **M1.1:** Repository Bootstrap, Project Rules, Validation Command, and CI Foundation (Complete)
* **M1.2:** Typed Core Contracts (Model, Provider, Request, Response, Cost) (Complete)
* **M1.3:** Configuration-Backed Registries (Models & Policies) (Complete)
* **M1.4:** Deterministic Mock Provider (Complete)
* **M1.5:** Candidate Eligibility Evaluation (Complete)
* **M1.6:** Deterministic In-Memory Router Skeleton & Tie-Breaking Logic (Complete)
* **M1.7:** Architecture Documentation and ADR Completion (Complete)
* **M1.8:** M1 Test Hardening and Validation Review (Complete)
* **M1.9:** Demonstration Interface and M1 Closure (Complete)

## Task Details: M1.9 Demonstration Interface and M1 Closure

### Objective
Create a professional credential-free CLI demonstration interface (`routeforge demo`), decode JSON demonstration scenarios, execute candidate eligibility evaluation and lowest-cost model selection, optionally execute mock provider attempts, and formally lock Milestone M1.

### Implemented Demonstration Components
* **CLI Module (`src/routeforge/cli.py`)**: Standard-library `argparse` parser and strict JSON scenario decoder `decode_demo_scenario`.
* **Module Entrypoint (`src/routeforge/__main__.py`)**: Supports `python -m routeforge demo <scenario-path>`.
* **Committed Scenarios (`examples/m1/`)**: `general-chat.json`, `constrained-routing.json`, `no-eligible-model.json`.
* **M1 Completion Report (`docs/milestones/M01-completion.md`)**: Documents formal closure of Milestone M1.

### Exit Code Semantics
* `0`: Routing completed and eligible model was executed (or `--route-only` requested).
* `1`: Invalid scenario JSON payload, missing file, or provider execution error.
* `2`: Routing completed normally but no candidate was eligible (`NO_ELIGIBLE_MODEL`).

### M1.9 Exit Criteria
* Demonstration CLI commands passing for all committed scenarios.
* Unit and integration CLI test coverage under `tests/unit/cli/` and `tests/integration/test_m1_cli_demo.py`.
* Completion report created (`docs/milestones/M01-completion.md`).
* All 6 validation stages passing via `uv run python scripts/validate.py`.

## Milestone Status

```text
MILESTONE 1 COMPLETE
```

## Next Milestone

**Milestone M2 — OpenAI-Compatible Gateway**  
Next task: `M2.1 — FastAPI Gateway Bootstrap and API Boundary Contracts`
