from travel_plan_permission import prompt_flow
from travel_plan_permission.prompt_flow import (
    build_output_bundle,
    generate_questions,
    required_field_gaps,
)


def test_generate_questions_limits_to_ten_and_skips_answered():
    answers = {"traveler_name": "Ada Lovelace", "city_state": "Boston, MA"}
    questions = generate_questions(answers, max_questions=10)

    assert len(questions) <= 10
    prompts = [q.prompt for q in questions]
    assert any("departure and return" in prompt for prompt in prompts)
    assert all("Who is traveling" not in prompt for prompt in prompts)


def test_required_field_gaps_identifies_missing_fields():
    answers = {
        "traveler_name": "Ada Lovelace",
        "depart_date": "2025-10-01",
        "return_date": "2025-10-04",
    }
    missing = required_field_gaps(answers)

    assert "business_purpose" in missing
    assert "traveler_name" not in missing
    assert len(missing) > 0


def test_output_bundle_includes_brochure_reference():
    answers = {"traveler_name": "Ada Lovelace", "city_state": "Boston, MA"}
    itinerary = b"excel-bytes"
    conversation_log = [{"type": "question", "text": "Where to?"}]

    bundle = build_output_bundle(
        itinerary_excel=itinerary,
        answers=answers,
        conversation_log=conversation_log,
        brochure=b"brochure-bytes",
    )

    assert bundle["itinerary_excel"]["content"] == itinerary
    assert "conference_brochure.pdf" in bundle["attachments"]
    assert "conference_brochure.pdf" in bundle["conversation_log_json"]
    summary = bundle["summary_pdf"]
    assert summary["filename"] == "summary.pdf"
    assert summary["mime_type"] == "application/pdf"
    assert summary["content"].startswith(b"%PDF-")
    assert b"/Type /Page" in summary["content"]
    assert b"%%EOF" in summary["content"][-2048:]


def test_output_bundle_uses_text_for_invalid_pdf(monkeypatch):
    answers = {"traveler_name": "Ada Lovelace", "city_state": "Boston, MA"}
    itinerary = b"excel-bytes"

    monkeypatch.setattr(prompt_flow, "_build_summary_pdf", lambda _: b"not-a-pdf")

    bundle = build_output_bundle(
        itinerary_excel=itinerary,
        answers=answers,
    )

    summary = bundle["summary_pdf"]
    assert summary["filename"] == "summary.txt"
    assert summary["mime_type"] == "text/plain"
    assert b"Travel Plan Summary" in summary["content"]
