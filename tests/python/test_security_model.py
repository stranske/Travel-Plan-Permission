from __future__ import annotations

import pytest

from travel_plan_permission.security import (
    API_ENDPOINT_PERMISSIONS,
    DEFAULT_ROLES,
    DEFAULT_SSO_PLANS,
    AuditEventType,
    AuditLog,
    Permission,
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
    security = SecurityModel(audit_log=audit_log)
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

    role_change_events = audit_log.filter_by_type(AuditEventType.ROLE_CHANGE)
    assert {event.outcome for event in role_change_events} == {
        RoleChangeState.PENDING_APPROVAL.value,
        RoleChangeState.APPROVED.value,
    }


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
