"""Audit issue disposition gating for LangGraph follow-up closure criteria."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

CHECKBOX_PATTERN = re.compile(r"^\s*[-*]\s*\[(?P<mark>[ xX])\]\s*(?P<text>.+?)\s*$")
HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(?P<title>.+?)\s*$")
FENCE_PATTERN = re.compile(r"^\s*```")
DEFAULT_APPROVAL_PATTERNS = (
    r"\bapprove(?:d)?\b",
    r"\blgtm\b",
    r"\blooks\s+good\s+to\s+me\b",
    r"\bship\s+it\b",
    r"\b(?:has|have)\s+my\s+approval\b",
)
DEFAULT_TRUSTED_ASSOCIATIONS = ("COLLABORATOR", "MEMBER", "OWNER")
NEGATED_APPROVAL_PATTERNS = (
    re.compile(r"\b(?:do\s+not|don't|not|cannot|can't|no)\s+approve(?:d)?\b", re.IGNORECASE),
    re.compile(r"\b(?:do\s+not|don't|not|no)\s+lgtm\b", re.IGNORECASE),
    re.compile(r"\blgtm\b[^\n]{0,20}\b(?:not|yet|pending|later)\b", re.IGNORECASE),
    re.compile(
        r"\bapprove(?:d)?\b[^\n]{0,20}\b(?:not|yet|pending|later|after|once)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bwithhold(?:ing)?\s+approval\b", re.IGNORECASE),
    re.compile(r"\b(?:should|can|could|would)\s+(?:we\s+)?approve(?:d)?\b", re.IGNORECASE),
    re.compile(
        r"\b(?:do|does|did|is|are|was|were|will|shall)\s+(?:we\s+)?approve(?:d)?\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bplease\s+approve(?:d)?\b", re.IGNORECASE),
    re.compile(
        r"\b(?:anyone|someone|who)\s+(?:can|could|should)?\s*approve(?:d)?\b", re.IGNORECASE
    ),
    re.compile(r"\bapprove(?:d)?\b[^\n]{0,40}\?", re.IGNORECASE),
    re.compile(r"\blgtm\b[^\n]{0,40}\?", re.IGNORECASE),
    re.compile(r"\bapprove(?:d)?\s*\?", re.IGNORECASE),
    re.compile(r"\blgtm\s*\?", re.IGNORECASE),
    re.compile(r"\blooks\s+good\s+to\s+me\b[^\n]{0,40}\?", re.IGNORECASE),
    re.compile(
        r"\blooks\s+good\s+to\s+me\b[^\n]{0,20}\b(?:not|yet|pending|later|after|once)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:do\s+not|don't|not|cannot|can't|no)\s+ship\s+it\b", re.IGNORECASE),
    re.compile(r"\bship\s+it\b[^\n]{0,20}\b(?:not|yet|pending|later|after|once)\b", re.IGNORECASE),
    re.compile(r"\bplease\s+ship\s+it\b", re.IGNORECASE),
    re.compile(r"\b(?:should|can|could|would)\s+(?:we\s+)?ship\s+it\b", re.IGNORECASE),
    re.compile(
        r"\b(?:do|does|did|is|are|was|were|will|shall)\s+(?:we\s+)?ship\s+it\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bship\s+it\b[^\n]{0,40}\?", re.IGNORECASE),
    re.compile(r"\b(?:has|have)\s+my\s+approval\b[^\n]{0,40}\?", re.IGNORECASE),
    re.compile(
        r"\b(?:need|needs|pending|request(?:ed|ing)?)\s+(?:my\s+)?approval\b", re.IGNORECASE
    ),
    re.compile(
        (
            r"\b(?:approve(?:d)?|lgtm|looks\s+good\s+to\s+me|ship\s+it|"
            r"(?:has|have)\s+my\s+approval)\b[^\n]{0,80}"
            r"\b(?:keep|remain|stays?)\s+(?:this\s+)?issue\s+open\b"
        ),
        re.IGNORECASE,
    ),
    re.compile(
        (
            r"\b(?:approve(?:d)?|lgtm|looks\s+good\s+to\s+me|ship\s+it|"
            r"(?:has|have)\s+my\s+approval)\b[^\n]{0,80}"
            r"\b(?:continue|continuing)\s+(?:to\s+)?(?:investigat(?:e|ing)|triage|debug)\b"
        ),
        re.IGNORECASE,
    ),
    re.compile(
        (
            r"\b(?:approve(?:d)?|lgtm|looks\s+good\s+to\s+me|ship\s+it|"
            r"(?:has|have)\s+my\s+approval)\b[^\n]{0,80}"
            r"\b(?:not|isn't|is\s+not)\s+ready\s+to\s+close\b"
        ),
        re.IGNORECASE,
    ),
    re.compile(
        (
            r"\b(?:approve(?:d)?|lgtm|looks\s+good\s+to\s+me|ship\s+it|"
            r"(?:has|have)\s+my\s+approval)\b[^\n]{0,80}"
            r"\b(?:do\s+not|don't|cannot|can't)\s+close\b"
        ),
        re.IGNORECASE,
    ),
)

CLOSURE_CONTEXT_PATTERN = re.compile(
    r"\b(?:close|closed|closing|closure|disposition|ready\s+to\s+close|safe\s+to\s+close|"
    r"resolved?|complete(?:d)?|done)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CheckboxSummary:
    total: int
    checked: int
    unchecked_items: tuple[str, ...]


@dataclass(frozen=True)
class ApprovalEvidence:
    author: str
    url: str | None
    association: str
    snippet: str


@dataclass(frozen=True)
class SectionCheckboxSummary:
    tasks: CheckboxSummary
    acceptance: CheckboxSummary


def _iter_relevant_checkboxes(
    issue_body: str, *, section: str | None = None
) -> tuple[tuple[str | None, str, bool], ...]:
    rows: list[tuple[str | None, str, bool]] = []
    in_fence = False
    current_section: str | None = None

    for raw_line in issue_body.splitlines():
        line = raw_line.rstrip()
        if FENCE_PATTERN.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        heading_match = HEADING_PATTERN.match(line)
        if heading_match is not None:
            heading = heading_match.group("title").strip().lower()
            if "acceptance criteria" in heading:
                current_section = "acceptance"
            elif "tasks" in heading:
                current_section = "tasks"
            else:
                current_section = None
            continue

        checkbox_match = CHECKBOX_PATTERN.match(line)
        if checkbox_match is None:
            continue

        if section is not None and current_section != section:
            continue

        rows.append(
            (
                current_section,
                checkbox_match.group("text").strip(),
                checkbox_match.group("mark").lower() == "x",
            )
        )

    return tuple(rows)


def _load_json(path: Path) -> object:
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def summarize_checkboxes(issue_body: str) -> CheckboxSummary:
    checked = 0
    unchecked_items: list[str] = []
    rows = _iter_relevant_checkboxes(issue_body)

    for _, text, is_checked in rows:
        if is_checked:
            checked += 1
        else:
            unchecked_items.append(text)

    return CheckboxSummary(total=len(rows), checked=checked, unchecked_items=tuple(unchecked_items))


def summarize_gate_sections(issue_body: str) -> SectionCheckboxSummary:
    task_rows = _iter_relevant_checkboxes(issue_body, section="tasks")
    acceptance_rows = _iter_relevant_checkboxes(issue_body, section="acceptance")

    task_checked = sum(1 for _, _, is_checked in task_rows if is_checked)
    acceptance_checked = sum(1 for _, _, is_checked in acceptance_rows if is_checked)

    return SectionCheckboxSummary(
        tasks=CheckboxSummary(
            total=len(task_rows),
            checked=task_checked,
            unchecked_items=tuple(text for _, text, is_checked in task_rows if not is_checked),
        ),
        acceptance=CheckboxSummary(
            total=len(acceptance_rows),
            checked=acceptance_checked,
            unchecked_items=tuple(
                text for _, text, is_checked in acceptance_rows if not is_checked
            ),
        ),
    )


def _collect_approval_evidence(
    comments: list[dict[str, object]],
    *,
    maintainers: tuple[str, ...],
    approval_patterns: tuple[re.Pattern[str], ...],
) -> tuple[ApprovalEvidence, ...]:
    maintainers_set = {name.lower() for name in maintainers}
    trusted_associations = set(DEFAULT_TRUSTED_ASSOCIATIONS)
    evidence: list[ApprovalEvidence] = []

    for comment in comments:
        user = comment.get("user")
        if not isinstance(user, dict):
            continue
        author = str(user.get("login", "")).strip()
        if not author:
            continue
        user_type = str(user.get("type", "")).strip().lower()
        # Approval must come from a human maintainer, not an automation actor.
        if user_type == "bot" or author.lower().endswith("[bot]"):
            continue
        association = str(comment.get("author_association", "")).upper().strip()
        if maintainers_set:
            if author.lower() not in maintainers_set:
                continue
        elif association not in trusted_associations:
            continue

        body = _extract_human_comment_text(str(comment.get("body", "")))
        for pattern in approval_patterns:
            match = pattern.search(body)
            if match is None:
                continue
            if any(negative.search(body) for negative in NEGATED_APPROVAL_PATTERNS):
                continue
            if not _has_closure_context(body, match.span()):
                continue
            start = max(0, match.start() - 24)
            end = min(len(body), match.end() + 24)
            snippet = body[start:end].replace("\n", " ").strip()
            evidence.append(
                ApprovalEvidence(
                    author=author,
                    url=(
                        comment.get("html_url")
                        if isinstance(comment.get("html_url"), str)
                        else None
                    ),
                    association=association,
                    snippet=snippet,
                )
            )
            break

    return tuple(evidence)


def _has_closure_context(body: str, match_span: tuple[int, int]) -> bool:
    """Require approval language to be tied to closure/disposition intent."""

    window_start = max(0, match_span[0] - 120)
    window_end = min(len(body), match_span[1] + 120)
    window = body[window_start:window_end]
    return CLOSURE_CONTEXT_PATTERN.search(window) is not None


def _extract_human_comment_text(body: str) -> str:
    """Drop quoted and fenced content so approval checks only inspect direct comment text."""

    in_fence = False
    kept_lines: list[str] = []

    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        if FENCE_PATTERN.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.lstrip().startswith(">"):
            continue
        kept_lines.append(line)

    return "\n".join(kept_lines)


def build_disposition_report(
    *,
    issue_json: dict[str, object],
    comments_json: list[dict[str, object]],
    maintainers: tuple[str, ...],
    approval_regexes: tuple[str, ...],
) -> dict[str, object]:
    issue_state = str(issue_json.get("state", "")).lower()
    issue_number = issue_json.get("number")
    issue_url = issue_json.get("html_url")
    body = str(issue_json.get("body") or "")

    checkbox_summary = summarize_checkboxes(body)
    section_summary = summarize_gate_sections(body)
    compiled_regexes = tuple(re.compile(pattern, re.IGNORECASE) for pattern in approval_regexes)
    approvals = _collect_approval_evidence(
        comments_json,
        maintainers=maintainers,
        approval_patterns=compiled_regexes,
    )

    tasks_complete = section_summary.tasks.total > 0 and not section_summary.tasks.unchecked_items
    acceptance_complete = (
        section_summary.acceptance.total > 0 and not section_summary.acceptance.unchecked_items
    )
    maintainer_approved = len(approvals) > 0
    ready_to_close = tasks_complete and acceptance_complete and maintainer_approved
    issue_is_open = issue_state == "open"
    prematurely_closed = (not ready_to_close) and (not issue_is_open)

    report = {
        "issue": {
            "number": issue_number,
            "url": issue_url,
            "state": issue_state,
        },
        "summary": {
            "total_checkboxes": checkbox_summary.total,
            "checked_checkboxes": checkbox_summary.checked,
            "unchecked_checkboxes": checkbox_summary.total - checkbox_summary.checked,
            "tasks_checkboxes_total": section_summary.tasks.total,
            "tasks_checkboxes_checked": section_summary.tasks.checked,
            "tasks_complete": tasks_complete,
            "acceptance_checkboxes_total": section_summary.acceptance.total,
            "acceptance_checkboxes_checked": section_summary.acceptance.checked,
            "acceptance_complete": acceptance_complete,
            "approval_comments": len(approvals),
            "maintainer_approved": maintainer_approved,
            "ready_to_close": ready_to_close,
            "issue_open": issue_is_open,
            "prematurely_closed": prematurely_closed,
            "passing": not prematurely_closed,
        },
        "remaining_checkboxes": list(checkbox_summary.unchecked_items),
        "remaining_tasks": list(section_summary.tasks.unchecked_items),
        "remaining_acceptance": list(section_summary.acceptance.unchecked_items),
        "approvals": [
            {
                "author": item.author,
                "url": item.url,
                "association": item.association,
                "snippet": item.snippet,
            }
            for item in approvals
        ],
        "maintainers": list(maintainers),
        "approval_patterns": list(approval_regexes),
    }
    return report


def build_comment_report(report: dict[str, object]) -> str:
    issue = report["issue"]
    summary = report["summary"]

    lines = [
        "## LangGraph Issue Disposition Audit",
        "",
        f"- Issue: #{issue['number']} ({issue['url']})",
        f"- State: `{issue['state']}`",
        f"- Checkboxes complete: {summary['checked_checkboxes']}/{summary['total_checkboxes']}",
        (
            "- Tasks complete: "
            + f"{summary['tasks_checkboxes_checked']}/{summary['tasks_checkboxes_total']}"
        ),
        (
            "- Acceptance criteria complete: "
            + f"{summary['acceptance_checkboxes_checked']}/{summary['acceptance_checkboxes_total']}"
        ),
        f"- Maintainer approval comments: {summary['approval_comments']}",
        f"- Ready to close: {'YES' if summary['ready_to_close'] else 'NO'}",
        f"- Prematurely closed: {'YES' if summary['prematurely_closed'] else 'NO'}",
        "",
        "| Gate | Status |",
        "|---|---|",
        (
            "| Issue remains open until Tasks + Acceptance Criteria are complete + maintainer approval | "
            + ("PASS" if summary["passing"] else "FAIL")
            + " |"
        ),
    ]

    if report["remaining_tasks"]:
        lines.append("")
        lines.append("### Remaining tasks")
        for item in report["remaining_tasks"]:
            lines.append(f"- [ ] {item}")

    if report["remaining_acceptance"]:
        lines.append("")
        lines.append("### Remaining acceptance criteria")
        for item in report["remaining_acceptance"]:
            lines.append(f"- [ ] {item}")

    if report["remaining_checkboxes"]:
        lines.append("")
        lines.append("### Remaining checkboxes")
        for item in report["remaining_checkboxes"]:
            lines.append(f"- [ ] {item}")

    if report["approvals"]:
        lines.append("")
        lines.append("### Maintainer approval evidence")
        for approval in report["approvals"]:
            if approval["url"]:
                lines.append(
                    f"- {approval['author']} ({approval['association']}): "
                    + f"`{approval['snippet']}` ({approval['url']})"
                )
            else:
                lines.append(
                    f"- {approval['author']} ({approval['association']}): "
                    + f"`{approval['snippet']}`"
                )

    if not summary["passing"]:
        lines.extend(
            [
                "",
                "### Needs human",
                "Issue was closed before completion + maintainer approval gate was satisfied.",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def is_report_passing(report: dict[str, object]) -> bool:
    return bool(report["summary"]["passing"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", type=Path, required=True, help="Path to issue JSON payload.")
    parser.add_argument(
        "--comments", type=Path, required=True, help="Path to issue comments JSON payload."
    )
    parser.add_argument(
        "--maintainer",
        action="append",
        default=[],
        help="Maintainer GitHub login allowed to approve disposition. Repeatable.",
    )
    parser.add_argument(
        "--approval-pattern",
        action="append",
        default=[],
        help="Regex indicating approval language in a comment body. Repeatable.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "comment"),
        default="json",
        help="Output format.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    issue_json = _load_json(args.issue)
    comments_json = _load_json(args.comments)

    if not isinstance(issue_json, dict):
        raise ValueError("Issue payload must be a JSON object.")
    if not isinstance(comments_json, list):
        raise ValueError("Comments payload must be a JSON array.")

    report = build_disposition_report(
        issue_json=issue_json,
        comments_json=comments_json,
        maintainers=tuple(args.maintainer),
        approval_regexes=(
            tuple(args.approval_pattern) if args.approval_pattern else DEFAULT_APPROVAL_PATTERNS
        ),
    )

    if args.format == "comment":
        print(build_comment_report(report), end="")
    else:
        print(json.dumps(report, indent=2))

    return 0 if is_report_passing(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
