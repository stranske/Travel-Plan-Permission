"""Synthetic demo seeding for the planner HTTP service.

This module powers the opt-in ``TPP_DEMO_MODE`` boot path (see
:func:`travel_plan_permission.http_service.create_app`). When enabled, it
seeds the in-memory proposal store from repo fixtures plus a small set of
synthetic policy-evidence defaults so a non-developer can exercise the full
traveler -> manager -> admin loop in a browser without a terminal.

Hard guarantees:

* **Synthetic only.** Seeded values originate from ``tests/fixtures/*.json`` in
  this repository plus synthetic defaults for the policy-evidence fields the
  portal review requires. No real travel/expense data is ever embedded, so the
  public demo never leaks proprietary data.
* **Opt-in.** Seeding only runs when ``TPP_DEMO_MODE`` is truthy, and never when
  the portal is pointed at a real Postgres backend (``TPP_PORTAL_DATABASE_URL``).

The companion runbook is ``docs/no-terminal-demo.md``.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import cast

from .planner_auth import PlannerAuthConfig, PlannerAuthMode, mint_bootstrap_token
from .security import Permission

logger = logging.getLogger(__name__)

#: Environment flag that turns the synthetic demo seed on. Default OFF.
DEMO_MODE_ENV_VAR = "TPP_DEMO_MODE"

#: Optional override pointing at a directory containing the demo fixtures.
DEMO_FIXTURE_DIR_ENV_VAR = "TPP_DEMO_FIXTURE_DIR"

#: Env var that, when it names a real Postgres DSN, disables demo seeding so the
#: synthetic seed can never be written into a proprietary-data store.
PORTAL_DATABASE_URL_ENV_VAR = "TPP_PORTAL_DATABASE_URL"

#: Repo fixtures the synthetic demo is seeded from.
CANONICAL_TRIP_FIXTURE = "canonical_trip_plan_realistic.json"
EXPENSE_FIXTURE = "sample_expense_report_minimal.json"

#: Subject embedded in the minted demo reviewer bearer token.
DEMO_REVIEWER_SUBJECT = "tpp-demo-reviewer"

#: Permissions granted to the demo reviewer token so the auth-gated manager
#: review queue/detail and decision routes are reachable in the demo.
DEMO_REVIEWER_PERMISSIONS: tuple[Permission, ...] = (
    Permission.VIEW,
    Permission.CREATE,
    Permission.APPROVE,
)

#: Bearer token lifetime for the demo reviewer (1 hour). Short-lived on purpose.
DEMO_TOKEN_TTL_SECONDS = 3600

# Policy-evidence answer fields the portal review requires that are not part of
# the trip-plan fixture itself (fare comparison, mileage, per-diem evidence).
# These are synthetic demo defaults, consistent with the fixture trip.
_DEMO_POLICY_EVIDENCE_ANSWERS: dict[str, str] = {
    "booking_date": "2025-09-20",
    "selected_fare": "455.25",
    "lowest_fare": "430.00",
    "cabin_class": "economy",
    "flight_duration_hours": "2.5",
    "fare_evidence_attached": "true",
    "driving_cost": "120.00",
    "flight_cost": "200.00",
    "distance_from_office_miles": "12.5",
    "overnight_stay": "true",
    "meals_provided": "false",
    "meal_per_diem_requested": "true",
}


class DemoSeedError(RuntimeError):
    """Raised when the synthetic demo cannot be seeded."""


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _points_at_real_postgres() -> bool:
    dsn = (os.getenv(PORTAL_DATABASE_URL_ENV_VAR) or "").strip().lower()
    return dsn.startswith("postgres://") or dsn.startswith("postgresql://")


def demo_mode_enabled() -> bool:
    """Return whether the synthetic demo seed should run.

    Demo mode is opt-in via ``TPP_DEMO_MODE`` and is force-disabled whenever the
    portal is backed by a real Postgres store, so synthetic data can never be
    written into a proprietary-data deployment.
    """

    if not _is_truthy(os.getenv(DEMO_MODE_ENV_VAR)):
        return False
    if _points_at_real_postgres():
        logger.warning(
            "%s is set but %s names a Postgres backend; refusing to seed synthetic "
            "demo data into a proprietary-data store.",
            DEMO_MODE_ENV_VAR,
            PORTAL_DATABASE_URL_ENV_VAR,
        )
        return False
    return True


def _repo_fixture_dir() -> Path | None:
    """Locate the repo ``tests/fixtures`` directory relative to this module."""

    for parent in Path(__file__).resolve().parents:
        candidate = parent / "tests" / "fixtures"
        if candidate.is_dir():
            return candidate
    return None


def demo_fixture_dir() -> Path:
    """Resolve the directory holding the demo fixtures.

    Resolution order: the ``TPP_DEMO_FIXTURE_DIR`` override, then the repo
    ``tests/fixtures`` checkout directory.
    """

    override = os.getenv(DEMO_FIXTURE_DIR_ENV_VAR)
    if override:
        path = Path(override).expanduser()
        if not path.is_dir():
            raise DemoSeedError(f"{DEMO_FIXTURE_DIR_ENV_VAR}={override!r} is not a directory.")
        return path
    repo_fixtures = _repo_fixture_dir()
    if repo_fixtures is None:
        raise DemoSeedError(
            "Could not locate demo fixtures. Set "
            f"{DEMO_FIXTURE_DIR_ENV_VAR} to a directory containing "
            f"{CANONICAL_TRIP_FIXTURE} and {EXPENSE_FIXTURE}."
        )
    return repo_fixtures


def _load_fixture(name: str) -> dict[str, object]:
    path = demo_fixture_dir() / name
    if not path.is_file():
        raise DemoSeedError(f"Demo fixture not found: {path}")
    return cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))


def _flatten(obj: object, prefix: str = "") -> dict[str, str]:
    """Flatten a nested fixture into dotted/indexed portal-answer form.

    ``{"hotel": {"name": "x"}}`` -> ``{"hotel.name": "x"}`` and
    ``{"comparable_hotels": [{"name": "y"}]}`` ->
    ``{"comparable_hotels[0].name": "y"}``, matching the portal form encoding.
    Scalars are stringified like an HTML form post (bools lower-cased).
    """

    flattened: dict[str, str] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            flattened.update(_flatten(value, child))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            flattened.update(_flatten(value, f"{prefix}[{index}]"))
    elif isinstance(obj, bool):
        flattened[prefix] = "true" if obj else "false"
    elif obj is not None:
        flattened[prefix] = str(obj)
    return flattened


def _demo_trip_answers() -> dict[str, object]:
    """Build complete portal answers from the canonical trip fixture."""

    canonical = _load_fixture(CANONICAL_TRIP_FIXTURE)
    answers = {key: value for key, value in _flatten(canonical).items() if key != "type"}
    # Overlay synthetic policy-evidence fields the review requires beyond the
    # base trip plan. Fixture-derived values win on key collisions.
    merged: dict[str, object] = dict(_DEMO_POLICY_EVIDENCE_ANSWERS)
    merged.update(answers)
    return merged


def mint_demo_reviewer_token(config: PlannerAuthConfig | None = None) -> str | None:
    """Mint a short-lived demo reviewer bearer token.

    Returns ``None`` when the service is not configured for bootstrap-token auth
    (the only mode that can validate a minted token), so callers can surface a
    helpful message instead of a broken token.
    """

    config = config or PlannerAuthConfig.from_env()
    if config.auth_mode != PlannerAuthMode.BOOTSTRAP_TOKEN:
        return None
    secret = os.getenv("TPP_BOOTSTRAP_SIGNING_SECRET")
    if not secret:
        return None
    provider = config.oidc_provider or "google"
    return mint_bootstrap_token(
        subject=DEMO_REVIEWER_SUBJECT,
        permissions=DEMO_REVIEWER_PERMISSIONS,
        provider=provider,
        secret=secret,
        expires_in_seconds=DEMO_TOKEN_TTL_SECONDS,
    )


def seed_demo_data(store: object) -> int:
    """Seed ``store`` with synthetic demo data.

    Returns the number of manager reviews seeded. Importing
    :mod:`travel_plan_permission.http_service` lazily avoids a circular import
    at module load time.
    """

    from . import http_service as h
    from .portal_review import portal_review_state

    answers = _demo_trip_answers()
    draft = store.save_portal_draft(answers)  # type: ignore[attr-defined]
    review = portal_review_state(
        draft.draft_id,
        answers,
        required_fields=h._PORTAL_REQUIRED_FIELDS,
        canonical_payload_builder=h._canonical_payload_from_answers,
    )
    if review.trip_plan is None or review.missing_fields or review.validation_errors:
        raise DemoSeedError(
            "Demo trip fixture did not validate into a complete review state "
            f"(missing={review.missing_fields}, errors={review.validation_errors})."
        )
    store.create_manager_review(review)  # type: ignore[attr-defined]

    # Best-effort: also seed an expense draft so the expense surface is
    # populated. Never let an expense-fixture mismatch break the demo seed,
    # since the reviewable manager queue is the load-bearing demo surface.
    try:
        expense_answers = {
            key: value
            for key, value in _flatten(_load_fixture(EXPENSE_FIXTURE)).items()
            if key != "type"
        }
        store.save_expense_draft(expense_answers)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - demo seeding must stay non-fatal here
        logger.warning("Demo expense fixture could not be seeded; continuing.", exc_info=True)

    return len(store.list_manager_reviews())  # type: ignore[attr-defined]
