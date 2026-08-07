"""Deterministic gateway candidate estimator supporting measured model profiles."""

from decimal import Decimal

from routeforge.contracts import (
    CandidateEstimate,
    EstimateProvenance,
    FeatureId,
    ModelDefinition,
    OutputFormat,
)
from routeforge.contracts.inference import ChatRequest
from routeforge.evaluation.model_profiles import ModelProfileRegistry


def classify_request_task_type(request: ChatRequest, feature_id: FeatureId) -> str:
    """Deterministically classify request task type based on explicit signals."""
    fid_str = str(feature_id).lower()
    known_tasks = {
        "classification",
        "structured-extraction",
        "json-generation",
        "summarization",
        "grounded-qa",
        "reasoning",
    }
    if fid_str in known_tasks:
        return fid_str

    if request.output_format == OutputFormat.JSON:
        return "json-generation"

    if request.messages:
        content_lower = request.messages[-1].content.lower()
        if "classify" in content_lower or "sentiment" in content_lower:
            return "classification"
        if "summarize" in content_lower or "summary" in content_lower:
            return "summarization"
        if "extract" in content_lower:
            return "structured-extraction"
        if "context:" in content_lower or "question:" in content_lower:
            return "grounded-qa"

    return "general"


def estimate_input_tokens(request: ChatRequest) -> int:
    """Deterministically estimate input token count from request messages."""
    token_count = 0
    for msg in request.messages:
        words = msg.content.split()
        token_count += max(1, len(words))
    return token_count


def build_candidate_estimate(
    *,
    request: ChatRequest,
    model: ModelDefinition,
    feature_id: FeatureId,
    model_profile_registry: ModelProfileRegistry | None = None,
) -> CandidateEstimate:
    """Build candidate metric estimate using model definition or active measured profile."""
    task_type = classify_request_task_type(request, feature_id)

    if model_profile_registry is not None and model.model_id in model_profile_registry.profiles:
        measured_profile = model_profile_registry.get_quality_profile(
            model.model_id,
            task_type,
        )
        if measured_profile is not None:
            predicted_quality = measured_profile.measured_quality
            estimated_latency_ms = measured_profile.measured_median_latency_ms
            provenance = EstimateProvenance(
                source=f"measured-profile-{measured_profile.source_benchmark_file}",
                version=measured_profile.evaluator_version,
            )
        else:
            # If no measured profile exists for this task on a profiled model,
            # mark quality as 0.0 to make candidate ineligible cleanly.
            predicted_quality = 0.0
            estimated_latency_ms = model.estimated_latency_ms
            provenance = EstimateProvenance(
                source="measured-profile-missing",
                version="v1-unmeasured-task",
            )
    else:
        matching_profile = next(
            (p for p in model.quality_profiles if p.task_type == task_type),
            None,
        )
        if matching_profile is None:
            matching_profile = next(
                (p for p in model.quality_profiles if p.task_type == str(feature_id)),
                None,
            )
        if matching_profile is None:
            matching_profile = next(
                (p for p in model.quality_profiles if p.task_type == "general"),
                None,
            )

        if matching_profile is None:
            raise ValueError(
                f"Model '{model.model_id}' has no quality profile matching task '{task_type}'."
            )

        predicted_quality = matching_profile.predicted_quality
        estimated_latency_ms = model.estimated_latency_ms
        provenance = EstimateProvenance(
            source="m2-deterministic-estimator",
            version="v1-output-budget-128",
        )

    input_tokens = estimate_input_tokens(request)
    output_tokens = 128

    input_cost = (
        Decimal(input_tokens) * model.estimated_input_cost_per_million_tokens_usd
    ) / Decimal("1000000")
    output_cost = (
        Decimal(output_tokens) * model.estimated_output_cost_per_million_tokens_usd
    ) / Decimal("1000000")
    estimated_cost_usd = input_cost + output_cost

    return CandidateEstimate(
        predicted_quality=predicted_quality,
        estimated_latency_ms=estimated_latency_ms,
        estimated_cost_usd=estimated_cost_usd,
        quality_provenance=provenance,
        latency_provenance=provenance,
        cost_provenance=provenance,
    )
