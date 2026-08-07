"""Command-line demonstration interface for RouteForge Milestone M1."""

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from routeforge.contracts import (
    AttemptId,
    CandidateEstimate,
    Capability,
    ChatMessage,
    ChatRequest,
    ChatRole,
    EstimateProvenance,
    FeatureId,
    FeaturePolicy,
    GovernanceClassification,
    ModelId,
    OutputFormat,
    ProviderOperatingState,
    ProviderRequest,
    RequestId,
    RoutingConstraints,
    TeamId,
    serialize_contract,
)
from routeforge.providers import DeterministicMockProvider
from routeforge.registries import RegistrySnapshot, load_registry_snapshot
from routeforge.routing import RoutingCandidate, route_request


class DemoValidationError(Exception):
    """Exception raised when a demonstration scenario JSON payload is invalid."""

    pass


@dataclass(frozen=True, slots=True)
class DemoScenario:
    """Decoded input payload for demonstration execution."""

    request: ChatRequest
    policy: FeaturePolicy
    candidates: list[RoutingCandidate]
    execution_template: dict[str, Any]
    decided_at: datetime


def _parse_utc_datetime(dt_str: str, field_name: str) -> datetime:
    if not isinstance(dt_str, str):
        raise DemoValidationError(f"Field '{field_name}' must be a string timestamp.")
    try:
        dt = datetime.fromisoformat(dt_str)
    except ValueError as err:
        raise DemoValidationError(
            f"Field '{field_name}' must be a valid ISO 8601 timestamp: {err}"
        ) from err
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise DemoValidationError(f"Timestamp '{field_name}' must be timezone-aware.")
    return dt.astimezone(UTC)


def _parse_decimal_str(val: Any, field_name: str) -> Decimal:
    if isinstance(val, float):
        raise DemoValidationError(
            f"Field '{field_name}' cannot be a float JSON number. Must be a decimal string."
        )
    if not isinstance(val, (str, int)):
        raise DemoValidationError(
            f"Field '{field_name}' must be a decimal string (e.g. \"0.001000\")."
        )
    try:
        return Decimal(str(val))
    except InvalidOperation as err:
        raise DemoValidationError(
            f"Field '{field_name}' value '{val}' is not a valid Decimal string."
        ) from err


