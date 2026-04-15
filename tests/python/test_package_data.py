from importlib import resources


def test_mapping_resource_exists() -> None:
    mapping = resources.files("travel_plan_permission").joinpath(
        "config", "excel_mappings.yaml"
    )
    assert mapping.is_file()
    assert "templates" in mapping.read_text(encoding="utf-8")


def test_template_resource_exists() -> None:
    template = resources.files("travel_plan_permission").joinpath(
        "templates", "travel_request_template.xlsx"
    )
    assert template.is_file()
    assert template.read_bytes().startswith(b"PK")


def test_portal_template_resources_exist() -> None:
    templates = resources.files("travel_plan_permission").joinpath("templates")
    home = templates.joinpath("portal_home.html")
    request = templates.joinpath("portal_request.html")
    queue = templates.joinpath("manager_review_queue.html")
    detail = templates.joinpath("manager_review_detail.html")

    assert home.is_file()
    assert "Travel Request Portal" in home.read_text(encoding="utf-8")
    assert request.is_file()
    assert (
        "Draft a travel request through the real service runtime."
        in request.read_text(encoding="utf-8")
    )
    assert queue.is_file()
    assert "Manager review queue" in queue.read_text(encoding="utf-8")
    assert detail.is_file()
    assert "Manager review detail" in detail.read_text(encoding="utf-8")
