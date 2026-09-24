from __future__ import annotations

from pathlib import Path
from threading import Event, Lock, Thread

import pytest

from travel_plan_permission import audit
from travel_plan_permission.security import (
    API_ENDPOINT_PERMISSIONS,
    DEFAULT_ROLES,
    DEFAULT_SSO_PLANS,
    PLANNER_POLICY_SNAPSHOT_ENDPOINT,
    AuditEventType,
    AuditLog,
    Permission,
    RoleChangeRequest,
    RoleChangeState,
    RoleName,
    SecurityModel,
)


def test_roles_and_permissions_matrix() -> None:
    security = SecurityModel()  # noqa: F841

    assert DEFAULT_ROLES[RoleName.TRAVELER].permissions == {
        Permission.VIEW,
        Permission.CREATE,
    }
    assert DEFAULT_ROLES[RoleName.APPROVER].permissions == {
        Permission.VIEW,
        Permission.APPROVE,
    }
    assert Permission.EXPORT in DEFAULT_ROLES[RoleName.FINANCE_ADMIN].permissions
    assert Permission.CONFIGURE in DEFAULT_ROLES[RoleName.POLICY_ADMIN].permissions
    assert set(Permission) == DEFAULT_ROLES[RoleName.SYSTEM_ADMIN].permissions
    assert PLANNER_POLICY_SNAPSHOT_ENDPOINT in API_ENDPOINT_PERMISSIONS
    assert "POST /api/approvals/:id/decision" in API_ENDPOINT_PERMISSIONS


def test_endpoint_authorization_and_delegation() -> None:
    security = SecurityModel()
    security.register_delegation(primary_user="primary.approver", backup_user="backup")

    # Backup acts on behalf of primary approver for approval endpoint.
    assert security.authorize(
        user="backup",
        role=RoleName.APPROVER,
        endpoint="POST /api/approvals/:id/decision",
        acting_on_behalf_of="primary.approver",
    )

    # Non-delegated backup cannot access configuration without proper role.
    assert not security.authorize(
        user="backup",
        role=RoleName.APPROVER,
        endpoint="POST /api/policy/rules",
        acting_on_behalf_of="primary.approver",
    )


def test_role_change_requires_admin_approval_and_is_logged() -> None:
    audit_log = AuditLog()
    security = SecurityModel(
        audit_log=audit_log,
        user_roles={
            "not-admin": RoleName.APPROVER,
            "susan": RoleName.SYSTEM_ADMIN,
        },
    )
    request = security.request_role_change(
        requester="alice", target_user="bob", new_role=RoleName.FINANCE_ADMIN
    )
    assert request.state == RoleChangeState.PENDING_APPROVAL

    with pytest.raises(PermissionError):
        security.approve_role_change(
            admin_actor="not-admin",
            admin_role=RoleName.APPROVER,
            request_id=request.request_id,
        )

    approved_request = security.approve_role_change(
        admin_actor="susan",
        admin_role=RoleName.SYSTEM_ADMIN,
        request_id=request.request_id,
    )
    assert approved_request.state == RoleChangeState.APPROVED
    assert security.user_roles["bob"] == RoleName.FINANCE_ADMIN

    role_change_events = audit_log.filter_by_type(AuditEventType.ROLE_CHANGE)
    assert {event.outcome for event in role_change_events} == {
        RoleChangeState.PENDING_APPROVAL.value,
        RoleChangeState.APPROVED.value,
    }


def test_role_change_approval_derives_admin_role_from_actor() -> None:
    security = SecurityModel(user_roles={"eve": RoleName.APPROVER})
    request = security.request_role_change(
        requester="alice", target_user="bob", new_role=RoleName.FINANCE_ADMIN
    )

    with pytest.raises(PermissionError, match="matching assigned admin role"):
        security.approve_role_change(
            admin_actor="eve",
            admin_role=RoleName.SYSTEM_ADMIN,
            request_id=request.request_id,
        )

    assert request.state == RoleChangeState.PENDING_APPROVAL


