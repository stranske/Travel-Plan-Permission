"""Prompt flow helpers for collecting trip details."""

from __future__ import annotations

import io
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from reportlab.lib.pagesizes import letter  # type: ignore[import-untyped]
from reportlab.lib.styles import getSampleStyleSheet  # type: ignore[import-untyped]
from reportlab.lib.units import inch  # type: ignore[import-untyped]
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer  # type: ignore[import-untyped]

from .mapping import DEFAULT_TEMPLATE_VERSION

CANONICAL_TRIP_FIELDS: tuple[str, ...] = (
    "traveler_name",
    "business_purpose",
    "cost_center",
    "destination_zip",
    "city_state",
    "depart_date",
    "return_date",
    "event_registration_cost",
    "flight_pref_outbound.carrier_flight",
    "flight_pref_outbound.depart_time",
    "flight_pref_outbound.arrive_time",
    "flight_pref_outbound.roundtrip_cost",
    "flight_pref_return.carrier_flight",
    "flight_pref_return.depart_time",
    "flight_pref_return.arrive_time",
    "lowest_cost_roundtrip",
    "parking_estimate",
    "hotel.name",
    "hotel.address",
    "hotel.city_state",
    "hotel.nightly_rate",
    "hotel.nights",
    "hotel.conference_hotel",
    "hotel.price_compare_notes",
    "comparable_hotels[0].name",
    "comparable_hotels[0].nightly_rate",
    "ground_transport_pref",
    "notes",
)


@dataclass(frozen=True)
class Question:
    """Single intake question that may fulfill multiple fields."""

    prompt: str
    fields: tuple[str, ...]
    kind: str = "text"
    options: tuple[str, ...] = field(default_factory=tuple)
    required: bool = True


QUESTION_FLOW: tuple[Question, ...] = (
    Question("Who is traveling?", ("traveler_name",)),
    Question(
        "Where are you headed and what's the destination ZIP?",
        ("city_state", "destination_zip"),
    ),
    Question("What are the departure and return dates?", ("depart_date", "return_date")),
    Question(
        "What's the business purpose and cost center?",
        ("business_purpose", "cost_center"),
    ),
    Question(
        "Share outbound and return flight preferences (flight number and times).",
        (
            "flight_pref_outbound.carrier_flight",
            "flight_pref_outbound.depart_time",
            "flight_pref_outbound.arrive_time",
            "flight_pref_return.carrier_flight",
            "flight_pref_return.depart_time",
            "flight_pref_return.arrive_time",
        ),
    ),
    Question(
        "What is the best available roundtrip fare and your chosen fare?",
        ("flight_pref_outbound.roundtrip_cost", "lowest_cost_roundtrip"),
    ),
    Question(
        "Where will you stay (name, address, nightly rate, nights)?",
        (
            "hotel.name",
            "hotel.address",
            "hotel.city_state",
            "hotel.nightly_rate",
            "hotel.nights",
        ),
    ),
    Question(
        "Is this the conference hotel? Add price comparison notes if not.",
        ("hotel.conference_hotel", "hotel.price_compare_notes"),
        kind="confirm",
    ),
    Question(
        "Any ground transport preference?",
        ("ground_transport_pref",),
        kind="choice",
        options=(
            "rideshare/taxi",
            "rental car",
            "public transit",
            "personal vehicle",
        ),
    ),
    Question(
        "Any extras to capture? (parking estimate, registration fee, notes)",
        ("parking_estimate", "event_registration_cost", "notes"),
        required=False,
    ),
)


def _is_filled(field: str, answers: dict[str, object]) -> bool:
    return field in answers and answers[field] not in (None, "")


def generate_questions(
    answers: dict[str, object],
    *,
    max_questions: int = 10,
    question_flow: Sequence[Question] = QUESTION_FLOW,
) -> list[Question]:
    """Return the next questions needed to complete required fields."""

    queued: list[Question] = []
    for question in question_flow:
        if len(queued) >= max_questions:
            break
        if all(_is_filled(field, answers) for field in question.fields):
            continue
        queued.append(question)
    return queued[:max_questions]


def build_output_bundle(
    *,
    itinerary_excel: bytes,
    answers: dict[str, object],
    conversation_log: Sequence[dict[str, object]] | None = None,
    brochure: bytes | None = None,
    template_version: str = DEFAULT_TEMPLATE_VERSION,
) -> dict[str, object]:
    """Assemble the output bundle with binary artifacts and metadata."""

    conversation = list(conversation_log or [])
    if brochure is not None:
        conversation.append(
            {
                "type": "attachment",
                "name": "conference_brochure.pdf",
                "description": "Traveler provided brochure for reference",
            }
        )

    summary_lines = [
        "Travel Plan Summary",
        f"Traveler: {answers.get('traveler_name', 'Unknown')}",
        f"Destination: {answers.get('city_state', 'Unknown')}",
        f"Dates: {answers.get('depart_date', '')} to {answers.get('return_date', '')}",
        f"Template: {template_version}",
    ]
    summary_bytes = "\n".join(summary_lines).encode("utf-8")
    summary_pdf_bytes = _build_summary_pdf(summary_lines)

    attachments: dict[str, bytes] = {}
    if brochure is not None:
        attachments["conference_brochure.pdf"] = brochure

    summary_payload: dict[str, object]
    if _looks_like_pdf(summary_pdf_bytes):
        summary_payload = {
            "filename": "summary.pdf",
            "content": summary_pdf_bytes,
            "mime_type": "application/pdf",
        }
    else:
        summary_payload = {
            "filename": "summary.txt",
            "content": summary_bytes,
            "mime_type": "text/plain",
        }

    bundle: dict[str, object] = {
        "itinerary_excel": {
            "filename": "itinerary.xlsx",
            "content": itinerary_excel,
            "template_version": template_version,
        },
        "summary_pdf": summary_payload,
        "conversation_log_json": json.dumps(conversation, ensure_ascii=False),
        "attachments": attachments,
    }

    return bundle


def _build_summary_pdf(summary_lines: Sequence[str]) -> bytes:
    """Render the summary lines into a simple PDF."""

    buffer = io.BytesIO()
    try:
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            title=summary_lines[0] if summary_lines else "Travel Plan Summary",
        )
        styles = getSampleStyleSheet()
        elements = []
        if summary_lines:
            elements.append(Paragraph(summary_lines[0], styles["Title"]))
        for line in summary_lines[1:]:
            elements.append(Spacer(1, 0.12 * inch))
            elements.append(Paragraph(line, styles["Normal"]))
        doc.build(elements)
    except Exception:
        return b""
    return buffer.getvalue()


def _looks_like_pdf(payload: bytes) -> bool:
    """Basic PDF signature check to avoid mislabeled text."""

    if not payload.startswith(b"%PDF-"):
        return False
    if b"/Type /Page" not in payload:
        return False
    trailer = payload[-2048:] if len(payload) > 2048 else payload
    return b"%%EOF" in trailer


def required_field_gaps(
    answers: dict[str, object], required_fields: Iterable[str] = CANONICAL_TRIP_FIELDS
) -> list[str]:
    """List required canonical fields that are still missing."""

    return [field for field in required_fields if not _is_filled(field, answers)]