def decode_demo_scenario(data: Any, snapshot: RegistrySnapshot) -> DemoScenario:
    """Decode and validate a demonstration scenario payload against a loaded snapshot."""
    if not isinstance(data, dict):
        raise DemoValidationError("Scenario JSON root must be an object.")

    allowed_root_keys = {"request", "policy", "candidates", "execution", "decided_at"}
    unknown_keys = set(data.keys()) - allowed_root_keys
    if unknown_keys:
        raise DemoValidationError(
            f"Unknown top-level field(s) in scenario JSON: {sorted(unknown_keys)}"
        )

    for required_root in ("request", "policy", "candidates", "execution", "decided_at"):
        if required_root not in data:
            raise DemoValidationError(
                f"Missing required top-level field '{required_root}' in scenario."
            )

    # 1. Parse Request
    req_dict = data["request"]
    if not isinstance(req_dict, dict):
        raise DemoValidationError("Field 'request' must be an object.")

    allowed_req_keys = {
        "request_id",
        "team_id",
        "feature_id",
        "messages",
        "output_format",
        "routing_constraints",
        "metadata",
        "created_at",
    }
    unknown_req = set(req_dict.keys()) - allowed_req_keys
    if unknown_req:
        raise DemoValidationError(f"Unknown field(s) in request payload: {sorted(unknown_req)}")

    for req_field in ("request_id", "team_id", "feature_id", "messages", "created_at"):
        if req_field not in req_dict:
            raise DemoValidationError(f"Missing required field '{req_field}' in request payload.")

    raw_msgs = req_dict["messages"]
    if not isinstance(raw_msgs, list) or not raw_msgs:
        raise DemoValidationError("Field 'messages' must be a non-empty list.")

    msgs: list[ChatMessage] = []
    for idx, msg in enumerate(raw_msgs):
        if not isinstance(msg, dict):
            raise DemoValidationError(f"Message at index {idx} must be an object.")
        if "role" not in msg or "content" not in msg:
            raise DemoValidationError(f"Message at index {idx} missing 'role' or 'content'.")
        try:
            role_enum = ChatRole(msg["role"])
        except ValueError as err:
            raise DemoValidationError(
                f"Invalid ChatRole '{msg['role']}' in message {idx}."
            ) from err
        msgs.append(ChatMessage(role=role_enum, content=str(msg["content"])))

    output_format = OutputFormat.TEXT
    if "output_format" in req_dict:
        try:
            output_format = OutputFormat(req_dict["output_format"])
        except ValueError as err:
            raise DemoValidationError(
                f"Invalid output_format '{req_dict['output_format']}'."
            ) from err

    # Parse routing constraints
    constraints = RoutingConstraints()
    if "routing_constraints" in req_dict:
        rc_dict = req_dict["routing_constraints"]
        if not isinstance(rc_dict, dict):
            raise DemoValidationError("Field 'routing_constraints' must be an object.")
        allowed_rc_keys = {
            "minimum_quality",
            "maximum_latency_ms",
            "maximum_estimated_cost_usd",
            "required_capabilities",
            "required_governance",
            "allow_degraded_provider",
        }
        unknown_rc = set(rc_dict.keys()) - allowed_rc_keys
        if unknown_rc:
            raise DemoValidationError(
                f"Unknown field(s) in routing_constraints: {sorted(unknown_rc)}"
            )

        min_q = (
            float(_parse_decimal_str(rc_dict["minimum_quality"], "minimum_quality"))
            if "minimum_quality" in rc_dict
            else None
        )
        max_lat = rc_dict.get("maximum_latency_ms")
        if max_lat is not None and (not isinstance(max_lat, int) or max_lat <= 0):
            raise DemoValidationError("Field 'maximum_latency_ms' must be a positive integer.")

        max_cost = (
            _parse_decimal_str(rc_dict["maximum_estimated_cost_usd"], "maximum_estimated_cost_usd")
            if "maximum_estimated_cost_usd" in rc_dict
            else None
        )

        req_caps: list[Capability] = []
        if "required_capabilities" in rc_dict:
            caps_list = rc_dict["required_capabilities"]
            if not isinstance(caps_list, list):
                raise DemoValidationError("Field 'required_capabilities' must be a list.")
            for c in caps_list:
                try:
                    req_caps.append(Capability(c))
                except ValueError as err:
                    raise DemoValidationError(f"Invalid capability '{c}'.") from err

        req_gov = None
        if "required_governance" in rc_dict and rc_dict["required_governance"] is not None:
            try:
                req_gov = GovernanceClassification(rc_dict["required_governance"])
            except ValueError as err:
                raise DemoValidationError(
                    f"Invalid governance '{rc_dict['required_governance']}'."
                ) from err

        allow_deg = rc_dict.get("allow_degraded_provider", False)

        constraints = RoutingConstraints(
            minimum_quality=min_q,
            maximum_latency_ms=max_lat,
            maximum_estimated_cost_usd=max_cost,
            required_capabilities=tuple(req_caps),
            required_governance=req_gov,
            allow_degraded_provider=allow_deg,
        )

    meta = req_dict.get("metadata", {})
    if not isinstance(meta, dict):
        raise DemoValidationError("Field 'metadata' must be an object.")

    created_at = _parse_utc_datetime(req_dict["created_at"], "created_at")

    chat_request = ChatRequest(
        request_id=RequestId(str(req_dict["request_id"])),
        team_id=TeamId(str(req_dict["team_id"])),
        feature_id=FeatureId(str(req_dict["feature_id"])),
        messages=tuple(msgs),
        output_format=output_format,
        routing_constraints=constraints,
        metadata=meta,
        created_at=created_at,
    )

    # 2. Resolve Policy
    pol_dict = data["policy"]
    if not isinstance(pol_dict, dict):
        raise DemoValidationError("Field 'policy' must be an object.")

    feature_id = chat_request.feature_id
    policy = snapshot.policies.get_active_for_feature(feature_id)
    if policy is None:
        raise DemoValidationError(
            f"No active feature policy found for feature_id '{feature_id}' in snapshot."
        )

    # 3. Parse Candidates
    cand_list = data["candidates"]
    if not isinstance(cand_list, list) or not cand_list:
        raise DemoValidationError("Field 'candidates' must be a non-empty list.")

    candidates: list[RoutingCandidate] = []
    seen_model_ids: set[ModelId] = set()

    for idx, c_dict in enumerate(cand_list):
        if not isinstance(c_dict, dict):
            raise DemoValidationError(f"Candidate at index {idx} must be an object.")
        allowed_c_keys = {"model_id", "provider_state", "estimate"}
        unknown_c = set(c_dict.keys()) - allowed_c_keys
        if unknown_c:
            raise DemoValidationError(f"Unknown field(s) in candidate {idx}: {sorted(unknown_c)}")

        for req_c in ("model_id", "provider_state", "estimate"):
            if req_c not in c_dict:
                raise DemoValidationError(f"Missing required field '{req_c}' in candidate {idx}.")

        m_id = ModelId(str(c_dict["model_id"]))
        if m_id in seen_model_ids:
            raise DemoValidationError(f"Duplicate candidate model_id '{m_id}' in scenario.")
        seen_model_ids.add(m_id)

        model_def = snapshot.models.get(m_id)
        if model_def is None:
            raise DemoValidationError(
                f"Candidate model_id '{m_id}' not found in loaded ModelRegistry."
            )

        try:
            p_state = ProviderOperatingState(c_dict["provider_state"])
        except ValueError as err:
            raise DemoValidationError(
                f"Invalid provider_state '{c_dict['provider_state']}' in candidate {idx}."
            ) from err

        est_dict = c_dict["estimate"]
        if not isinstance(est_dict, dict):
            raise DemoValidationError(f"Field 'estimate' in candidate {idx} must be an object.")

        for req_e in (
            "predicted_quality",
            "estimated_latency_ms",
            "estimated_cost_usd",
            "quality_provenance",
            "latency_provenance",
            "cost_provenance",
        ):
            if req_e not in est_dict:
                raise DemoValidationError(
                    f"Missing required field '{req_e}' in estimate for candidate {idx}."
                )

        q_val = float(_parse_decimal_str(est_dict["predicted_quality"], "predicted_quality"))
        lat_val = est_dict["estimated_latency_ms"]
        if not isinstance(lat_val, int) or lat_val <= 0:
            raise DemoValidationError("Field 'estimated_latency_ms' must be a positive integer.")
        cost_val = _parse_decimal_str(est_dict["estimated_cost_usd"], "estimated_cost_usd")

        q_prov = EstimateProvenance(
            source=str(est_dict["quality_provenance"].get("source", "demo")),
            version=str(est_dict["quality_provenance"].get("version", "v1")),
        )
        l_prov = EstimateProvenance(
            source=str(est_dict["latency_provenance"].get("source", "demo")),
            version=str(est_dict["latency_provenance"].get("version", "v1")),
        )
        c_prov = EstimateProvenance(
            source=str(est_dict["cost_provenance"].get("source", "demo")),
            version=str(est_dict["cost_provenance"].get("version", "v1")),
        )

        estimate = CandidateEstimate(
            predicted_quality=q_val,
            estimated_latency_ms=lat_val,
            estimated_cost_usd=cost_val,
            quality_provenance=q_prov,
            latency_provenance=l_prov,
            cost_provenance=c_prov,
        )

        candidates.append(
            RoutingCandidate(model=model_def, estimate=estimate, provider_state=p_state)
        )

    # 4. Parse Execution Template & Decided At
    exec_dict = data["execution"]
    if not isinstance(exec_dict, dict):
        raise DemoValidationError("Field 'execution' must be an object.")
    if "attempt_id" not in exec_dict or "timeout_ms" not in exec_dict:
        raise DemoValidationError("Field 'execution' missing required attempt_id or timeout_ms.")

    decided_at = _parse_utc_datetime(data["decided_at"], "decided_at")

    return DemoScenario(
        request=chat_request,
        policy=policy,
        candidates=candidates,
        execution_template=exec_dict,
        decided_at=decided_at,
    )


