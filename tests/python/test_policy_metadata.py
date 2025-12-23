from travel_plan_permission import PolicyEngine


def test_describe_rules_reflects_configuration() -> None:
    yaml_content = """
rules:
  advance_booking:
    days_required: 21
    severity: blocking
  fare_comparison:
    max_over_lowest: 150
  cabin_class:
    long_haul_hours: 6
    allowed_classes:
      - economy
      - premium economy
    severity: advisory
  non_reimbursable:
    blocked_keywords:
      - gift
"""
    engine = PolicyEngine.from_yaml(yaml_content)
    metadata = {item["rule_id"]: item for item in engine.describe_rules()}

    assert metadata["advance_booking"]["severity"] == "blocking"
    assert "21 days" in metadata["advance_booking"]["description"]
    assert "150" in metadata["fare_comparison"]["description"]
    assert metadata["cabin_class"]["severity"] == "advisory"
    assert "premium economy" in metadata["cabin_class"]["description"].lower()
    assert "gift" in metadata["non_reimbursable"]["description"]
