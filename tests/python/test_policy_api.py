import shutil
import subprocess
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import travel_plan_permission.policy_api as policy_api_module
from travel_plan_permission import (
    ExceptionRequest,
    ExceptionType,
    ExpenseCategory,
    ExpenseItem,
    PlannerCorrelationId,
    PlannerPolicySnapshotRequest,
    PlannerProposalEvaluationRequest,
    PlannerProposalEvaluationResult,
    PlannerProposalStatusRequest,
    PlannerProposalSubmissionRequest,
    PolicyCheckResult,
    PolicyContext,
    PolicyEngine,
    PolicyResult,
    PolicyRule,
    Receipt,
    ReconciliationResult,
    Severity,
    TripPlan,
    check_trip_plan,
    get_evaluation_result,
    get_policy_snapshot,
    list_allowed_vendors,
    poll_execution_status,
    reconcile,
    submit_proposal,
)


@pytest.fixture()
def trip_plan() -> TripPlan:
    return TripPlan(
        trip_id="TRIP-API-001",
        traveler_name="Alex Rivera",
        destination="New York, NY",
        departure_date=date(2024, 9, 15),
        return_date=date(2024, 9, 20),
        purpose="Client workshop",
        estimated_cost=Decimal("1000.00"),
    )


@pytest.fixture()
def over_budget_receipts() -> list[Receipt]:
    return [
        Receipt(
            total=Decimal("500.00"),
            date=date(2024, 9, 16),
            vendor="Metro Cab",
            file_reference="receipt-001.pdf",
            file_size_bytes=1024,
        ),
        Receipt(
            total=Decimal("700.00"),
            date=date(2024, 9, 17),
            vendor="Hotel Central",
            file_reference="receipt-002.png",
            file_size_bytes=2048,
        ),
    ]


@pytest.fixture()
def matching_receipts() -> list[Receipt]:
    return [
        Receipt(
            total=Decimal("250.00"),
            date=date(2024, 9, 16),
            vendor="Metro Cab",
            file_reference="receipt-003.pdf",
            file_size_bytes=512,
        ),
        Receipt(
            total=Decimal("750.00"),
            date=date(2024, 9, 18),
            vendor="Hotel Central",
            file_reference="receipt-004.png",
            file_size_bytes=1024,
        ),
    ]


def test_check_trip_plan_reports_policy_issues(trip_plan: TripPlan) -> None:
    result = check_trip_plan(trip_plan)

    assert isinstance(result, PolicyCheckResult)
    assert result.policy_version
    assert result.status == "fail"
    assert any(issue.code == "fare_evidence" for issue in result.issues)
    for issue in result.issues:
        assert issue.context["rule_id"] == issue.code


def test_check_trip_plan_triggers_fare_comparison_when_inputs_present(
    trip_plan: TripPlan,
) -> None:
    plan = trip_plan.model_copy(
        update={
            "booking_date": date(2024, 8, 1),
            "departure_date": date(2024, 9, 15),
            "return_date": date(2024, 9, 20),
            "selected_fare": Decimal("650.00"),
            "lowest_fare": Decimal("300.00"),
            "cabin_class": "economy",
            "flight_duration_hours": 3.5,
            "fare_evidence_attached": True,
            "driving_cost": Decimal("120.00"),
            "flight_cost": Decimal("200.00"),
            "comparable_hotels": [Decimal("150.00"), Decimal("175.00")],
            "overnight_stay": False,
            "meals_provided": False,
            "meal_per_diem_requested": True,
            "expenses": [
                ExpenseItem(
                    category=ExpenseCategory.GROUND_TRANSPORT,
                    description="Airport shuttle",
                    vendor="City Shuttle",
                    amount=Decimal("45.00"),
                    expense_date=date(2024, 9, 15),
                    receipt_attached=True,
                )
            ],
            "third_party_payments": [
                {"description": "Sponsor covered ticket", "itemized": True}
            ],
        }
    )

    result = check_trip_plan(plan)

    assert any(issue.code == "fare_comparison" for issue in result.issues)


