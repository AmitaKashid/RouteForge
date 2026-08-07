"""Unit tests for routing candidate evaluations, estimates, and routing decisions."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from routeforge.contracts.common import (
    FeatureId,
    ModelId,
    PolicyId,
    PolicyVersion,
    ProviderId,
    RequestId,
    TeamId,
)
from routeforge.contracts.errors import CandidateRejectionReason, RoutingReason
from routeforge.contracts.routing import (
    CandidateEstimate,
    CandidateEvaluation,
    EstimateProvenance,
    RoutingDecision,
)


@pytest.fixture
def sample_estimate() -> CandidateEstimate:
    prov = EstimateProvenance(source="static_benchmarks", version="1.0.0")
    return CandidateEstimate(
        predicted_quality=0.9,
        estimated_latency_ms=300,
        estimated_cost_usd=Decimal("0.002"),
        quality_provenance=prov,
        latency_provenance=prov,
        cost_provenance=prov,
    )


def test_estimate_provenance_validation() -> None:
    with pytest.raises(ValueError, match="source cannot be empty"):
        EstimateProvenance(source=" ", version="v1")

    with pytest.raises(ValueError, match="version cannot be empty"):
        EstimateProvenance(source="src", version=" ")


def test_candidate_estimate_validation() -> None:
    prov = EstimateProvenance(source="src", version="v1")

    with pytest.raises(ValueError, match="predicted_quality must be between"):
        CandidateEstimate(
            predicted_quality=1.2,
            estimated_latency_ms=100,
            estimated_cost_usd=Decimal("0.01"),
            quality_provenance=prov,
            latency_provenance=prov,
            cost_provenance=prov,
        )

    with pytest.raises(ValueError, match="estimated_latency_ms must not be negative"):
        CandidateEstimate(
            predicted_quality=0.9,
            estimated_latency_ms=-10,
            estimated_cost_usd=Decimal("0.01"),
            quality_provenance=prov,
            latency_provenance=prov,
            cost_provenance=prov,
        )

    with pytest.raises(ValueError, match="estimated_cost_usd must not be negative"):
        CandidateEstimate(
            predicted_quality=0.9,
            estimated_latency_ms=100,
            estimated_cost_usd=Decimal("-0.01"),
            quality_provenance=prov,
            latency_provenance=prov,
            cost_provenance=prov,
        )


def test_candidate_evaluation_invalid_identifiers(sample_estimate: CandidateEstimate) -> None:
    with pytest.raises(ValueError, match="model_id cannot be empty"):
        CandidateEvaluation(
            model_id=ModelId(""),
            provider_id=ProviderId("p1"),
            eligible=True,
            rejection_reasons=(),
            estimate=sample_estimate,
        )

    with pytest.raises(ValueError, match="provider_id cannot be empty"):
        CandidateEvaluation(
            model_id=ModelId("m1"),
            provider_id=ProviderId(""),
            eligible=True,
            rejection_reasons=(),
            estimate=sample_estimate,
        )


def test_eligible_candidate_evaluation(sample_estimate: CandidateEstimate) -> None:
    eval_res = CandidateEvaluation(
        model_id=ModelId("gpt-4o"),
        provider_id=ProviderId("openai"),
        eligible=True,
        rejection_reasons=(),
        estimate=sample_estimate,
    )
    assert eval_res.eligible is True
    assert eval_res.rejection_reasons == ()


def test_ineligible_candidate_evaluation(sample_estimate: CandidateEstimate) -> None:
    eval_res = CandidateEvaluation(
        model_id=ModelId("gpt-3.5-turbo"),
        provider_id=ProviderId("openai"),
        eligible=False,
        rejection_reasons=(CandidateRejectionReason.QUALITY_BELOW_THRESHOLD,),
        estimate=sample_estimate,
    )
    assert eval_res.eligible is False
    assert CandidateRejectionReason.QUALITY_BELOW_THRESHOLD in eval_res.rejection_reasons


def test_contradictory_candidate_state_rejected(sample_estimate: CandidateEstimate) -> None:
    with pytest.raises(ValueError, match="eligible candidate must not have rejection reasons"):
        CandidateEvaluation(
            model_id=ModelId("m1"),
            provider_id=ProviderId("p1"),
            eligible=True,
            rejection_reasons=(CandidateRejectionReason.COST_ABOVE_REQUEST_LIMIT,),
            estimate=sample_estimate,
        )

    with pytest.raises(ValueError, match="ineligible candidate must have at least one"):
        CandidateEvaluation(
            model_id=ModelId("m1"),
            provider_id=ProviderId("p1"),
            eligible=False,
            rejection_reasons=(),
            estimate=sample_estimate,
        )


def test_successful_routing_decision(sample_estimate: CandidateEstimate) -> None:
    cand = CandidateEvaluation(
        model_id=ModelId("gpt-4o"),
        provider_id=ProviderId("openai"),
        eligible=True,
        rejection_reasons=(),
        estimate=sample_estimate,
    )
    decision = RoutingDecision(
        request_id=RequestId("req_1"),
        team_id=TeamId("team_1"),
        feature_id=FeatureId("feat_1"),
        policy_id=PolicyId("pol_1"),
        policy_version=PolicyVersion("v1"),
        candidates=(cand,),
        routing_reason=RoutingReason.CHEAPEST_ELIGIBLE_MODEL,
        decided_at=datetime.now(UTC),
        selected_model_id=ModelId("gpt-4o"),
        selected_provider_id=ProviderId("openai"),
    )
    assert decision.selected_model_id == ModelId("gpt-4o")
    assert decision.routing_reason == RoutingReason.CHEAPEST_ELIGIBLE_MODEL


def test_no_eligible_model_decision(sample_estimate: CandidateEstimate) -> None:
    cand = CandidateEvaluation(
        model_id=ModelId("gpt-3.5-turbo"),
        provider_id=ProviderId("openai"),
        eligible=False,
        rejection_reasons=(CandidateRejectionReason.QUALITY_BELOW_THRESHOLD,),
        estimate=sample_estimate,
    )
    decision = RoutingDecision(
        request_id=RequestId("req_1"),
        team_id=TeamId("team_1"),
        feature_id=FeatureId("feat_1"),
        policy_id=PolicyId("pol_1"),
        policy_version=PolicyVersion("v1"),
        candidates=(cand,),
        routing_reason=RoutingReason.NO_ELIGIBLE_MODEL,
        decided_at=datetime.now(UTC),
        selected_model_id=None,
        selected_provider_id=None,
    )
    assert decision.selected_model_id is None
    assert decision.routing_reason == RoutingReason.NO_ELIGIBLE_MODEL


def test_routing_decision_invalid_identifiers_and_empty_candidates(
    sample_estimate: CandidateEstimate,
) -> None:
    now = datetime.now(UTC)
    cand = CandidateEvaluation(
        model_id=ModelId("gpt-4o"),
        provider_id=ProviderId("openai"),
        eligible=True,
        rejection_reasons=(),
        estimate=sample_estimate,
    )
    cands = (cand,)

    with pytest.raises(ValueError, match="request_id cannot be empty"):
        RoutingDecision(
            request_id=RequestId(""),
            team_id=TeamId("t1"),
            feature_id=FeatureId("f1"),
            policy_id=PolicyId("p1"),
            policy_version=PolicyVersion("v1"),
            candidates=cands,
            routing_reason=RoutingReason.CHEAPEST_ELIGIBLE_MODEL,
            decided_at=now,
            selected_model_id=ModelId("gpt-4o"),
            selected_provider_id=ProviderId("openai"),
        )

    with pytest.raises(ValueError, match="team_id cannot be empty"):
        RoutingDecision(
            request_id=RequestId("req_1"),
            team_id=TeamId(""),
            feature_id=FeatureId("f1"),
            policy_id=PolicyId("p1"),
            policy_version=PolicyVersion("v1"),
            candidates=cands,
            routing_reason=RoutingReason.CHEAPEST_ELIGIBLE_MODEL,
            decided_at=now,
            selected_model_id=ModelId("gpt-4o"),
            selected_provider_id=ProviderId("openai"),
        )

    with pytest.raises(ValueError, match="feature_id cannot be empty"):
        RoutingDecision(
            request_id=RequestId("req_1"),
            team_id=TeamId("t1"),
            feature_id=FeatureId(""),
            policy_id=PolicyId("p1"),
            policy_version=PolicyVersion("v1"),
            candidates=cands,
            routing_reason=RoutingReason.CHEAPEST_ELIGIBLE_MODEL,
            decided_at=now,
            selected_model_id=ModelId("gpt-4o"),
            selected_provider_id=ProviderId("openai"),
        )

    with pytest.raises(ValueError, match="policy_id cannot be empty"):
        RoutingDecision(
            request_id=RequestId("req_1"),
            team_id=TeamId("t1"),
            feature_id=FeatureId("f1"),
            policy_id=PolicyId(""),
            policy_version=PolicyVersion("v1"),
            candidates=cands,
            routing_reason=RoutingReason.CHEAPEST_ELIGIBLE_MODEL,
            decided_at=now,
            selected_model_id=ModelId("gpt-4o"),
            selected_provider_id=ProviderId("openai"),
        )

    with pytest.raises(ValueError, match="policy_version cannot be empty"):
        RoutingDecision(
            request_id=RequestId("req_1"),
            team_id=TeamId("t1"),
            feature_id=FeatureId("f1"),
            policy_id=PolicyId("p1"),
            policy_version=PolicyVersion(""),
            candidates=cands,
            routing_reason=RoutingReason.CHEAPEST_ELIGIBLE_MODEL,
            decided_at=now,
            selected_model_id=ModelId("gpt-4o"),
            selected_provider_id=ProviderId("openai"),
        )

    with pytest.raises(ValueError, match="candidates cannot be empty"):
        RoutingDecision(
            request_id=RequestId("req_1"),
            team_id=TeamId("t1"),
            feature_id=FeatureId("f1"),
            policy_id=PolicyId("p1"),
            policy_version=PolicyVersion("v1"),
            candidates=(),
            routing_reason=RoutingReason.NO_ELIGIBLE_MODEL,
            decided_at=now,
        )


def test_selected_model_missing_from_candidates_rejected(
    sample_estimate: CandidateEstimate,
) -> None:
    cand = CandidateEvaluation(
        model_id=ModelId("gpt-4o"),
        provider_id=ProviderId("openai"),
        eligible=True,
        rejection_reasons=(),
        estimate=sample_estimate,
    )
    with pytest.raises(ValueError, match="is not present in candidates list"):
        RoutingDecision(
            request_id=RequestId("req_1"),
            team_id=TeamId("t1"),
            feature_id=FeatureId("f1"),
            policy_id=PolicyId("p1"),
            policy_version=PolicyVersion("v1"),
            candidates=(cand,),
            routing_reason=RoutingReason.CHEAPEST_ELIGIBLE_MODEL,
            decided_at=datetime.now(UTC),
            selected_model_id=ModelId("claude-3-5-sonnet"),
            selected_provider_id=ProviderId("anthropic"),
        )


def test_selected_ineligible_model_rejected(sample_estimate: CandidateEstimate) -> None:
    cand = CandidateEvaluation(
        model_id=ModelId("gpt-3.5-turbo"),
        provider_id=ProviderId("openai"),
        eligible=False,
        rejection_reasons=(CandidateRejectionReason.QUALITY_BELOW_THRESHOLD,),
        estimate=sample_estimate,
    )
    with pytest.raises(ValueError, match="must be an eligible candidate"):
        RoutingDecision(
            request_id=RequestId("req_1"),
            team_id=TeamId("t1"),
            feature_id=FeatureId("f1"),
            policy_id=PolicyId("p1"),
            policy_version=PolicyVersion("v1"),
            candidates=(cand,),
            routing_reason=RoutingReason.CHEAPEST_ELIGIBLE_MODEL,
            decided_at=datetime.now(UTC),
            selected_model_id=ModelId("gpt-3.5-turbo"),
            selected_provider_id=ProviderId("openai"),
        )


def test_partially_missing_selected_pair_rejected(sample_estimate: CandidateEstimate) -> None:
    cand = CandidateEvaluation(
        model_id=ModelId("gpt-4o"),
        provider_id=ProviderId("openai"),
        eligible=True,
        rejection_reasons=(),
        estimate=sample_estimate,
    )
    with pytest.raises(ValueError, match="must both be present or both absent"):
        RoutingDecision(
            request_id=RequestId("req_1"),
            team_id=TeamId("t1"),
            feature_id=FeatureId("f1"),
            policy_id=PolicyId("p1"),
            policy_version=PolicyVersion("v1"),
            candidates=(cand,),
            routing_reason=RoutingReason.CHEAPEST_ELIGIBLE_MODEL,
            decided_at=datetime.now(UTC),
            selected_model_id=ModelId("gpt-4o"),
            selected_provider_id=None,
        )


def test_no_eligible_model_with_selected_model_rejected(
    sample_estimate: CandidateEstimate,
) -> None:
    cand = CandidateEvaluation(
        model_id=ModelId("gpt-4o"),
        provider_id=ProviderId("openai"),
        eligible=True,
        rejection_reasons=(),
        estimate=sample_estimate,
    )
    with pytest.raises(ValueError, match="NO_ELIGIBLE_MODEL requires selected_model_id"):
        RoutingDecision(
            request_id=RequestId("req_1"),
            team_id=TeamId("t1"),
            feature_id=FeatureId("f1"),
            policy_id=PolicyId("p1"),
            policy_version=PolicyVersion("v1"),
            candidates=(cand,),
            routing_reason=RoutingReason.NO_ELIGIBLE_MODEL,
            decided_at=datetime.now(UTC),
            selected_model_id=ModelId("gpt-4o"),
            selected_provider_id=ProviderId("openai"),
        )


def test_successful_routing_reason_without_selected_model_rejected(
    sample_estimate: CandidateEstimate,
) -> None:
    cand = CandidateEvaluation(
        model_id=ModelId("gpt-4o"),
        provider_id=ProviderId("openai"),
        eligible=True,
        rejection_reasons=(),
        estimate=sample_estimate,
    )
    with pytest.raises(ValueError, match="requires selected_model_id"):
        RoutingDecision(
            request_id=RequestId("req_1"),
            team_id=TeamId("t1"),
            feature_id=FeatureId("f1"),
            policy_id=PolicyId("p1"),
            policy_version=PolicyVersion("v1"),
            candidates=(cand,),
            routing_reason=RoutingReason.CHEAPEST_ELIGIBLE_MODEL,
            decided_at=datetime.now(UTC),
            selected_model_id=None,
            selected_provider_id=None,
        )


def test_negative_retry_count_rejected(sample_estimate: CandidateEstimate) -> None:
    cand = CandidateEvaluation(
        model_id=ModelId("gpt-4o"),
        provider_id=ProviderId("openai"),
        eligible=True,
        rejection_reasons=(),
        estimate=sample_estimate,
    )
    with pytest.raises(ValueError, match="retry_count must not be negative"):
        RoutingDecision(
            request_id=RequestId("req_1"),
            team_id=TeamId("t1"),
            feature_id=FeatureId("f1"),
            policy_id=PolicyId("p1"),
            policy_version=PolicyVersion("v1"),
            candidates=(cand,),
            routing_reason=RoutingReason.CHEAPEST_ELIGIBLE_MODEL,
            decided_at=datetime.now(UTC),
            selected_model_id=ModelId("gpt-4o"),
            selected_provider_id=ProviderId("openai"),
            retry_count=-1,
        )


def test_timezone_naive_decision_time_rejected(sample_estimate: CandidateEstimate) -> None:
    cand = CandidateEvaluation(
        model_id=ModelId("gpt-4o"),
        provider_id=ProviderId("openai"),
        eligible=True,
        rejection_reasons=(),
        estimate=sample_estimate,
    )
    with pytest.raises(ValueError, match="must be timezone-aware"):
        RoutingDecision(
            request_id=RequestId("req_1"),
            team_id=TeamId("t1"),
            feature_id=FeatureId("f1"),
            policy_id=PolicyId("p1"),
            policy_version=PolicyVersion("v1"),
            candidates=(cand,),
            routing_reason=RoutingReason.CHEAPEST_ELIGIBLE_MODEL,
            decided_at=datetime(2026, 1, 1, 10, 0, 0),
            selected_model_id=ModelId("gpt-4o"),
            selected_provider_id=ProviderId("openai"),
        )
