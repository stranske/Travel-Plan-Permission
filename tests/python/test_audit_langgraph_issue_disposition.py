import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.audit_langgraph_issue_disposition import (  # noqa: E402
    build_comment_report,
    build_disposition_report,
    is_report_passing,
    summarize_checkboxes,
    summarize_gate_sections,
)


def test_summarize_checkboxes_counts_checked_and_unchecked() -> None:
    body = "\n".join(
        [
            "### Tasks",
            "- [x] completed task",
            "- [ ] pending task",
            "not a task",
        ]
    )

    summary = summarize_checkboxes(body)

    assert summary.total == 2
    assert summary.checked == 1
    assert summary.unchecked_items == ("pending task",)


def test_summarize_gate_sections_tracks_tasks_and_acceptance_independently() -> None:
    body = "\n".join(
        [
            "## Tasks",
            "- [x] completed task",
            "- [ ] pending task",
            "## Acceptance Criteria",
            "- [x] accepted one",
            "- [ ] accepted two",
        ]
    )

    summary = summarize_gate_sections(body)

    assert summary.tasks.total == 2
    assert summary.tasks.checked == 1
    assert summary.tasks.unchecked_items == ("pending task",)
    assert summary.acceptance.total == 2
    assert summary.acceptance.checked == 1
    assert summary.acceptance.unchecked_items == ("accepted two",)


def test_closed_issue_without_approval_is_flagged_as_premature() -> None:
    issue = {
        "number": 939,
        "html_url": "https://github.com/stranske/Travel-Plan-Permission/issues/939",
        "state": "closed",
        "body": "## Tasks\n- [x] done\n## Acceptance Criteria\n- [ ] needs maintainer review",
    }
    comments: list[dict[str, object]] = []

    report = build_disposition_report(
        issue_json=issue,
        comments_json=comments,
        maintainers=("maintainer-a",),
        approval_regexes=(r"\bapprove(?:d)?\b",),
    )

    assert report["summary"]["prematurely_closed"] is True
    assert is_report_passing(report) is False


def test_open_issue_without_approval_is_allowed_to_remain_open() -> None:
    issue = {
        "number": 939,
        "html_url": "https://github.com/stranske/Travel-Plan-Permission/issues/939",
        "state": "open",
        "body": "## Tasks\n- [x] done\n## Acceptance Criteria\n- [ ] waiting on maintainer approval",
    }

    report = build_disposition_report(
        issue_json=issue,
        comments_json=[],
        maintainers=("maintainer-a",),
        approval_regexes=(r"\bapprove(?:d)?\b",),
    )

    assert report["summary"]["prematurely_closed"] is False
    assert report["summary"]["ready_to_close"] is False
    assert is_report_passing(report) is True


def test_ready_to_close_when_checkboxes_complete_and_maintainer_approves() -> None:
    issue = {
        "number": 939,
        "html_url": "https://github.com/stranske/Travel-Plan-Permission/issues/939",
        "state": "open",
        "body": "## Tasks\n- [x] task one\n## Acceptance Criteria\n- [x] task two",
    }
    comments = [
        {
            "user": {"login": "maintainer-a"},
            "body": "I approve this disposition; safe to close.",
            "html_url": "https://github.com/stranske/Travel-Plan-Permission/issues/939#issuecomment-1",
            "author_association": "MEMBER",
        },
        {
            "user": {"login": "contributor-b"},
            "body": "looks good",
            "html_url": "https://github.com/stranske/Travel-Plan-Permission/issues/939#issuecomment-2",
            "author_association": "CONTRIBUTOR",
        },
    ]

    report = build_disposition_report(
        issue_json=issue,
        comments_json=comments,
        maintainers=("maintainer-a",),
        approval_regexes=(r"\bapprove(?:d)?\b", r"\blgtm\b"),
    )

    assert report["summary"]["maintainer_approved"] is True
    assert report["summary"]["ready_to_close"] is True
    assert len(report["approvals"]) == 1
    assert report["approvals"][0]["association"] == "MEMBER"