def test_check_trip_plan_reports_pass_when_no_rules(
    trip_plan: TripPlan, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        PolicyEngine, "from_file", lambda *_args, **_kwargs: PolicyEngine([])
    )

    result = check_trip_plan(trip_plan)

    assert result.status == "pass"
    assert result.issues == []
    assert result.policy_version


def test_check_trip_plan_passes_with_only_advisories(
    trip_plan: TripPlan, monkeypatch: pytest.MonkeyPatch
) -> None:
    class AdvisoryRule(PolicyRule):
        rule_id = "advisory_only"

        def __init__(self) -> None:
            super().__init__(Severity.ADVISORY)

        def evaluate(self, _context: PolicyContext) -> PolicyResult:
            return PolicyResult(
                rule_id=self.rule_id,
                severity=self.severity,
                passed=False,
                message="Advisory issue.",
            )

        def message(self) -> str:
            return "Advisory issue."

    engine = PolicyEngine([AdvisoryRule()])
    monkeypatch.setattr(PolicyEngine, "from_file", lambda *_args, **_kwargs: engine)

    result = check_trip_plan(trip_plan)

    assert result.status == "pass"
    assert len(result.issues) == 1
    assert result.issues[0].code == "advisory_only"
    assert result.issues[0].severity == "warning"


def test_check_trip_plan_fails_with_blocking_and_advisory_rules(
    trip_plan: TripPlan, monkeypatch: pytest.MonkeyPatch
) -> None:
    class BlockingRule(PolicyRule):
        rule_id = "blocking_rule"

        def __init__(self) -> None:
            super().__init__(Severity.BLOCKING)

        def evaluate(self, _context: PolicyContext) -> PolicyResult:
            return PolicyResult(
                rule_id=self.rule_id,
                severity=self.severity,
                passed=False,
                message="Blocking issue.",
            )

        def message(self) -> str:
            return "Blocking issue."

    class AdvisoryRule(PolicyRule):
        rule_id = "advisory_rule"

        def __init__(self) -> None:
            super().__init__(Severity.ADVISORY)

        def evaluate(self, _context: PolicyContext) -> PolicyResult:
            return PolicyResult(
                rule_id=self.rule_id,
                severity=self.severity,
                passed=False,
                message="Advisory issue.",
            )

        def message(self) -> str:
            return "Advisory issue."

    engine = PolicyEngine([BlockingRule(), AdvisoryRule()])
    monkeypatch.setattr(PolicyEngine, "from_file", lambda *_args, **_kwargs: engine)

    result = check_trip_plan(trip_plan)

    assert result.status == "fail"
    assert {issue.code for issue in result.issues} == {"blocking_rule", "advisory_rule"}
    severities = {issue.code: issue.severity for issue in result.issues}
    assert severities["blocking_rule"] == "error"
    assert severities["advisory_rule"] == "warning"


def test_check_trip_plan_passes_when_all_rules_pass(
    trip_plan: TripPlan, monkeypatch: pytest.MonkeyPatch
) -> None:
    class PassingRule(PolicyRule):
        rule_id = "passing_rule"

        def __init__(self) -> None:
            super().__init__(Severity.BLOCKING)

        def evaluate(self, _context: PolicyContext) -> PolicyResult:
            return PolicyResult(
                rule_id=self.rule_id,
                severity=self.severity,
                passed=True,
                message="All good.",
            )

        def message(self) -> str:
            return "All good."

    engine = PolicyEngine([PassingRule()])
    monkeypatch.setattr(PolicyEngine, "from_file", lambda *_args, **_kwargs: engine)

    result = check_trip_plan(trip_plan)

    assert result.status == "pass"
    assert result.issues == []


