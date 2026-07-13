from fastapi.testclient import TestClient

from travel_plan_permission.http_service import create_app
from travel_plan_permission.intake_requirements import get_intake_requirement_catalog


def _set_runtime_env(monkeypatch) -> None:
    monkeypatch.setenv("TPP_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("TPP_OIDC_PROVIDER", "google")
    monkeypatch.setenv("TPP_AUTH_MODE", "static-token")
    monkeypatch.setenv("TPP_ACCESS_TOKEN", "dev-token")
    monkeypatch.setenv("TPP_HANDOFF_SIGNING_SECRET", "test-handoff-signing-secret")


def test_catalog_marks_parking_and_local_mobility_as_researchable() -> None:
    catalog = get_intake_requirement_catalog()
    requirements = {item.code: item for item in catalog.requirements}

    assert requirements["airport_parking"].collection_mode == "researchable"
    assert requirements["airport_parking"].required_inputs == [
        "departure_airport",
        "parking_days",
    ]
    assert requirements["airport_access"].required_inputs == [
        "traveler_residence_address",
        "official_domicile_address",
        "departure_airport",
    ]
    assert "commuting" in (requirements["airport_access"].research_prompt or "")
    assert "off-airport" in (requirements["airport_parking"].research_prompt or "")
    assert requirements["local_mobility"].research_prompt
    assert requirements["meals_incidentals"].collection_mode == "automatic"


def test_planner_intake_requirement_endpoint_requires_view_permission(monkeypatch) -> None:
    _set_runtime_env(monkeypatch)
    client = TestClient(create_app())

    unauthorized = client.get("/api/planner/intake-requirements")
    authorized = client.get(
        "/api/planner/intake-requirements",
        headers={"Authorization": "Bearer dev-token"},
    )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    payload = authorized.json()
    assert payload["contract_version"] == "tpp-intake-requirements/v1"
    assert any(item["code"] == "airport_parking" for item in payload["requirements"])