def test_approval_requires_trusted_association_when_maintainer_list_not_set() -> None:
    issue = {
        "number": 939,
        "html_url": "https://github.com/stranske/Travel-Plan-Permission/issues/939",
        "state": "open",
        "body": "## Tasks\n- [x] task one\n## Acceptance Criteria\n- [x] task two",
    }
    comments = [
        {
            "user": {"login": "external-contributor"},
            "body": "LGTM, approving this",
            "html_url": "https://github.com/stranske/Travel-Plan-Permission/issues/939#issuecomment-3",
            "author_association": "CONTRIBUTOR",
        }
    ]

    report = build_disposition_report(
        issue_json=issue,
        comments_json=comments,
        maintainers=(),
        approval_regexes=(r"\bapprove(?:d)?\b", r"\blgtm\b"),
    )

    assert report["summary"]["maintainer_approved"] is False
    assert report["summary"]["ready_to_close"] is False
    assert report["approvals"] == []


def test_member_approval_counts_without_explicit_maintainer_list() -> None:
    issue = {
        "number": 939,
        "html_url": "https://github.com/stranske/Travel-Plan-Permission/issues/939",
        "state": "open",
        "body": "## Tasks\n- [x] task one\n## Acceptance Criteria\n- [x] task two",
    }
    comments = [
        {
            "user": {"login": "repo-maintainer"},
            "body": "Approved. This can be closed.",
            "html_url": "https://github.com/stranske/Travel-Plan-Permission/issues/939#issuecomment-4",
            "author_association": "OWNER",
        }
    ]

    report = build_disposition_report(
        issue_json=issue,
        comments_json=comments,
        maintainers=(),
        approval_regexes=(r"\bapprove(?:d)?\b",),
    )

    assert report["summary"]["maintainer_approved"] is True
    assert report["summary"]["ready_to_close"] is True
    assert len(report["approvals"]) == 1
    assert report["approvals"][0]["association"] == "OWNER"


def test_bot_member_approval_does_not_count() -> None:
    issue = {
        "number": 939,
        "html_url": "https://github.com/stranske/Travel-Plan-Permission/issues/939",
        "state": "open",
        "body": "## Tasks\n- [x] task one\n## Acceptance Criteria\n- [x] task two",
    }
    comments = [
        {
            "user": {"login": "workflow-bot[bot]", "type": "Bot"},
            "body": "Approved.",
            "html_url": "https://github.com/stranske/Travel-Plan-Permission/issues/939#issuecomment-5",
            "author_association": "MEMBER",
        }
    ]

    report = build_disposition_report(
        issue_json=issue,
        comments_json=comments,
        maintainers=(),
        approval_regexes=(r"\bapprove(?:d)?\b",),
    )

    assert report["summary"]["maintainer_approved"] is False
    assert report["summary"]["ready_to_close"] is False
    assert report["approvals"] == []


def test_bot_named_in_maintainer_list_does_not_count() -> None:
    issue = {
        "number": 939,
        "html_url": "https://github.com/stranske/Travel-Plan-Permission/issues/939",
        "state": "open",
        "body": "## Tasks\n- [x] task one\n## Acceptance Criteria\n- [x] task two",
    }
    comments = [
        {
            "user": {"login": "ops-automation[bot]", "type": "Bot"},
            "body": "I approve this.",
            "html_url": "https://github.com/stranske/Travel-Plan-Permission/issues/939#issuecomment-6",
            "author_association": "OWNER",
        }
    ]

    report = build_disposition_report(
        issue_json=issue,
        comments_json=comments,
        maintainers=("ops-automation[bot]",),
        approval_regexes=(r"\bapprove(?:d)?\b",),
    )

    assert report["summary"]["maintainer_approved"] is False
    assert report["summary"]["ready_to_close"] is False
    assert report["approvals"] == []


def test_negated_approval_phrase_does_not_count() -> None:
    issue = {
        "number": 939,
        "html_url": "https://github.com/stranske/Travel-Plan-Permission/issues/939",
        "state": "open",
        "body": "## Tasks\n- [x] task one\n## Acceptance Criteria\n- [x] task two",
    }
    comments = [
        {
            "user": {"login": "maintainer-a"},
            "body": "Not approved yet; we still need another verification run.",
            "html_url": "https://github.com/stranske/Travel-Plan-Permission/issues/939#issuecomment-7",
            "author_association": "MEMBER",
        }
    ]

    report = build_disposition_report(
        issue_json=issue,
        comments_json=comments,
        maintainers=("maintainer-a",),
        approval_regexes=(r"\bapprove(?:d)?\b", r"\blgtm\b"),
    )

    assert report["summary"]["maintainer_approved"] is False
    assert report["summary"]["ready_to_close"] is False
    assert report["approvals"] == []


