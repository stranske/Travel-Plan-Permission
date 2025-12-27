Implemented package-resource template path extraction with a cached temp file fallback so `policy_api._default_template_path` works even when templates only exist as package resources, and updated the helper test plus PR checklist accordingly in `src/travel_plan_permission/policy_api.py`, `tests/python/test_policy_api_helpers.py`, and `codex-prompt.md`.

Tests:
- `pytest tests/python/test_policy_api_helpers.py::test_default_template_path_reports_package_resource_only`

Next steps:
1. Run the full suite with `pytest` if you want broader validation.