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