def test_quoted_approval_text_does_not_count() -> None:
    issue = {
        "number": 939,
        "html_url": "https://github.com/stranske/Travel-Plan-Permission/issues/939",
        "state": "open",
        "body": "## Tasks\n- [x] task one\n## Acceptance Criteria\n- [x] task two",
    }
    comments = [
        {
            "user": {"login": "maintainer-a"},
            "body": "> I approve this disposition.\nI am quoting prior discussion only.",
            "html_url": "https://github.com/stranske/Travel-Plan-Permission/issues/939#issuecomment-8",
            "author_association": "MEMBER",
        }
    ]

    report = build_disposition_report(
        issue_json=issue,
        comments_json=comments,
        maintainers=("maintainer-a",),
        approval_regexes=(r"\bapprove(?:d)?\b",),
    )

    assert report["summary"]["maintainer_approved"] is False
    assert report["summary"]["ready_to_close"] is False
    assert report["approvals"] == []


def test_code_fence_approval_text_does_not_count() -> None:
    issue = {
        "number": 939,
        "html_url": "https://github.com/stranske/Travel-Plan-Permission/issues/939",
        "state": "open",
        "body": "## Tasks\n- [x] task one\n## Acceptance Criteria\n- [x] task two",
    }
    comments = [
        {
            "user": {"login": "maintainer-a"},
            "body": "```text\nApproved.\n```\nNo explicit sign-off yet.",
            "html_url": "https://github.com/stranske/Travel-Plan-Permission/issues/939#issuecomment-9",
            "author_association": "MEMBER",
        }
    ]

    report = build_disposition_report(
        issue_json=issue,
        comments_json=comments,
        maintainers=("maintainer-a",),
        approval_regexes=(r"\bapprove(?:d)?\b",),
    )

    assert report["summary"]["maintainer_approved"] is False
    assert report["summary"]["ready_to_close"] is False
    assert report["approvals"] == []


def test_ready_to_close_requires_acceptance_section_checkboxes() -> None:
    issue = {
        "number": 939,
        "html_url": "https://github.com/stranske/Travel-Plan-Permission/issues/939",
        "state": "open",
        "body": "## Tasks\n- [x] task one\n- [x] task two",
    }
    comments = [
        {
            "user": {"login": "maintainer-a"},
            "body": "Approved.",
            "author_association": "MEMBER",
        }
    ]

    report = build_disposition_report(
        issue_json=issue,
        comments_json=comments,
        maintainers=("maintainer-a",),
        approval_regexes=(r"\bapprove(?:d)?\b",),
    )

    assert report["summary"]["tasks_complete"] is True
    assert report["summary"]["acceptance_complete"] is False
    assert report["summary"]["ready_to_close"] is False


def test_comment_report_includes_needs_human_on_failure() -> None:
    report = {
        "issue": {
            "number": 939,
            "url": "https://example.invalid/939",
            "state": "closed",
        },
        "summary": {
            "total_checkboxes": 2,
            "checked_checkboxes": 1,
            "unchecked_checkboxes": 1,
            "tasks_checkboxes_total": 1,
            "tasks_checkboxes_checked": 1,
            "tasks_complete": True,
            "acceptance_checkboxes_total": 1,
            "acceptance_checkboxes_checked": 0,
            "acceptance_complete": False,
            "approval_comments": 0,
            "maintainer_approved": False,
            "ready_to_close": False,
            "issue_open": False,
            "prematurely_closed": True,
            "passing": False,
        },
        "remaining_checkboxes": ["pending"],
        "remaining_tasks": [],
        "remaining_acceptance": ["pending"],
        "approvals": [],
    }

    comment = build_comment_report(report)

    assert "LangGraph Issue Disposition Audit" in comment
    assert "Needs human" in comment
    assert "Issue was closed before completion" in comment