def test_check_trip_plan_skips_cost_comparison_when_estimates_missing(
    trip_plan: TripPlan,
) -> None:
    plan = trip_plan.model_copy(update={"expense_breakdown": {}})

    result = check_trip_plan(plan)

    issue_codes = {issue.code for issue in result.issues}
    assert "driving_vs_flying" not in issue_codes
    assert "fare_evidence" in issue_codes


def test_list_allowed_vendors_returns_registry_matches(
    trip_plan: TripPlan,
) -> None:
    vendors = list_allowed_vendors(trip_plan)

    assert isinstance(vendors, list)
    assert vendors == [
        "Blue Skies Airlines",
        "Citywide Rides",
        "Downtown Suites",
    ]


def test_list_allowed_vendors_filters_by_destination_and_date(
    trip_plan: TripPlan,
) -> None:
    plan = trip_plan.model_copy(
        update={"destination": "New York, NY", "departure_date": date(2024, 11, 2)}
    )

    vendors = list_allowed_vendors(plan)

    assert vendors == [
        "Blue Skies Airlines",
        "Downtown Suites",
    ]


def test_list_allowed_vendors_matches_other_destinations(
    trip_plan: TripPlan,
) -> None:
    plan = trip_plan.model_copy(update={"destination": "San Francisco, CA"})

    vendors = list_allowed_vendors(plan)

    assert vendors == [
        "Blue Skies Airlines",
        "Citywide Rides",
    ]


def test_list_allowed_vendors_handles_empty_destination(
    trip_plan: TripPlan,
) -> None:
    plan = trip_plan.model_copy(update={"destination": ""})

    vendors = list_allowed_vendors(plan)

    assert vendors == ["Citywide Rides"]


def test_list_allowed_vendors_handles_no_active_providers(
    trip_plan: TripPlan,
) -> None:
    plan = trip_plan.model_copy(
        update={"departure_date": date(2025, 1, 10), "return_date": date(2025, 1, 12)}
    )

    vendors = list_allowed_vendors(plan)

    assert vendors == []


def test_reconcile_summarizes_receipts(
    trip_plan: TripPlan, over_budget_receipts: list[Receipt]
) -> None:
    result = reconcile(trip_plan, over_budget_receipts)

    assert result.status == "over_budget"
    assert result.planned_total == Decimal("1000.00")
    assert result.actual_total == Decimal("1200.00")
    assert result.variance == Decimal("200.00")
    assert result.receipt_count == 2
    assert result.receipts_by_type == {".pdf": 1, ".png": 1}
    assert result.expenses_by_category == {ExpenseCategory.OTHER: Decimal("1200.00")}


def test_reconcile_matches_estimated_cost(
    trip_plan: TripPlan, matching_receipts: list[Receipt]
) -> None:
    result = reconcile(trip_plan, matching_receipts)

    assert isinstance(result, ReconciliationResult)
    assert result.status == "on_budget"
    assert result.variance == Decimal("0.00")


def test_reconcile_handles_empty_receipts(trip_plan: TripPlan) -> None:
    result = reconcile(trip_plan, [])

    assert result.status == "under_budget"
    assert result.planned_total == Decimal("1000.00")
    assert result.actual_total == Decimal("0.00")
    assert result.variance == Decimal("-1000.00")
    assert result.receipt_count == 0
    assert result.receipts_by_type == {}


