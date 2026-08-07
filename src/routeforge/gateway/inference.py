"""Application-level inference coordinator handling routing, retries, fallback, and persistence."""

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from routeforge.contracts import (
    AttemptId,
    ChatRequest,
    ChatResponse,
    ErrorCode,
    ExecutionAttempt,
    ExecutionAttemptKind,
    ExecutionAttemptOutcome,
    FeaturePolicy,
    ModelDefinition,
    ModelId,
    ProviderError,
    ProviderId,
    ProviderOperatingState,
    ProviderRequest,
    RoutingDecision,
    RoutingReason,
    utc_now,
)
from routeforge.contracts.verification import VerificationStrategy
from routeforge.gateway.estimation import build_candidate_estimate
from routeforge.providers import LLMProvider, ProviderExecutionError
from routeforge.resilience import (
    CircuitState,
    ProviderHealthSnapshot,
)
from routeforge.routing.selection import RoutingCandidate, route_request
from routeforge.storage.database import DatabaseManager
from routeforge.storage.models import InferenceRecordModel, QualityVerificationRecord
from routeforge.storage.records import (
    calculate_accounted_cost,
    get_monthly_period_start,
    hash_prompt,
    reconcile_actual_cost,
    release_budget_reservation,
    replace_budget_reservation,
    reserve_budget_for_request,
)
from routeforge.verification.hashing import hash_json_output, hash_text_output
from routeforge.verification.queue import (
    ack_and_delete_verification_job,
    enqueue_verification_job,
)
from routeforge.verification.sampling import should_sample_verification

TERMINAL_RETRYABLE_ERRORS: set[ErrorCode | str] = {
    ErrorCode.PROVIDER_TIMEOUT,
    ErrorCode.PROVIDER_RATE_LIMITED,
    ErrorCode.PROVIDER_CONNECTION_ERROR,
    ErrorCode.PROVIDER_UNAVAILABLE,
    "PROVIDER_TIMEOUT",
    "PROVIDER_RATE_LIMITED",
    "PROVIDER_CONNECTION_ERROR",
    "PROVIDER_UNAVAILABLE",
    "RATE_LIMIT_EXCEEDED",
    "SERVICE_UNAVAILABLE",
    "BAD_GATEWAY",
}


def execution_attempt_to_dict(attempt: ExecutionAttempt) -> dict[str, Any]:
    """Serialize ExecutionAttempt to JSONB-compatible dictionary."""
    return {
        "attempt_number": attempt.attempt_number,
        "attempt_id": str(attempt.attempt_id),
        "attempt_kind": str(attempt.attempt_kind.value),
        "model_id": str(attempt.model_id),
        "provider_id": str(attempt.provider_id),
        "outcome": str(attempt.outcome.value),
        "error_code": (
            attempt.error_code.value
            if hasattr(attempt.error_code, "value")
            else str(attempt.error_code)
        )
        if attempt.error_code is not None
        else None,
        "retryable": attempt.retryable,
        "provider_status_code": attempt.provider_status_code,
        "latency_ms": attempt.latency_ms,
        "estimated_cost_usd": str(attempt.estimated_cost_usd),
        "actual_cost_usd": str(attempt.actual_cost_usd)
        if attempt.actual_cost_usd is not None
        else None,
        "is_half_open_probe": attempt.is_half_open_probe,
        "started_at": attempt.started_at.isoformat(),
        "completed_at": attempt.completed_at.isoformat(),
    }


def calculate_exponential_backoff_ms(initial_backoff_ms: int, retry_number: int) -> int:
    """Calculate exponential backoff in milliseconds for retry number N (1-indexed).

    Formula: initial_backoff_ms * 2 ** (N - 1)
    """
    if retry_number < 1:
        raise ValueError("retry_number must be at least 1.")
    return int(initial_backoff_ms * (2 ** (retry_number - 1)))


