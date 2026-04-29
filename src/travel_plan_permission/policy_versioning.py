"""Utilities for versioning and migrating policy-lite configurations.

The helpers in this module focus on policy-as-code lifecycle concerns:

* Semantic version tracking with deterministic configuration hashes
* Backward-compatibility checks between policy versions
* Migration planning that favors zero-downtime rollouts using dual-run
* Simulation helpers to replay historical policy contexts against a
  prospective configuration
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - import cycles avoided at runtime
    from .policy import PolicyContext, PolicyEngine, PolicyResult


def _stable_hash(config: dict[str, Any]) -> str:
    """Return a deterministic hash for a policy configuration."""

    normalized = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return sha256(normalized).hexdigest()


def _parse_version(version: str | None) -> tuple[int, int, int]:
    if not version:
        return (0, 1, 0)

    parts = str(version).split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
    except ValueError:
        return (0, 1, 0)

    return (major, minor, patch)


@dataclass(frozen=True)
class PolicyVersion:
    """Semantic policy version paired with a configuration hash."""

    major: int
    minor: int
    patch: int
    config_hash: str

    @classmethod
    def from_config(cls, version: str | None, rule_config: dict[str, Any]) -> PolicyVersion:
        major, minor, patch = _parse_version(version)
        return cls(
            major=major,
            minor=minor,
            patch=patch,
            config_hash=_stable_hash(rule_config),
        )

    @property
    def label(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def is_backward_compatible_with(self, previous: PolicyVersion) -> bool:
        if self.major != previous.major:
            return False
        return self.minor >= previous.minor

    def change_type(self, previous: PolicyVersion) -> str:
        if self.config_hash == previous.config_hash:
            return "no-op"
        if self.major != previous.major:
            return "breaking"
        if self.minor != previous.minor:
            return "feature"
        if self.patch != previous.patch:
            return "patch"
        return "config-drift"


@dataclass(frozen=True)
class PolicyMigrationPlan:
    source: PolicyVersion
    target: PolicyVersion
    breaking_change: bool
    requires_downtime: bool
    steps: list[str]


class PolicyMigrationPlanner:
    """Construct migration plans that avoid service interruption."""

    def build_plan(self, source: PolicyVersion, target: PolicyVersion) -> PolicyMigrationPlan:
        breaking_change = target.major != source.major
        steps = [
            "Pin current policy version for in-flight approvals",
            "Deploy proposed policy in shadow mode for regression comparisons",
            "Replay recent historical decisions to surface deltas",
            "Promote proposed policy when deltas are understood and approved",
            "Archive previous policy version for rollback within retention window",
        ]

        requires_downtime = False
        if breaking_change:
            steps.append(
                "Schedule staged rollout with opt-in cohorts to guard against breaking behavior"
            )

        return PolicyMigrationPlan(
            source=source,
            target=target,
            breaking_change=breaking_change,
            requires_downtime=requires_downtime,
            steps=steps,
        )


@dataclass
class PolicyChangeSimulationResult:
    context: PolicyContext
    current_results: list[PolicyResult]
    proposed_results: list[PolicyResult]


def simulate_policy_change(
    current_engine: PolicyEngine,
    proposed_engine: PolicyEngine,
    historical_contexts: Iterable[PolicyContext],
) -> list[PolicyChangeSimulationResult]:
    """Replay historical contexts to evaluate impact of a policy change."""

    simulations: list[PolicyChangeSimulationResult] = []
    for context in historical_contexts:
        simulations.append(
            PolicyChangeSimulationResult(
                context=context,
                current_results=current_engine.validate(context),
                proposed_results=proposed_engine.validate(context),
            )
        )
    return simulations