def test_policy_api_documentation_examples_match_models() -> None:
    trip_plan_payload = {
        "trip_id": "TRIP-1001",
        "traveler_name": "Alex Rivera",
        "traveler_role": "Senior Analyst",
        "department": "Finance",
        "destination": "Chicago, IL 60601",
        "origin_city": "Austin, TX",
        "destination_city": "Chicago, IL",
        "departure_date": "2025-06-10",
        "return_date": "2025-06-12",
        "purpose": "Quarterly planning summit",
        "transportation_mode": "air",
        "expected_costs": {"airfare": 420.50, "lodging": 600.00},
        "funding_source": "FIN-OPS",
        "estimated_cost": 1200.50,
        "status": "submitted",
        "expense_breakdown": {"airfare": 420.50, "lodging": 600.00, "meals": 180.00},
        "selected_providers": {"airfare": "Skyway Air", "lodging": "Lakeside Hotel"},
        "validation_results": [],
        "approval_history": [],
        "exception_requests": [],
    }

    plan = TripPlan.model_validate(trip_plan_payload)
    assert plan.trip_id == "TRIP-1001"

    policy_result_payload = {
        "status": "fail",
        "issues": [
            {
                "code": "advance_booking",
                "message": "Flights must be booked 14 days in advance",
                "severity": "warning",
                "context": {"rule_id": "advance_booking", "severity": "advisory"},
            }
        ],
        "policy_version": "d7a6d25a",
    }

    policy_result = PolicyCheckResult.model_validate(policy_result_payload)
    assert policy_result.status == "fail"
    assert policy_result.issues[0].code == "advance_booking"

    reconciliation_payload = {
        "trip_id": "TRIP-1004",
        "report_id": "TRIP-1004-reconciliation",
        "planned_total": 900.00,
        "actual_total": 325.25,
        "variance": -574.75,
        "status": "under_budget",
        "receipt_count": 2,
        "receipts_by_type": {".pdf": 1, ".png": 1},
        "expenses_by_category": {"other": 325.25},
    }

    reconciliation_result = ReconciliationResult.model_validate(reconciliation_payload)
    assert reconciliation_result.receipt_count == 2
    assert reconciliation_result.status == "under_budget"
    assert ExpenseCategory.OTHER in reconciliation_result.expenses_by_category


def test_policy_api_markdown_lint() -> None:
    root = Path(__file__).resolve().parents[2]
    local_bin = root / "node_modules" / ".bin" / "markdownlint-cli2"
    lint_bin = local_bin if local_bin.exists() else shutil.which("markdownlint-cli2")
    if not lint_bin:
        pytest.skip("markdownlint-cli2 is not installed")

    subprocess.run(
        [str(lint_bin), "docs/policy-api.md"],
        check=True,
        cwd=root,
    )


def test_get_policy_snapshot_returns_current_contract(trip_plan: TripPlan) -> None:
    request = PlannerPolicySnapshotRequest(
        trip_id=trip_plan.trip_id,
        requested_at=datetime(2026, 4, 11, 12, 0, tzinfo=UTC),
    )

    snapshot = get_policy_snapshot(trip_plan, request)

    assert snapshot.trip_id == trip_plan.trip_id
    assert snapshot.freshness == "current"
    assert snapshot.versioning.contract_version == "2026-04-11"
    assert snapshot.auth.endpoint == "GET /api/planner/policy-snapshot"
    assert any(rule.code == "fare_evidence" for rule in snapshot.documentation_rules)
    assert any(
        trigger.code == "fare_evidence" for trigger in snapshot.approval_triggers
    )


def test_get_policy_snapshot_reports_stale_cache(trip_plan: TripPlan) -> None:
    request = PlannerPolicySnapshotRequest(
        trip_id=trip_plan.trip_id,
        requested_at=datetime(2026, 4, 12, 12, 0, tzinfo=UTC),
        snapshot_generated_at=datetime(2026, 4, 11, 11, 0, tzinfo=UTC),
    )

    snapshot = get_policy_snapshot(trip_plan, request)

    assert snapshot.freshness == "stale"
    assert snapshot.generated_at == request.requested_at
    assert snapshot.expires_at == request.requested_at + timedelta(hours=24)


def test_get_policy_snapshot_reports_explicit_invalidation(
    trip_plan: TripPlan,
) -> None:
    request = PlannerPolicySnapshotRequest(
        trip_id=trip_plan.trip_id,
        requested_at=datetime(2026, 4, 11, 12, 0, tzinfo=UTC),
        snapshot_generated_at=datetime(2026, 4, 11, 11, 0, tzinfo=UTC),
        known_policy_version="outdated-version",
        invalidate_reason="policy rules rotated after planner cache warmup",
    )

    snapshot = get_policy_snapshot(trip_plan, request)

    assert snapshot.freshness == "invalidated"
    assert snapshot.invalidation_reason == request.invalidate_reason
    assert snapshot.invalidated_at == request.requested_at
    assert snapshot.versioning.compatible_with_planner_cache is False