def test_role_change_rejection_requires_matching_actor_assignment() -> None:
    security = SecurityModel(
        user_roles={
            "eve": RoleName.APPROVER,
            "pat": RoleName.POLICY_ADMIN,
        }
    )
    request = security.request_role_change(
        requester="alice", target_user="bob", new_role=RoleName.FINANCE_ADMIN
    )

    with pytest.raises(PermissionError, match="matching assigned admin role"):
        security.reject_role_change(
            admin_actor="eve",
            admin_role=RoleName.POLICY_ADMIN,
            request_id=request.request_id,
        )

    assert request.state == RoleChangeState.PENDING_APPROVAL
    rejected_request = security.reject_role_change(
        admin_actor="pat",
        admin_role=RoleName.POLICY_ADMIN,
        request_id=request.request_id,
    )
    assert rejected_request.state == RoleChangeState.REJECTED


@pytest.mark.parametrize("decision", ["approve_role_change", "reject_role_change"])
def test_role_change_decision_requires_actor_assignment(decision: str) -> None:
    security = SecurityModel()
    request = security.request_role_change(
        requester="alice", target_user="bob", new_role=RoleName.FINANCE_ADMIN
    )

    decide = getattr(security, decision)
    with pytest.raises(PermissionError, match="matching assigned admin role"):
        decide(
            admin_actor="mallory",
            admin_role=RoleName.SYSTEM_ADMIN,
            request_id=request.request_id,
        )

    assert request.state == RoleChangeState.PENDING_APPROVAL


def test_role_change_approval_is_terminal() -> None:
    security = SecurityModel(user_roles={"susan": RoleName.SYSTEM_ADMIN})
    request = security.request_role_change(
        requester="alice", target_user="bob", new_role=RoleName.FINANCE_ADMIN
    )

    security.approve_role_change(
        admin_actor="susan",
        admin_role=RoleName.SYSTEM_ADMIN,
        request_id=request.request_id,
    )

    with pytest.raises(
        ValueError,
        match=rf"{request.request_id}.*{RoleChangeState.APPROVED.value}",
    ):
        security.reject_role_change(
            admin_actor="susan",
            admin_role=RoleName.SYSTEM_ADMIN,
            request_id=request.request_id,
        )

    assert request.state == RoleChangeState.APPROVED
    assert request.request_id not in security.pending_role_changes
    assert security.decided_role_changes[request.request_id] is request


def test_role_change_rejection_is_terminal() -> None:
    security = SecurityModel(user_roles={"pat": RoleName.POLICY_ADMIN})
    request = security.request_role_change(
        requester="alice", target_user="bob", new_role=RoleName.FINANCE_ADMIN
    )

    security.reject_role_change(
        admin_actor="pat",
        admin_role=RoleName.POLICY_ADMIN,
        request_id=request.request_id,
    )

    with pytest.raises(
        ValueError,
        match=rf"{request.request_id}.*{RoleChangeState.REJECTED.value}",
    ):
        security.approve_role_change(
            admin_actor="pat",
            admin_role=RoleName.POLICY_ADMIN,
            request_id=request.request_id,
        )

    assert request.state == RoleChangeState.REJECTED
    assert request.request_id not in security.pending_role_changes
    assert security.decided_role_changes[request.request_id] is request