def run_demo(
    scenario_path: Path,
    models_dir: Path,
    policies_dir: Path,
    route_only: bool = False,
    pretty: bool = False,
) -> tuple[int, str]:
    """Execute the CLI demonstration flow and return (exit_code, json_output_string)."""
    if not scenario_path.exists():
        sys.stderr.write(f"Error: Scenario file '{scenario_path}' does not exist.\n")
        return 1, ""

    try:
        with open(scenario_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as err:
        sys.stderr.write(f"Error reading scenario JSON: {err}\n")
        return 1, ""

    if not models_dir.exists() or not policies_dir.exists():
        sys.stderr.write(
            f"Error: Models directory '{models_dir}' or "
            f"policies directory '{policies_dir}' missing.\n"
        )
        return 1, ""

    try:
        snapshot = load_registry_snapshot(
            models_directory=models_dir,
            policies_directory=policies_dir,
        )
        scenario = decode_demo_scenario(data, snapshot)
    except Exception as err:
        sys.stderr.write(f"Error parsing scenario: {err}\n")
        return 1, ""

    # Execute deterministic routing
    decision = route_request(
        request=scenario.request,
        policy=scenario.policy,
        candidates=scenario.candidates,
        decided_at=scenario.decided_at,
    )

    provider_response_serialized = None
    exit_code = 0

    if decision.selected_model_id is None:
        exit_code = 2
    elif not route_only:
        selected_model = snapshot.models.get(decision.selected_model_id)
        if selected_model is not None:
            exec_dict = scenario.execution_template
            p_req = ProviderRequest(
                request_id=scenario.request.request_id,
                attempt_id=AttemptId(str(exec_dict["attempt_id"])),
                model_id=selected_model.model_id,
                messages=scenario.request.messages,
                output_format=scenario.request.output_format,
                timeout_ms=int(exec_dict["timeout_ms"]),
                idempotency_key=str(exec_dict.get("idempotency_key", "")),
            )
            provider = DeterministicMockProvider()
            try:
                p_resp = asyncio.run(provider.complete(p_req, selected_model))
                provider_response_serialized = serialize_contract(p_resp)
            except Exception as err:
                sys.stderr.write(f"Error during provider execution: {err}\n")
                return 1, ""

    output_doc = {
        "demo_version": "m1",
        "routing_decision": serialize_contract(decision),
        "provider_response": provider_response_serialized,
    }

    indent = 2 if pretty else None
    json_out = json.dumps(output_doc, indent=indent, sort_keys=True)
    return exit_code, json_out


def main(args: list[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="routeforge",
        description="RouteForge LLM Gateway CLI Demonstration (Milestone M1)",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    demo_parser = subparsers.add_parser("demo", help="Run an M1 demonstration scenario")
    demo_parser.add_argument(
        "scenario",
        type=Path,
        help="Path to scenario JSON file (e.g. examples/m1/general-chat.json)",
    )
    demo_parser.add_argument(
        "--models-directory",
        type=Path,
        default=Path("config/models"),
        help="Path to models config directory (default: config/models)",
    )
    demo_parser.add_argument(
        "--policies-directory",
        type=Path,
        default=Path("config/policies"),
        help="Path to policies config directory (default: config/policies)",
    )
    demo_parser.add_argument(
        "--route-only",
        action="store_true",
        help="Stop after producing routing decision without executing provider",
    )
    demo_parser.add_argument(
        "--pretty", action="store_true", help="Format JSON output with indentation"
    )

    parsed = parser.parse_args(args)

    if parsed.command != "demo":
        parser.print_help(sys.stderr)
        return 1

    exit_code, json_out = run_demo(
        scenario_path=parsed.scenario,
        models_dir=parsed.models_directory,
        policies_dir=parsed.policies_directory,
        route_only=parsed.route_only,
        pretty=parsed.pretty,
    )

    if json_out:
        print(json_out)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