def test_get_policy_snapshot_rejects_mismatched_trip_id(
    trip_plan: TripPlan,
) -> None:
    request = PlannerPolicySnapshotRequest(
        trip_id="TRIP-OTHER-999",
        requested_at=datetime(2026, 4, 11, 12, 0, tzinfo=UTC),
    )

    with pytest.raises(
        ValueError,
        match="PlannerPolicySnapshotRequest.trip_id does not match plan.trip_id",
    ):
        get_policy_snapshot(trip_plan, request)


def test_get_policy_snapshot_etag_changes_when_plan_changes(
    trip_plan: TripPlan,
) -> None:
    request = PlannerPolicySnapshotRequest(
        trip_id=trip_plan.trip_id,
        requested_at=datetime(2026, 4, 11, 12, 0, tzinfo=UTC),
    )
    changed_plan = trip_plan.model_copy(update={"purpose": "Changed scope"})

    original = get_policy_snapshot(trip_plan, request)
    changed = get_policy_snapshot(changed_plan, request)

    assert original.versioning.etag != changed.versioning.etag


def test_submit_proposal_returns_pending_contract(trip_plan: TripPlan) -> None:
    request = PlannerProposalSubmissionRequest(
        trip_id=trip_plan.trip_id,
        proposal_id="proposal-123",
        proposal_version="proposal-v1",
        payload={"selected_options": ["flight-1", "hotel-3"]},
        submitted_at=datetime(2026, 4, 11, 12, 30, tzinfo=UTC),
    )

    response = submit_proposal(trip_plan, request)

    assert response.operation == "submit_proposal"
    assert response.submission_status == "pending"
    assert response.execution_status is not None
    assert response.execution_status.state == "deferred"
    assert response.execution_status.terminal is False
    assert response.retry is not None
    assert response.status_endpoint is not None
    assert response.result_payload["proposal_id"] == request.proposal_id
    assert response.result_payload["submitted_payload_keys"] == ["selected_options"]


def test_submit_proposal_returns_succeeded_contract_for_approved_trip(
    trip_plan: TripPlan,
) -> None:
    approved_plan = trip_plan.model_copy(update={"status": "approved"})
    request = PlannerProposalSubmissionRequest(
        trip_id=trip_plan.trip_id,
        proposal_id="proposal-123",
        proposal_version="proposal-v2",
        transport_pattern="sync",
        submitted_at=datetime(2026, 4, 11, 12, 35, tzinfo=UTC),
    )

    response = submit_proposal(approved_plan, request)

    assert response.submission_status == "succeeded"
    assert response.execution_status is not None
    assert response.execution_status.state == "succeeded"
    assert response.execution_status.terminal is True
    assert response.retry is None
    assert response.result_payload["queue_state"] == "completed"


def test_submit_proposal_returns_failed_contract_for_rejected_trip(
    trip_plan: TripPlan,
) -> None:
    rejected_plan = trip_plan.model_copy(update={"status": "rejected"})
    request = PlannerProposalSubmissionRequest(
        trip_id=trip_plan.trip_id,
        proposal_id="proposal-123",
        proposal_version="proposal-v3",
        submitted_at=datetime(2026, 4, 11, 12, 40, tzinfo=UTC),
    )

    response = submit_proposal(rejected_plan, request)

    assert response.submission_status == "failed"
    assert response.execution_status is not None
    assert response.execution_status.state == "failed"
    assert response.error is not None
    assert response.error.code == "proposal_rejected"
    assert response.retry is None