def test_concurrent_role_change_decisions_are_serialized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    security = SecurityModel(user_roles={"susan": RoleName.SYSTEM_ADMIN})
    request = security.request_role_change(
        requester="alice", target_user="bob", new_role=RoleName.FINANCE_ADMIN
    )
    first_helper_entered = Event()
    second_helper_entered = Event()
    release_first = Event()
    counter_lock = Lock()
    helper_calls = 0
    original_require_pending = security._require_pending_role_change

    def controlled_require_pending(
        *,
        admin_actor: str,
        actor_role: RoleName,
        request_id: str,
        transition: str,
    ) -> RoleChangeRequest:
        nonlocal helper_calls
        with counter_lock:
            helper_calls += 1
            call_number = helper_calls
        if call_number == 1:
            first_helper_entered.set()
            assert release_first.wait(timeout=2)
        else:
            second_helper_entered.set()
        return original_require_pending(
            admin_actor=admin_actor,
            actor_role=actor_role,
            request_id=request_id,
            transition=transition,
        )

    monkeypatch.setattr(
        security, "_require_pending_role_change", controlled_require_pending
    )
    results: list[RoleChangeRequest] = []
    errors: list[BaseException] = []

    def decide(transition: str) -> None:
        try:
            method = getattr(security, transition)
            results.append(
                method(
                    admin_actor="susan",
                    admin_role=RoleName.SYSTEM_ADMIN,
                    request_id=request.request_id,
                )
            )
        except BaseException as exc:  # noqa: BLE001 - thread outcome is asserted below
            errors.append(exc)

    approve_thread = Thread(target=decide, args=("approve_role_change",))
    reject_thread = Thread(target=decide, args=("reject_role_change",))
    approve_thread.start()
    assert first_helper_entered.wait(timeout=2)
    reject_thread.start()

    assert not second_helper_entered.wait(timeout=0.1)
    release_first.set()
    approve_thread.join(timeout=2)
    reject_thread.join(timeout=2)

    assert not approve_thread.is_alive()
    assert not reject_thread.is_alive()
    assert results == [request]
    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)
    assert request.state == RoleChangeState.APPROVED
    assert security.user_roles[request.target_user] == request.new_role
    assert request.request_id not in security.pending_role_changes
    assert security.decided_role_changes[request.request_id] is request


def test_a_refused_second_decision_writes_one_failure_event_and_no_decision_event(
    tmp_path: Path,
) -> None:
    store = audit.SQLiteAuditEventStore(tmp_path / "audit-events.sqlite3")
    store.initialize()
    audit.set_default_store(store)
    try:
        security = SecurityModel(user_roles={"susan": RoleName.SYSTEM_ADMIN})
        request = security.request_role_change(
            requester="alice", target_user="bob", new_role=RoleName.FINANCE_ADMIN
        )
        security.approve_role_change(
            admin_actor="susan",
            admin_role=RoleName.SYSTEM_ADMIN,
            request_id=request.request_id,
        )
        before = list(store.query(event_type=audit.EVENT_RBAC_ROLE_CHANGE))

        with pytest.raises(ValueError):
            security.reject_role_change(
                admin_actor="susan",
                admin_role=RoleName.SYSTEM_ADMIN,
                request_id=request.request_id,
            )

        after = list(store.query(event_type=audit.EVENT_RBAC_ROLE_CHANGE))
        refused = after[len(before) :]
        assert len(refused) == 1
        assert refused[0].outcome == audit.OUTCOME_FAILURE
        assert refused[0].metadata["reason_code"] == "rbac.role_change_already_decided"
        assert refused[0].metadata["transition"] == "reject"
        assert refused[0].metadata["current_state"] == RoleChangeState.APPROVED.value
        assert refused[0].metadata["transition"] not in {"approved", "rejected"}
    finally:
        audit.reset_default_store()
        store.close()


def test_audit_log_captures_authentication_and_authorization_events() -> None:
    audit_log = AuditLog()
    audit_log.record(
        event_type=AuditEventType.AUTHENTICATION,
        actor="test-user",
        outcome="success",
        metadata={"idp": "okta"},
    )
    audit_log.record(
        event_type=AuditEventType.AUTHORIZATION,
        actor="test-user",
        subject="resource",
        outcome="allowed",
    )

    assert len(audit_log.filter_by_type(AuditEventType.AUTHENTICATION)) == 1
    assert len(audit_log.filter_by_type(AuditEventType.AUTHORIZATION)) == 1


def test_sso_plan_supports_major_providers() -> None:
    providers = DEFAULT_SSO_PLANS
    assert {"azure_ad", "okta", "google"} <= set(providers)

    for plan in providers.values():
        assert plan.issuer
        assert plan.token_endpoint
        assert plan.jwks_uri
        assert plan.supports_pkce is True
