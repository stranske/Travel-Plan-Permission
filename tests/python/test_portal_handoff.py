from travel_plan_permission.portal_handoff import (
    issue_handoff_token,
    verify_handoff_token,
)


def test_handoff_token_is_subject_scoped_and_expires() -> None:
    token = issue_handoff_token("draft-123", secret="test-secret-value", now=100)

    assert verify_handoff_token(token, secret="test-secret-value", now=999) == "draft-123"
    assert verify_handoff_token(token, secret="test-secret-value", now=1001) is None


def test_handoff_token_rejects_tampering_and_wrong_secret() -> None:
    token = issue_handoff_token("draft-123", secret="test-secret-value", now=100)

    assert verify_handoff_token(token + "x", secret="test-secret-value", now=101) is None
    assert verify_handoff_token(token, secret="different-secret", now=101) is None