def test_submit_proposal_returns_unavailable_contract_when_service_down(
    trip_plan: TripPlan,
) -> None:
    request = PlannerProposalSubmissionRequest(
        trip_id=trip_plan.trip_id,
        proposal_id="proposal-123",
        proposal_version="proposal-v4",
        service_available=False,
        submitted_at=datetime(2026, 4, 11, 12, 45, tzinfo=UTC),
    )

    response = submit_proposal(trip_plan, request)

    assert response.submission_status == "unavailable"
    assert response.execution_status is None
    assert response.error is not None
    assert response.error.category == "availability"
    assert response.retry is not None
    assert response.retry.retryable is True


def test_poll_execution_status_returns_running_contract_for_async_trip(
    trip_plan: TripPlan,
) -> None:
    submit_request = PlannerProposalSubmissionRequest(
        trip_id=trip_plan.trip_id,
        proposal_id="proposal-123",
        proposal_version="proposal-v5",
        transport_pattern="async",
        submitted_at=datetime(2026, 4, 11, 12, 49, tzinfo=UTC),
    )
    submit_response = submit_proposal(trip_plan, submit_request)
    request = PlannerProposalStatusRequest(
        trip_id=trip_plan.trip_id,
        proposal_id="proposal-123",
        proposal_version="proposal-v5",
        execution_id=str(submit_response.result_payload["execution_id"]),
        transport_pattern="async",
        requested_at=datetime(2026, 4, 11, 12, 50, tzinfo=UTC),
    )

    response = poll_execution_status(trip_plan, request)

    assert response.operation == "poll_execution_status"
    assert response.submission_status == "pending"
    assert response.execution_status is not None
    assert response.execution_status.state == "running"
    assert response.retry is not None
    assert response.result_payload["result_endpoint"].endswith(
        f"/{submit_response.result_payload['execution_id']}/evaluation-result"
    )


def test_poll_execution_status_preserves_supplied_correlation_id(
    trip_plan: TripPlan,
) -> None:
    submit_request = PlannerProposalSubmissionRequest(
        trip_id=trip_plan.trip_id,
        proposal_id="proposal-abc",
        proposal_version="proposal-v6",
    )
    submit_response = submit_proposal(trip_plan, submit_request)
    request = PlannerProposalStatusRequest(
        trip_id=trip_plan.trip_id,
        proposal_id="proposal-abc",
        proposal_version="proposal-v6",
        execution_id=str(submit_response.result_payload["execution_id"]),
        correlation_id=PlannerCorrelationId(value="corr-custom-123"),
        requested_at=datetime(2026, 4, 11, 12, 55, tzinfo=UTC),
    )

    response = poll_execution_status(trip_plan, request)

    assert response.correlation_id.value == "corr-custom-123"


def test_poll_execution_status_rejects_mismatched_execution_id(
    trip_plan: TripPlan,
) -> None:
    request = PlannerProposalStatusRequest(
        trip_id=trip_plan.trip_id,
        proposal_id="proposal-bad",
        proposal_version="proposal-v7",
        execution_id="exec-wrong",
        requested_at=datetime(2026, 4, 11, 13, 0, tzinfo=UTC),
    )

    with pytest.raises(
        ValueError,
        match="PlannerProposalStatusRequest.execution_id does not match",
    ):
        poll_execution_status(trip_plan, request)


