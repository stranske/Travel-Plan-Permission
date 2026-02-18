import sys

sys.path.append("src")

from travel_plan_permission.policy import PolicyContext, PolicyEngine, PolicyResult
from travel_plan_permission.policy_versioning import (
    PolicyChangeSimulationResult,
    PolicyMigrationPlan,
    PolicyMigrationPlanner,
    PolicyVersion,
    simulate_policy_change,
)


def test_policy_version_hash_and_label() -> None:
    version = PolicyVersion.from_config("1.2.3", {"rules": {"foo": 1}})

    assert version.label == "1.2.3"
    # Hash should be stable for the same config
    assert (
        version.config_hash
        == PolicyVersion.from_config("1.2.3", {"rules": {"foo": 1}}).config_hash
    )


def test_backward_compatibility_and_change_type() -> None:
    base = PolicyVersion.from_config("1.0.0", {"rules": {"foo": 1}})
    minor = PolicyVersion.from_config("1.1.0", {"rules": {"foo": 2}})
    major = PolicyVersion.from_config("2.0.0", {"rules": {"foo": 2}})
    patch = PolicyVersion.from_config("1.0.1", {"rules": {"foo": 1, "bar": 3}})

    assert minor.is_backward_compatible_with(base) is True
    assert major.is_backward_compatible_with(base) is False
    assert minor.change_type(base) == "feature"
    assert major.change_type(base) == "breaking"
    assert patch.change_type(base) in {"patch", "config-drift"}


def test_migration_plan_steps_and_flags() -> None:
    planner = PolicyMigrationPlanner()
    source = PolicyVersion.from_config("1.0.0", {"rules": {"foo": 1}})
    target = PolicyVersion.from_config("2.0.0", {"rules": {"foo": 2}})

    plan = planner.build_plan(source, target)

    assert isinstance(plan, PolicyMigrationPlan)
    assert plan.breaking_change is True
    assert plan.requires_downtime is False
    assert any("shadow mode" in step for step in plan.steps)


class _StaticEngine(PolicyEngine):
    def __init__(self, results: list[PolicyResult]) -> None:
        self._results = results

    def validate(self, context: PolicyContext) -> list[PolicyResult]:  # noqa: ARG002
        return self._results


def test_simulation_replays_contexts() -> None:
    contexts = [PolicyContext(), PolicyContext()]
    current_results: list[PolicyResult] = [
        PolicyResult(rule_id="test", severity="advisory", passed=True, message="old")
    ]
    proposed_results: list[PolicyResult] = [
        PolicyResult(rule_id="test", severity="advisory", passed=True, message="new")
    ]

    simulations = simulate_policy_change(
        current_engine=_StaticEngine(current_results),
        proposed_engine=_StaticEngine(proposed_results),
        historical_contexts=contexts,
    )

    assert len(simulations) == len(contexts)
    assert all(isinstance(item, PolicyChangeSimulationResult) for item in simulations)
    assert all(sim.current_results == current_results for sim in simulations)
    assert all(sim.proposed_results == proposed_results for sim in simulations)