@dataclass(frozen=True)
class ExecutionResult:
    """Outcome of inference execution across attempts."""

    success: bool
    response: ChatResponse | None = None
    decision: RoutingDecision | None = None
    error: ProviderError | None = None
    error_code: ErrorCode | None = None
    error_message: str | None = None
    http_status_code: int = 200
    attempts: tuple[ExecutionAttempt, ...] = ()
    retry_count: int = 0
    fallback_used: bool = False
    initial_model_id: ModelId | None = None
    initial_provider_id: ProviderId | None = None
    selected_model_id: ModelId | None = None
    selected_provider_id: ProviderId | None = None


async def execute_inference(
    *,
    request: ChatRequest,
    policy: FeaturePolicy,
    candidate_models: list[ModelDefinition],
    provider_resolver: Callable[[ProviderId], LLMProvider],
    db_manager: DatabaseManager | None = None,
    profile_registry: Any = None,
    circuit_breaker: Any = None,
    redis_client: Any = None,
    sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> ExecutionResult:
    """Execute policy-controlled inference request with retries, circuit breakers, and fallback."""
    now = request.created_at if request.created_at is not None else utc_now()
    created_timestamp = datetime.now(UTC)
    prompt_digest = hash_prompt(request.messages)

    # 1. Resolve circuit breaker state per candidate and build initial candidate pool
    candidates: list[RoutingCandidate] = []
    candidate_snapshots: dict[tuple[ProviderId, ModelId], ProviderHealthSnapshot] = {}
    model_by_id: dict[ModelId, ModelDefinition] = {}

    for model in candidate_models:
        model_by_id[model.model_id] = model
        snap: ProviderHealthSnapshot | None = None
        if circuit_breaker is not None:
            snap = await circuit_breaker.get_routing_state(
                provider_id=model.provider_id,
                model_id=model.model_id,
                policy=policy.circuit_breaker_policy,
                now=now.timestamp(),
            )
            candidate_snapshots[(model.provider_id, model.model_id)] = snap
            p_state = snap.provider_state
        else:
            p_state = ProviderOperatingState.HEALTHY

        try:
            estimate = build_candidate_estimate(
                request=request,
                model=model,
                feature_id=policy.feature_id,
                model_profile_registry=profile_registry,
            )
            candidates.append(
                RoutingCandidate(
                    model=model,
                    estimate=estimate,
                    provider_state=p_state,
                )
            )
        except ValueError:
            continue

    if not candidates:
        return ExecutionResult(
            success=False,
            error_code=ErrorCode.NO_ELIGIBLE_MODEL,
            error_message="No candidate models available for policy.",
            http_status_code=503,
        )

    # 2. Initial routing decision
    initial_decision = route_request(
        request=request,
        policy=policy,
        candidates=candidates,
        decided_at=now,
    )

    candidate_evaluations_payload = [
        {
            "model_id": str(eval.model_id),
            "provider_id": str(eval.provider_id),
            "eligible": eval.eligible,
            "rejection_reasons": [
                r.value if hasattr(r, "value") else str(r) for r in eval.rejection_reasons
            ],
            "predicted_quality": float(eval.estimate.predicted_quality),
            "estimated_latency_ms": eval.estimate.estimated_latency_ms,
            "estimated_cost_usd": float(eval.estimate.estimated_cost_usd),
            "provider_state": str(
                candidate_snapshots[(eval.provider_id, eval.model_id)].provider_state.value
                if (eval.provider_id, eval.model_id) in candidate_snapshots
                else "HEALTHY"
            ),
            "circuit_state": str(
                candidate_snapshots[(eval.provider_id, eval.model_id)].circuit_state.value
                if (eval.provider_id, eval.model_id) in candidate_snapshots
                else "CLOSED"
            ),
        }
        for eval in initial_decision.candidates
    ]

    if initial_decision.selected_model_id is None:
        if db_manager is not None:
            record = InferenceRecordModel(
                request_id=str(request.request_id),
                team_id=str(request.team_id),
                feature_id=str(policy.feature_id),
                policy_id=str(policy.policy_id),
                policy_version=str(policy.version),
                selected_model_id=None,
                selected_provider_id=None,
                routing_reason=str(initial_decision.routing_reason.value),
                candidate_decisions=candidate_evaluations_payload,
                status="NO_ELIGIBLE_MODEL",
                error_code="NO_ELIGIBLE_MODEL",
                prompt_hash=prompt_digest,
                message_count=len(request.messages),
                execution_attempts=[],
                retry_count=0,
                fallback_used=False,
                initial_model_id=None,
                initial_provider_id=None,
                created_at=created_timestamp,
                completed_at=datetime.now(UTC),
            )
            try:
                async with db_manager.session_factory() as session:
                    session.add(record)
                    await session.commit()
            except Exception:
                pass

        return ExecutionResult(
            success=False,
            decision=initial_decision,
            error_code=ErrorCode.NO_ELIGIBLE_MODEL,
            error_message="No eligible candidate model met policy and request constraints.",
            http_status_code=503,
        )

    initial_model_id = initial_decision.selected_model_id
    initial_provider_id = initial_decision.selected_provider_id
    current_model_id = initial_model_id
    current_provider_id = initial_provider_id

    sel_candidate = next(
        (c for c in candidates if c.model.model_id == current_model_id),
        None,
    )
    current_estimated_cost = (
        sel_candidate.estimate.estimated_cost_usd
        if sel_candidate is not None
        else Decimal("0.00010000")
    )

    # 3. Reserve initial budget in PostgreSQL
    month_start_date = get_monthly_period_start(created_timestamp)
    budget_allowed = True
    monthly_budget_usd = None
    committed_cost_usd = Decimal("0")

    if db_manager is not None:
        try:
            async with db_manager.session_factory() as session:
                (
                    budget_allowed,
                    monthly_budget_usd,
                    committed_cost_usd,
                    _req_est,
                ) = await reserve_budget_for_request(
                    session,
                    str(request.team_id),
                    current_estimated_cost,
                    created_timestamp,
                )

                status_val = "BUDGET_RESERVED" if budget_allowed else "BUDGET_REJECTED"
                reserved_val = current_estimated_cost if budget_allowed else Decimal("0")
                error_val = None if budget_allowed else "MONTHLY_BUDGET_EXCEEDED"

                record = InferenceRecordModel(
                    request_id=str(request.request_id),
                    team_id=str(request.team_id),
                    feature_id=str(policy.feature_id),
                    policy_id=str(policy.policy_id),
                    policy_version=str(policy.version),
                    selected_model_id=str(current_model_id),
                    selected_provider_id=str(current_provider_id),
                    routing_reason=str(initial_decision.routing_reason.value),
                    candidate_decisions=candidate_evaluations_payload,
                    status=status_val,
                    error_code=error_val,
                    prompt_hash=prompt_digest,
                    message_count=len(request.messages),
                    estimated_cost_usd=current_estimated_cost,
                    reserved_cost_usd=reserved_val,
                    accounted_cost_usd=None,
                    cost_source=None,
                    budget_period_start=month_start_date,
                    provider_latency_ms=None,
                    execution_attempts=[],
                    retry_count=0,
                    fallback_used=False,
                    initial_model_id=str(initial_model_id),
                    initial_provider_id=str(initial_provider_id),
                    created_at=created_timestamp,
                    completed_at=datetime.now(UTC),
                )
                session.add(record)
                await session.commit()
        except Exception:
            budget_allowed = True

    if not budget_allowed:
        mb_str = f"{monthly_budget_usd:.8f}" if monthly_budget_usd is not None else "0.0"
        return ExecutionResult(
            success=False,
            decision=initial_decision,
            error_code=ErrorCode.MONTHLY_BUDGET_EXCEEDED,
            error_message=(
                f"Monthly budget limit of ${mb_str} exceeded "
                f"(committed: ${committed_cost_usd:.8f})."
            ),
            http_status_code=402,
            initial_model_id=initial_model_id,
            initial_provider_id=initial_provider_id,
        )

    # 4. Resilience Loop (Retries & Fallbacks)
    attempts: list[ExecutionAttempt] = []
    attempt_counter = 0
    total_retry_count = 0
    fallback_used = False
    fallback_attempts_count = 0

    excluded_pairs: set[tuple[ProviderId, ModelId]] = set()
    current_decision = initial_decision

    while True:
        target_model = model_by_id.get(current_model_id)
        if target_model is None:
            return ExecutionResult(
                success=False,
                error_code=ErrorCode.UNKNOWN_MODEL,
                error_message=f"Model definition '{current_model_id}' not found.",
                http_status_code=503,
            )

        current_provider_id = target_model.provider_id
        provider = provider_resolver(current_provider_id)

        is_half_open_probe = False
        if circuit_breaker is not None:
            snap = candidate_snapshots.get((current_provider_id, current_model_id))
            if snap is not None and snap.circuit_state == CircuitState.HALF_OPEN:
                acquired = await circuit_breaker.acquire_half_open_probe(
                    provider_id=current_provider_id,
                    model_id=current_model_id,
                    now=now.timestamp(),
                    ttl_seconds=policy.circuit_breaker_policy.open_duration_seconds,
                )
                if not acquired:
                    # Probe lock held by another request -> treat as UNAVAILABLE and re-route
                    excluded_pairs.add((current_provider_id, current_model_id))
                    rerun_candidates: list[RoutingCandidate] = []
                    for c in candidates:
                        c_pstate = (
                            ProviderOperatingState.UNAVAILABLE
                            if (c.model.provider_id, c.model.model_id) in excluded_pairs
                            else c.provider_state
                        )
                        rerun_candidates.append(
                            RoutingCandidate(
                                model=c.model,
                                estimate=c.estimate,
                                provider_state=c_pstate,
                            )
                        )
                    current_decision = route_request(
                        request=request,
                        policy=policy,
                        candidates=rerun_candidates,
                        decided_at=now,
                    )
                    if current_decision.selected_model_id is None:
                        return ExecutionResult(
                            success=False,
                            decision=current_decision,
                            error_code=ErrorCode.NO_ELIGIBLE_MODEL,
                            error_message=(
                                "No eligible candidate model met policy and request constraints."
                            ),
                            http_status_code=503,
                        )
                    current_model_id = current_decision.selected_model_id
                    target_model = model_by_id.get(current_model_id)
                    if target_model is None:
                        return ExecutionResult(
                            success=False,
                            error_code=ErrorCode.UNKNOWN_MODEL,
                            error_message=f"Model definition '{current_model_id}' not found.",
                            http_status_code=503,
                        )
                    current_provider_id = target_model.provider_id
                    provider = provider_resolver(current_provider_id)
                else:
                    is_half_open_probe = True

        max_retries = (
            0
            if is_half_open_probe
            else (policy.retry_policy.maximum_retries if policy.retry_policy.enabled else 0)
        )
        attempt_on_pair = 0
        last_provider_error: ProviderError | None = None

        while attempt_on_pair <= max_retries:
            attempt_counter += 1
            attempt_on_pair += 1

            attempt_id = AttemptId(f"{request.request_id}-attempt-{attempt_counter}")
            if attempt_counter == 1:
                kind = ExecutionAttemptKind.PRIMARY
            elif fallback_used and attempt_on_pair == 1:
                kind = ExecutionAttemptKind.FALLBACK
            else:
                kind = ExecutionAttemptKind.RETRY

            provider_req = ProviderRequest(
                request_id=request.request_id,
                attempt_id=attempt_id,
                model_id=current_model_id,
                messages=request.messages,
                output_format=request.output_format,
                timeout_ms=5000,
                idempotency_key=f"{request.request_id}-idempotency",
            )

            start_time = utc_now()

            try:
                provider_resp = await provider.complete(request=provider_req, model=target_model)
                end_time = utc_now()

                if circuit_breaker is not None:
                    await circuit_breaker.record_success(
                        provider_id=current_provider_id,
                        model_id=current_model_id,
                        now=now.timestamp(),
                    )

                accounted_cost = calculate_accounted_cost(
                    target_model,
                    provider_resp.usage.input_tokens,
                    provider_resp.usage.output_tokens,
                )

                succ_attempt = ExecutionAttempt(
                    attempt_number=attempt_counter,
                    attempt_id=attempt_id,
                    attempt_kind=kind,
                    model_id=current_model_id,
                    provider_id=current_provider_id,
                    outcome=ExecutionAttemptOutcome.SUCCEEDED,
                    estimated_cost_usd=current_estimated_cost,
                    actual_cost_usd=accounted_cost,
                    started_at=start_time,
                    completed_at=end_time,
                    latency_ms=provider_resp.latency_ms,
                    is_half_open_probe=is_half_open_probe,
                )
                attempts.append(succ_attempt)

                attempts_dicts = [execution_attempt_to_dict(a) for a in attempts]
                final_routing_reason = (
                    RoutingReason.FALLBACK_AFTER_TRANSIENT_FAILURE
                    if fallback_used
                    else current_decision.routing_reason
                )

                if db_manager is not None:
                    try:
                        async with db_manager.session_factory() as session:
                            await reconcile_actual_cost(
                                session=session,
                                request_id=str(request.request_id),
                                actual_cost_usd=accounted_cost,
                                input_tokens=provider_resp.usage.input_tokens,
                                output_tokens=provider_resp.usage.output_tokens,
                                total_tokens=provider_resp.usage.total_tokens,
                                provider_latency_ms=provider_resp.latency_ms,
                                execution_attempts=attempts_dicts,
                                retry_count=total_retry_count,
                                fallback_used=fallback_used,
                                selected_model_id=str(current_model_id),
                                selected_provider_id=str(current_provider_id),
                                routing_reason=str(
                                    final_routing_reason.value
                                    if hasattr(final_routing_reason, "value")
                                    else final_routing_reason
                                ),
                            )
                    except Exception:
                        pass

                chat_response = ChatResponse(
                    request_id=request.request_id,
                    response_id=f"chatcmpl-{request.request_id}",
                    model_id=current_model_id,
                    provider_id=current_provider_id,
                    content=provider_resp.content,
                    finish_reason=provider_resp.finish_reason,
                    usage=provider_resp.usage,
                    created_at=now,
                )

                final_decision = RoutingDecision(
                    request_id=request.request_id,
                    team_id=request.team_id,
                    feature_id=request.feature_id,
                    policy_id=policy.policy_id,
                    policy_version=policy.version,
                    candidates=current_decision.candidates,
                    routing_reason=final_routing_reason,
                    decided_at=now,
                    selected_model_id=current_model_id,
                    selected_provider_id=current_provider_id,
                    classifier_version=None,
                    fallback_used=fallback_used,
                    retry_count=total_retry_count,
                )

                # Quality Verification Sampling
                vp = policy.verification_policy
                if vp.enabled and db_manager is not None:
                    sampled = should_sample_verification(
                        request_id=request.request_id,
                        policy_id=policy.policy_id,
                        policy_version=policy.version,
                        sample_rate_basis_points=vp.sample_rate_basis_points,
                    )
                    if sampled and vp.reference_model_id:
                        ref_model_id = vp.reference_model_id
                        ref_model_def = model_by_id.get(ref_model_id)
                        ref_provider_id = (
                            ref_model_def.provider_id if ref_model_def else ProviderId("unknown")
                        )
                        verification_uuid = uuid.uuid4()
                        now_dt = utc_now()

                        if current_model_id == ref_model_id:
                            # Skip verification call when selected model is already reference model
                            skip_record = QualityVerificationRecord(
                                verification_id=verification_uuid,
                                request_id=str(request.request_id),
                                team_id=str(request.team_id),
                                feature_id=str(policy.feature_id),
                                policy_id=str(policy.policy_id),
                                policy_version=str(policy.version),
                                selected_model_id=str(current_model_id),
                                selected_provider_id=str(current_provider_id),
                                reference_model_id=str(ref_model_id),
                                reference_provider_id=str(ref_provider_id),
                                strategy=str(vp.strategy.value)
                                if vp.strategy
                                else "NORMALIZED_EXACT",
                                minimum_score=vp.minimum_score or Decimal("1.00000"),
                                status="SKIPPED",
                                failure_code="REFERENCE_MODEL_ALREADY_USED",
                                selected_output_hash=hash_text_output(provider_resp.content),
                                delivery_attempts=0,
                                queued_at=now_dt,
                                completed_at=now_dt,
                            )
                            try:
                                async with db_manager.session_factory() as session:
                                    session.add(skip_record)
                                    await session.commit()
                            except Exception:
                                pass
                        else:
                            strat_val = (
                                str(vp.strategy.value) if vp.strategy else "NORMALIZED_EXACT"
                            )
                            if vp.strategy == VerificationStrategy.JSON_FIELD_AGREEMENT:
                                sel_hash = hash_json_output(provider_resp.content)
                            else:
                                sel_hash = hash_text_output(provider_resp.content)

                            msg_dicts = [
                                {
                                    "role": str(
                                        m.role.value if hasattr(m.role, "value") else m.role
                                    ),
                                    "content": m.content,
                                }
                                for m in request.messages
                            ]
                            payload = {
                                "verification_id": str(verification_uuid),
                                "request_id": str(request.request_id),
                                "team_id": str(request.team_id),
                                "feature_id": str(policy.feature_id),
                                "policy_id": str(policy.policy_id),
                                "policy_version": str(policy.version),
                                "selected_model_id": str(current_model_id),
                                "selected_provider_id": str(current_provider_id),
                                "reference_model_id": str(ref_model_id),
                                "reference_provider_id": str(ref_provider_id),
                                "strategy": strat_val,
                                "minimum_score": str(vp.minimum_score or Decimal("1.00000")),
                                "messages": json.dumps(msg_dicts),
                                "output_format": str(request.output_format.value)
                                if request.output_format
                                else "",
                                "selected_response_content": provider_resp.content,
                                "queue_timestamp": now_dt.isoformat(),
                            }

                            raw_redis = (
                                getattr(redis_client, "redis", redis_client)
                                if redis_client
                                else None
                            )
                            enqueue_ok = False
                            stream_entry_id = ""
                            if raw_redis is not None:
                                try:
                                    stream_entry_id = await enqueue_verification_job(
                                        raw_redis, payload
                                    )
                                    enqueue_ok = True
                                except Exception:
                                    enqueue_ok = False

                            if enqueue_ok:
                                queued_record = QualityVerificationRecord(
                                    verification_id=verification_uuid,
                                    request_id=str(request.request_id),
                                    team_id=str(request.team_id),
                                    feature_id=str(policy.feature_id),
                                    policy_id=str(policy.policy_id),
                                    policy_version=str(policy.version),
                                    selected_model_id=str(current_model_id),
                                    selected_provider_id=str(current_provider_id),
                                    reference_model_id=str(ref_model_id),
                                    reference_provider_id=str(ref_provider_id),
                                    strategy=strat_val,
                                    minimum_score=vp.minimum_score or Decimal("1.00000"),
                                    status="QUEUED",
                                    selected_output_hash=sel_hash,
                                    delivery_attempts=0,
                                    queued_at=now_dt,
                                )
                                try:
                                    async with db_manager.session_factory() as session:
                                        session.add(queued_record)
                                        await session.commit()
                                except Exception:
                                    if raw_redis is not None and stream_entry_id:
                                        try:
                                            await ack_and_delete_verification_job(
                                                raw_redis, stream_entry_id
                                            )
                                        except Exception:
                                            pass

                return ExecutionResult(
                    success=True,
                    response=chat_response,
                    decision=final_decision,
                    attempts=tuple(attempts),
                    retry_count=total_retry_count,
                    fallback_used=fallback_used,
                    initial_model_id=initial_model_id,
                    initial_provider_id=initial_provider_id,
                    selected_model_id=current_model_id,
                    selected_provider_id=current_provider_id,
                )

            except ProviderExecutionError as err:
                end_time = utc_now()
                last_provider_error = err.error

                fail_attempt = ExecutionAttempt(
                    attempt_number=attempt_counter,
                    attempt_id=attempt_id,
                    attempt_kind=kind,
                    model_id=current_model_id,
                    provider_id=current_provider_id,
                    outcome=ExecutionAttemptOutcome.FAILED,
                    estimated_cost_usd=current_estimated_cost,
                    started_at=start_time,
                    completed_at=end_time,
                    error_code=err.error.code,
                    retryable=err.error.retryable,
                    provider_status_code=err.error.provider_status_code,
                    is_half_open_probe=is_half_open_probe,
                )
                attempts.append(fail_attempt)

                # Check if retryable and retry attempt count remaining on current pair
                if err.error.retryable and attempt_on_pair <= max_retries:
                    total_retry_count += 1
                    backoff_ms = calculate_exponential_backoff_ms(
                        policy.retry_policy.initial_backoff_ms, attempt_on_pair
                    )
                    await sleep_fn(backoff_ms / 1000.0)
                    continue

                # Not retryable or retries exhausted for current pair
                break

        # Finished attempts on current model pair.
        # Check circuit breaker recording and fallback eligibility.
        assert last_provider_error is not None
        is_last_error_retryable = last_provider_error.retryable

        if (
            circuit_breaker is not None
            and is_last_error_retryable
            and last_provider_error.code in TERMINAL_RETRYABLE_ERRORS
        ):
            await circuit_breaker.record_terminal_failure(
                provider_id=current_provider_id,
                model_id=current_model_id,
                policy=policy.circuit_breaker_policy,
                error_code=str(
                    last_provider_error.code.value
                    if hasattr(last_provider_error.code, "value")
                    else last_provider_error.code
                ),
                now=now.timestamp(),
            )
        elif circuit_breaker is not None and is_half_open_probe and not is_last_error_retryable:
            await circuit_breaker.release_half_open_probe(
                provider_id=current_provider_id,
                model_id=current_model_id,
            )

        is_pinned = (
            policy.pinned_model_id is not None and policy.pinned_model_id == initial_model_id
        )

        can_fallback = (
            is_last_error_retryable
            and policy.fallback_policy.enabled
            and (fallback_attempts_count < policy.fallback_policy.maximum_fallback_attempts)
            and not is_pinned
        )

        if not can_fallback:
            # Cannot fallback -> return final provider error
            attempts_dicts = [execution_attempt_to_dict(a) for a in attempts]
            err_code_str = (
                last_provider_error.code.value
                if hasattr(last_provider_error.code, "value")
                else str(last_provider_error.code)
            )

            if db_manager is not None:
                try:
                    async with db_manager.session_factory() as session:
                        await release_budget_reservation(
                            session=session,
                            request_id=str(request.request_id),
                            status_name="PROVIDER_ERROR",
                            error_code=err_code_str,
                            execution_attempts=attempts_dicts,
                            retry_count=total_retry_count,
                            fallback_used=fallback_used,
                        )
                except Exception:
                    pass

            return ExecutionResult(
                success=False,
                decision=current_decision,
                error=last_provider_error,
                error_code=last_provider_error.code,
                error_message=last_provider_error.message,
                http_status_code=502,
                attempts=tuple(attempts),
                retry_count=total_retry_count,
                fallback_used=fallback_used,
                initial_model_id=initial_model_id,
                initial_provider_id=initial_provider_id,
                selected_model_id=current_model_id,
                selected_provider_id=current_provider_id,
            )

        # Execute Fallback Route Selection
        excluded_pairs.add((current_provider_id, current_model_id))

        fallback_candidates: list[RoutingCandidate] = []
        for model in candidate_models:
            if (model.provider_id, model.model_id) in excluded_pairs:
                p_state = ProviderOperatingState.UNAVAILABLE
            else:
                snap = candidate_snapshots.get((model.provider_id, model.model_id))
                p_state = (
                    snap.provider_state if snap is not None else ProviderOperatingState.HEALTHY
                )
            try:
                est = build_candidate_estimate(
                    request=request,
                    model=model,
                    feature_id=policy.feature_id,
                    model_profile_registry=profile_registry,
                )
                fallback_candidates.append(
                    RoutingCandidate(
                        model=model,
                        estimate=est,
                        provider_state=p_state,
                    )
                )
            except ValueError:
                continue

        fallback_decision = route_request(
            request=request,
            policy=policy,
            candidates=fallback_candidates,
            decided_at=now,
        )

        if fallback_decision.selected_model_id is None:
            # No remaining eligible fallback candidate
            attempts_dicts = [execution_attempt_to_dict(a) for a in attempts]
            err_code_str = (
                last_provider_error.code.value
                if hasattr(last_provider_error.code, "value")
                else str(last_provider_error.code)
            )

            if db_manager is not None:
                try:
                    async with db_manager.session_factory() as session:
                        await release_budget_reservation(
                            session=session,
                            request_id=str(request.request_id),
                            status_name="PROVIDER_ERROR",
                            error_code=err_code_str,
                            execution_attempts=attempts_dicts,
                            retry_count=total_retry_count,
                            fallback_used=fallback_used,
                        )
                except Exception:
                    pass

            return ExecutionResult(
                success=False,
                decision=fallback_decision,
                error=last_provider_error,
                error_code=last_provider_error.code,
                error_message=last_provider_error.message,
                http_status_code=502,
                attempts=tuple(attempts),
                retry_count=total_retry_count,
                fallback_used=fallback_used,
                initial_model_id=initial_model_id,
                initial_provider_id=initial_provider_id,
                selected_model_id=current_model_id,
                selected_provider_id=current_provider_id,
            )

        fb_model_id = fallback_decision.selected_model_id
        fb_provider_id = fallback_decision.selected_provider_id

        fb_candidate = next(
            (c for c in fallback_candidates if c.model.model_id == fb_model_id),
            None,
        )
        fb_estimated_cost = (
            fb_candidate.estimate.estimated_cost_usd
            if fb_candidate is not None
            else Decimal("0.00010000")
        )

        # Atomic replacement of PostgreSQL budget reservation
        if db_manager is not None:
            try:
                async with db_manager.session_factory() as session:
                    (
                        fb_budget_allowed,
                        _mb,
                        _committed,
                    ) = await replace_budget_reservation(
                        session=session,
                        request_id=str(request.request_id),
                        team_id=str(request.team_id),
                        new_estimated_cost=fb_estimated_cost,
                        now=created_timestamp,
                    )
            except Exception:
                fb_budget_allowed = True
        else:
            fb_budget_allowed = True

        if not fb_budget_allowed:
            # Controlled fallback budget failure
            attempts_dicts = [execution_attempt_to_dict(a) for a in attempts]
            if db_manager is not None:
                try:
                    async with db_manager.session_factory() as session:
                        await release_budget_reservation(
                            session=session,
                            request_id=str(request.request_id),
                            status_name="BUDGET_REJECTED",
                            error_code="FALLBACK_BUDGET_EXCEEDED",
                            execution_attempts=attempts_dicts,
                            retry_count=total_retry_count,
                            fallback_used=fallback_used,
                        )
                except Exception:
                    pass

            return ExecutionResult(
                success=False,
                decision=fallback_decision,
                error_code=ErrorCode.FALLBACK_BUDGET_EXCEEDED,
                error_message="Fallback candidate estimate exceeded remaining team monthly budget.",
                http_status_code=402,
                attempts=tuple(attempts),
                retry_count=total_retry_count,
                fallback_used=fallback_used,
                initial_model_id=initial_model_id,
                initial_provider_id=initial_provider_id,
                selected_model_id=fb_model_id,
                selected_provider_id=fb_provider_id,
            )

        # Fallback budget approved -> update state and continue loop
        current_model_id = fb_model_id
        current_provider_id = fb_provider_id
        current_estimated_cost = fb_estimated_cost
        current_decision = fallback_decision
        fallback_used = True
        fallback_attempts_count += 1