def test_get_evaluation_result_returns_non_compliant_contract(
    trip_plan: TripPlan,
) -> None:
    plan = trip_plan.model_copy(
        update={
            "selected_fare": Decimal("650.00"),
            "lowest_fare": Decimal("300.00"),
            "fare_evidence_attached": False,
            "comparable_hotels": [Decimal("140.00"), Decimal("165.00")],
            "selected_providers": {"airfare": "Blue Skies Airlines"},
        }
    )
    submit_response = submit_proposal(
        plan,
        PlannerProposalSubmissionRequest(
            trip_id=plan.trip_id,
            proposal_id="proposal-123",
            proposal_version="proposal-v8",
        ),
    )
    request = PlannerProposalEvaluationRequest(
        trip_id=plan.trip_id,
        proposal_id="proposal-123",
        proposal_version="proposal-v8",
        execution_id=str(submit_response.result_payload["execution_id"]),
        requested_at=datetime(2026, 4, 11, 13, 5, tzinfo=UTC),
    )

    result = get_evaluation_result(plan, request)

    assert isinstance(result, PlannerProposalEvaluationResult)
    assert result.outcome == "non_compliant"
    assert {issue.code for issue in result.blocking_issues} >= {
        "fare_comparison",
        "fare_evidence",
    }
    assert any(
        alternative.category == "airfare"
        and alternative.suggested_value == "300.00"
        for alternative in result.preferred_alternatives
    )
    assert any(
        guidance.code == "lower_trip_cost"
        for guidance in result.reoptimization_guidance
    )


def test_get_evaluation_result_returns_compliant_contract(
    trip_plan: TripPlan, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        policy_api_module,
        "check_trip_plan",
        lambda _plan: PolicyCheckResult(status="pass", issues=[], policy_version="v1"),
    )
    submit_response = submit_proposal(
        trip_plan,
        PlannerProposalSubmissionRequest(
            trip_id=trip_plan.trip_id,
            proposal_id="proposal-123",
            proposal_version="proposal-v9",
        ),
    )
    request = PlannerProposalEvaluationRequest(
        trip_id=trip_plan.trip_id,
        proposal_id="proposal-123",
        proposal_version="proposal-v9",
        execution_id=str(submit_response.result_payload["execution_id"]),
        requested_at=datetime(2026, 4, 11, 13, 10, tzinfo=UTC),
    )

    result = get_evaluation_result(trip_plan, request)

    assert result.outcome == "compliant"
    assert result.blocking_issues == []
    assert result.exception_requirements == []
    assert result.reoptimization_guidance == []


def test_get_evaluation_result_returns_exception_required_contract(
    trip_plan: TripPlan, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        policy_api_module,
        "check_trip_plan",
        lambda _plan: PolicyCheckResult(status="pass", issues=[], policy_version="v1"),
    )
    plan = trip_plan.model_copy(
        update={
            "exception_requests": [
                ExceptionRequest(
                    type=ExceptionType.DRIVING_VS_FLYING,
                    justification=(
                        "Driving keeps the traveler aligned with on-site equipment "
                        "handoff timing and avoids an otherwise disconnected arrival."
                    ),
                    requestor="alex.rivera",
                    amount=Decimal("180.00"),
                )
            ]
        }
    )
    submit_response = submit_proposal(
        plan,
        PlannerProposalSubmissionRequest(
            trip_id=plan.trip_id,
            proposal_id="proposal-123",
            proposal_version="proposal-v10",
        ),
    )
    request = PlannerProposalEvaluationRequest(
        trip_id=plan.trip_id,
        proposal_id="proposal-123",
        proposal_version="proposal-v10",
        execution_id=str(submit_response.result_payload["execution_id"]),
        requested_at=datetime(2026, 4, 11, 13, 15, tzinfo=UTC),
    )

    result = get_evaluation_result(plan, request)

    assert result.outcome == "exception_required"
    assert len(result.exception_requirements) == 1
    assert result.exception_requirements[0].type == "driving_vs_flying"
    assert any(
        guidance.code == "route_exception_workflow"
        for guidance in result.reoptimization_guidance
    )


def test_get_evaluation_result_rejects_mismatched_execution_id(
    trip_plan: TripPlan,
) -> None:
    request = PlannerProposalEvaluationRequest(
        trip_id=trip_plan.trip_id,
        proposal_id="proposal-bad",
        proposal_version="proposal-v11",
        execution_id="exec-wrong",
        requested_at=datetime(2026, 4, 11, 13, 20, tzinfo=UTC),
    )

    with pytest.raises(
        ValueError,
        match="PlannerProposalEvaluationRequest.execution_id does not match",
    ):
        get_evaluation_result(trip_plan, request)
