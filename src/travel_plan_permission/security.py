"""Security model definitions for travel plan permissions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class Permission(StrEnum):
    """Supported permissions for API endpoints."""

    VIEW = "view"
    CREATE = "create"
    APPROVE = "approve"
    EXPORT = "export"
    CONFIGURE = "configure"


class RoleName(StrEnum):
    """Defined roles within the travel system."""

    TRAVELER = "traveler"
    APPROVER = "approver"
    FINANCE_ADMIN = "finance_admin"
    POLICY_ADMIN = "policy_admin"
    SYSTEM_ADMIN = "system_admin"


@dataclass(frozen=True)
class Role:
    """Role definition including its permissions."""

    name: RoleName
    permissions: set[Permission]

    def can(self, permission: Permission) -> bool:
        """Return whether the role grants a permission."""

        return permission in self.permissions


DEFAULT_ROLES: dict[RoleName, Role] = {
    RoleName.TRAVELER: Role(
        name=RoleName.TRAVELER, permissions={Permission.VIEW, Permission.CREATE}
    ),
    RoleName.APPROVER: Role(
        name=RoleName.APPROVER,
        permissions={Permission.VIEW, Permission.APPROVE},
    ),
    RoleName.FINANCE_ADMIN: Role(
        name=RoleName.FINANCE_ADMIN,
        permissions={
            Permission.VIEW,
            Permission.APPROVE,
            Permission.EXPORT,
        },
    ),
    RoleName.POLICY_ADMIN: Role(
        name=RoleName.POLICY_ADMIN,
        permissions={
            Permission.VIEW,
            Permission.CONFIGURE,
        },
    ),
    RoleName.SYSTEM_ADMIN: Role(
        name=RoleName.SYSTEM_ADMIN,
        permissions=set(Permission),
    ),
}


API_ENDPOINT_PERMISSIONS: dict[str, Permission] = {
    "GET /api/itineraries": Permission.VIEW,
    "POST /api/itineraries": Permission.CREATE,
    "GET /api/itineraries/:id": Permission.VIEW,
    "POST /api/approvals/:id/decision": Permission.APPROVE,
    "POST /api/approvals/delegate": Permission.APPROVE,
    "POST /api/exports/expenses": Permission.EXPORT,
    "GET /api/exports/audit": Permission.EXPORT,
    "POST /api/policy/version": Permission.CONFIGURE,
    "POST /api/policy/rules": Permission.CONFIGURE,
    "POST /api/admin/roles": Permission.CONFIGURE,
    "POST /api/admin/sso/validate": Permission.CONFIGURE,
}


class AuditEventType(StrEnum):
    """Types of audit events recorded by the system."""

    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    ROLE_CHANGE = "role_change"
    DELEGATION = "delegation"


@dataclass
class AuditLogEvent:
    """Single audit log entry capturing auth-related activity."""

    event_type: AuditEventType
    actor: str
    subject: str | None
    outcome: str
    metadata: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class AuditLog:
    """In-memory audit log capturing authentication and authorization events."""

    events: list[AuditLogEvent] = field(default_factory=list)

    def record(
        self,
        event_type: AuditEventType,
        actor: str,
        outcome: str,
        subject: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditLogEvent:
        """Record a new audit event."""

        event = AuditLogEvent(
            event_type=event_type,
            actor=actor,
            subject=subject,
            outcome=outcome,
            metadata=metadata or {},
        )
        self.events.append(event)
        return event

    def filter_by_type(self, event_type: AuditEventType) -> list[AuditLogEvent]:
        """Return audit events filtered by type."""

        return [event for event in self.events if event.event_type == event_type]


@dataclass(frozen=True)
class Delegation:
    """Delegation contract that allows a backup to act for a primary."""

    primary_user: str
    backup_user: str
    permissions: set[Permission]


class RoleChangeState(StrEnum):
    """Lifecycle state for role change requests."""

    PENDING_APPROVAL = "pending_admin_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class RoleChangeRequest:
    """Representation of a requested role change awaiting admin decision."""

    request_id: str
    requester: str
    target_user: str
    new_role: RoleName
    state: RoleChangeState = RoleChangeState.PENDING_APPROVAL


@dataclass
class SSOProviderPlan:
    """Plan for integrating with a specific SSO provider."""

    name: str
    issuer: str
    token_endpoint: str
    jwks_uri: str
    supports_pkce: bool


DEFAULT_SSO_PLANS: dict[str, SSOProviderPlan] = {
    "azure_ad": SSOProviderPlan(
        name="Azure AD",
        issuer="https://login.microsoftonline.com/{tenant_id}/v2.0",
        token_endpoint="https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
        jwks_uri="https://login.microsoftonline.com/common/discovery/v2.0/keys",
        supports_pkce=True,
    ),
    "okta": SSOProviderPlan(
        name="Okta",
        issuer="https://{yourOktaDomain}/oauth2/default",
        token_endpoint="https://{yourOktaDomain}/oauth2/default/v1/token",
        jwks_uri="https://{yourOktaDomain}/oauth2/default/v1/keys",
        supports_pkce=True,
    ),
    "google": SSOProviderPlan(
        name="Google",
        issuer="https://accounts.google.com",
        token_endpoint="https://oauth2.googleapis.com/token",
        jwks_uri="https://www.googleapis.com/oauth2/v3/certs",
        supports_pkce=True,
    ),
}


class SecurityModel:
    """Security model that maps roles to permissions and endpoint policies."""

    def __init__(
        self,
        roles: dict[RoleName, Role] | None = None,
        endpoint_permissions: dict[str, Permission] | None = None,
        audit_log: AuditLog | None = None,
        sso_plans: dict[str, SSOProviderPlan] | None = None,
    ) -> None:
        self.roles = roles or DEFAULT_ROLES
        self.endpoint_permissions = endpoint_permissions or API_ENDPOINT_PERMISSIONS
        self.audit_log = audit_log or AuditLog()
        self.delegations: dict[str, Delegation] = {}
        self.sso_plans = sso_plans or DEFAULT_SSO_PLANS
        self.pending_role_changes: dict[str, RoleChangeRequest] = {}

    def required_permission(self, endpoint: str) -> Permission:
        """Return the permission required for an API endpoint."""

        if endpoint not in self.endpoint_permissions:
            raise KeyError(f"No permission mapped for endpoint '{endpoint}'")
        return self.endpoint_permissions[endpoint]

    def authorize(
        self,
        user: str,
        role: RoleName,
        endpoint: str,
        *,
        acting_on_behalf_of: str | None = None,
    ) -> bool:
        """Authorize access to an endpoint, including delegated approval."""

        required = self.required_permission(endpoint)
        role_allows = self.roles[role].can(required)
        delegated_allows = False
        if acting_on_behalf_of:
            delegation = self.delegations.get(acting_on_behalf_of)
            delegated_allows = (
                delegation is not None
                and delegation.backup_user == user
                and required in delegation.permissions
            )

        allowed = role_allows or delegated_allows
        self.audit_log.record(
            event_type=AuditEventType.AUTHORIZATION,
            actor=user,
            subject=acting_on_behalf_of,
            outcome="allowed" if allowed else "denied",
            metadata={
                "role": role.value,
                "endpoint": endpoint,
                "required_permission": required.value,
                "delegated": acting_on_behalf_of if delegated_allows else None,
            },
        )
        return allowed

    def register_delegation(self, primary_user: str, backup_user: str) -> Delegation:
        """Register a delegation that allows a backup to approve for a primary."""

        delegation = Delegation(
            primary_user=primary_user,
            backup_user=backup_user,
            permissions={Permission.APPROVE},
        )
        self.delegations[primary_user] = delegation
        self.audit_log.record(
            event_type=AuditEventType.DELEGATION,
            actor=primary_user,
            subject=backup_user,
            outcome="created",
            metadata={"permissions": sorted(p.value for p in delegation.permissions)},
        )
        return delegation

    def request_role_change(
        self, requester: str, target_user: str, new_role: RoleName
    ) -> RoleChangeRequest:
        """Create a role change request that requires admin approval."""

        request = RoleChangeRequest(
            request_id=str(uuid4()),
            requester=requester,
            target_user=target_user,
            new_role=new_role,
        )
        self.pending_role_changes[request.request_id] = request
        self.audit_log.record(
            event_type=AuditEventType.ROLE_CHANGE,
            actor=requester,
            subject=target_user,
            outcome=RoleChangeState.PENDING_APPROVAL.value,
            metadata={"new_role": new_role.value},
        )
        return request

    def approve_role_change(
        self, admin_actor: str, admin_role: RoleName, request_id: str
    ) -> RoleChangeRequest:
        """Approve a pending role change; only admins may approve."""

        if admin_role not in {RoleName.SYSTEM_ADMIN, RoleName.POLICY_ADMIN}:
            raise PermissionError("Only admin roles may approve role changes")

        request = self.pending_role_changes.get(request_id)
        if request is None:
            raise KeyError(f"No pending role change for id '{request_id}'")

        request.state = RoleChangeState.APPROVED
        self.audit_log.record(
            event_type=AuditEventType.ROLE_CHANGE,
            actor=admin_actor,
            subject=request.target_user,
            outcome=request.state.value,
            metadata={"new_role": request.new_role.value},
        )
        return request

    def reject_role_change(
        self, admin_actor: str, admin_role: RoleName, request_id: str
    ) -> RoleChangeRequest:
        """Reject a pending role change; only admins may reject."""

        if admin_role not in {RoleName.SYSTEM_ADMIN, RoleName.POLICY_ADMIN}:
            raise PermissionError("Only admin roles may reject role changes")

        request = self.pending_role_changes.get(request_id)
        if request is None:
            raise KeyError(f"No pending role change for id '{request_id}'")

        request.state = RoleChangeState.REJECTED
        self.audit_log.record(
            event_type=AuditEventType.ROLE_CHANGE,
            actor=admin_actor,
            subject=request.target_user,
            outcome=request.state.value,
            metadata={"new_role": request.new_role.value},
        )
        return request
