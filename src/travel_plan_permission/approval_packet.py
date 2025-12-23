"""Approval packet generation for multi-level approvers."""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Mapping, Sequence

from jinja2 import BaseLoader, Environment, select_autoescape
from pydantic import BaseModel, Field
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .models import ApprovalEvent, TripPlan


@dataclass(frozen=True)
class ApprovalLinks:
    """Links for approvers to make decisions."""

    approve_url: str
    reject_url: str
    override_url: str


class EmailContent(BaseModel):
    """Rendered email content ready for transport."""

    subject: str = Field(..., description="Email subject line")
    body: str = Field(..., description="Plain-text email body")


class ApprovalPacket(BaseModel):
    """Structured approval packet containing email and PDF assets."""

    trip_plan: TripPlan
    compliance_status: str
    total_cost: Decimal
    cost_breakdown: dict[str, Decimal]
    approval_history: tuple[ApprovalEvent, ...]
    manager_email: EmailContent
    board_email: EmailContent
    pdf_bytes: bytes
    generated_at: datetime


_EMAIL_ENV = Environment(
    loader=BaseLoader(),
    autoescape=select_autoescape(
        enabled_extensions=("html",),
        default_for_string=False,
        default=True,
    ),
)

MANAGER_EMAIL_TEMPLATE = """Subject: Travel plan approval request for {{ trip.traveler_name }}

Hello {{ recipient_name or "Manager" }},

Trip summary:
- Traveler: {{ trip.traveler_name }}
- Destination: {{ trip.destination }}
- Dates: {{ trip.departure_date }} to {{ trip.return_date }}
- Total cost: ${{ "%.2f"|format(total_cost) }}
- Policy compliance: {{ compliance_status }}

Approve: {{ links.approve_url }}
Reject: {{ links.reject_url }}
Override (include justification): {{ links.override_url }}

This request maintains an immutable approval history with {{ history_count }} entries.
"""

BOARD_EMAIL_TEMPLATE = """Subject: Board approval packet for {{ trip.traveler_name }}'s trip

Board member,

Please review the attached approval packet:
- Traveler: {{ trip.traveler_name }}
- Destination: {{ trip.destination }}
- Dates: {{ trip.departure_date }} to {{ trip.return_date }}
- Total cost: ${{ "%.2f"|format(total_cost) }}
- Policy compliance: {{ compliance_status }}
- Prior approvals logged: {{ history_count }}

Approve: {{ links.approve_url }}
Reject: {{ links.reject_url }}
Override (include justification): {{ links.override_url }}

Approval history and override justifications are auditable in the attached PDF.
"""


def _render_email(template: str, context: Mapping[str, object]) -> EmailContent:
    compiled = _EMAIL_ENV.from_string(template)
    body = compiled.render(**context)

    subject_line = body.splitlines()[0].removeprefix("Subject: ").strip()
    cleaned_body = "\n".join(body.splitlines()[1:]).strip()
    return EmailContent(subject=subject_line, body=cleaned_body)


def _format_cost_breakdown(costs: Mapping[str, Decimal]) -> list[list[str]]:
    rows = [["Category", "Amount (USD)"]]
    for category, amount in costs.items():
        category_label = getattr(category, "value", category)
        rows.append([str(category_label), f"${amount.quantize(Decimal('0.01'))}"])
    return rows


def generate_packet_pdf(
    *,
    trip_plan: TripPlan,
    compliance_status: str,
    cost_breakdown: Mapping[str, Decimal],
    approval_history: Sequence[ApprovalEvent],
    entries_per_page: int = 15,
) -> bytes:
    """Create a summary PDF with trip details, policy status, costs, and history."""

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        title=f"Approval Packet - {trip_plan.trip_id}",
        author=trip_plan.traveler_name,
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="Small",
            parent=styles["Normal"],
            fontSize=9,
            leading=11,
        )
    )

    elements = [
        Paragraph("Travel Approval Packet", styles["Title"]),
        Spacer(1, 0.2 * inch),
        Paragraph(f"Traveler: {trip_plan.traveler_name}", styles["Normal"]),
        Paragraph(f"Destination: {trip_plan.destination}", styles["Normal"]),
        Paragraph(
            f"Dates: {trip_plan.departure_date} to {trip_plan.return_date}",
            styles["Normal"],
        ),
        Paragraph(f"Policy compliance: {compliance_status}", styles["Normal"]),
        Spacer(1, 0.15 * inch),
        Paragraph("Cost breakdown", styles["Heading2"]),
    ]

    cost_rows = _format_cost_breakdown(cost_breakdown)
    cost_table = Table(cost_rows, hAlign="LEFT")
    cost_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]
        )
    )
    elements.append(cost_table)

    if len(cost_rows) + len(approval_history) > entries_per_page:
        elements.append(PageBreak())
    else:
        elements.append(Spacer(1, 0.2 * inch))

    elements.append(Paragraph("Approval and override history", styles["Heading2"]))
    history_rows = [["Approver", "Level", "Outcome", "Timestamp", "Justification"]]
    for event in approval_history:
        history_rows.append(
            [
                event.approver_id,
                event.level,
                event.outcome.value,
                event.timestamp.isoformat(),
                event.justification or "",
            ]
        )

    history_table = Table(history_rows, hAlign="LEFT", repeatRows=1)
    history_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    elements.append(history_table)

    doc.build(elements)
    return buffer.getvalue()


def build_approval_packet(
    *,
    trip_plan: TripPlan,
    compliance_status: str,
    approval_links: ApprovalLinks,
    board_links: ApprovalLinks | None = None,
    cost_breakdown: Mapping[str, Decimal] | None = None,
    approval_history: Sequence[ApprovalEvent] | None = None,
) -> ApprovalPacket:
    """Render emails and PDF for a multi-level approval packet."""

    raw_costs = cost_breakdown or trip_plan.expense_breakdown
    costs = {
        str(getattr(category, "value", category)): amount for category, amount in raw_costs.items()
    }
    if not costs and trip_plan.estimated_cost:
        costs["estimated_total"] = trip_plan.estimated_cost

    history = tuple(approval_history or trip_plan.approval_history)
    total_cost = sum(costs.values(), Decimal("0"))

    base_context = {
        "trip": trip_plan,
        "total_cost": total_cost,
        "compliance_status": compliance_status,
        "history_count": len(history),
    }
    manager_email = _render_email(
        MANAGER_EMAIL_TEMPLATE,
        {**base_context, "links": approval_links, "recipient_name": "Manager"},
    )
    board_email = _render_email(
        BOARD_EMAIL_TEMPLATE,
        {"links": board_links or approval_links, **base_context},
    )

    pdf_bytes = generate_packet_pdf(
        trip_plan=trip_plan,
        compliance_status=compliance_status,
        cost_breakdown=costs,
        approval_history=history,
    )

    return ApprovalPacket(
        trip_plan=trip_plan,
        compliance_status=compliance_status,
        total_cost=total_cost,
        cost_breakdown=costs,
        approval_history=history,
        manager_email=manager_email,
        board_email=board_email,
        pdf_bytes=pdf_bytes,
        generated_at=datetime.now(UTC),
    )
