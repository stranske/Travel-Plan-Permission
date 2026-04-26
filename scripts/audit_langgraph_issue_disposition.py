"""Audit issue disposition gating for LangGraph follow-up closure criteria."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

CHECKBOX_PATTERN = re.compile(r"^\s*[-*]\s*\[(?P<mark>[ xX])\]\s*(?P<text>.+?)\s*$")
DEFAULT_APPROVAL_PATTERNS = (r"\bapprove(?:d)?\b", r"\blgtm\b")


@dataclass(frozen=True)
class CheckboxSummary:
    total: int
    checked: int
    unchecked_items: tuple[str, ...]


@dataclass(frozen=True)
class ApprovalEvidence:
    author: str
    url: str | None
    snippet: str


def _load_json(path: Path) -> object:
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def summarize_checkboxes(issue_body: str) -> CheckboxSummary:
    checked = 0
    unchecked_items: list[str] = []
    total = 0

    for line in issue_body.splitlines():
        match = CHECKBOX_PATTERN.match(line)
        if match is None:
            continue
        total += 1
        if match.group("mark").lower() == "x":
            checked += 1
        else:
            unchecked_items.append(match.group("text").strip())

    return CheckboxSummary(total=total, checked=checked, unchecked_items=tuple(unchecked_items))


def _collect_approval_evidence(
    comments: list[dict[str, object]],
    *,
    maintainers: tuple[str, ...],
    approval_patterns: tuple[re.Pattern[str], ...],
) -> tuple[ApprovalEvidence, ...]:
    maintainers_set = {name.lower() for name in maintainers}
    evidence: list[ApprovalEvidence] = []

    for comment in comments:
        user = comment.get("user")
        if not isinstance(user, dict):
            continue
        author = str(user.get("login", "")).strip()
        if not author:
            continue
        if maintainers_set and author.lower() not in maintainers_set:
            continue

        body = str(comment.get("body", ""))
        for pattern in approval_patterns:
            match = pattern.search(body)
            if match is None:
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
                    snippet=snippet,
                )
            )
            break

    return tuple(evidence)


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
    compiled_regexes = tuple(re.compile(pattern, re.IGNORECASE) for pattern in approval_regexes)
    approvals = _collect_approval_evidence(
        comments_json,
        maintainers=maintainers,
        approval_patterns=compiled_regexes,
    )

    tasks_complete = checkbox_summary.total > 0 and not checkbox_summary.unchecked_items
    maintainer_approved = len(approvals) > 0
    ready_to_close = tasks_complete and maintainer_approved
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
            "approval_comments": len(approvals),
            "maintainer_approved": maintainer_approved,
            "ready_to_close": ready_to_close,
            "issue_open": issue_is_open,
            "prematurely_closed": prematurely_closed,
            "passing": not prematurely_closed,
        },
        "remaining_checkboxes": list(checkbox_summary.unchecked_items),
        "approvals": [
            {
                "author": item.author,
                "url": item.url,
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
        f"- Maintainer approval comments: {summary['approval_comments']}",
        f"- Ready to close: {'YES' if summary['ready_to_close'] else 'NO'}",
        f"- Prematurely closed: {'YES' if summary['prematurely_closed'] else 'NO'}",
        "",
        "| Gate | Status |",
        "|---|---|",
        (
            "| Issue remains open until all checkboxes complete + maintainer approval | "
            + ("PASS" if summary["passing"] else "FAIL")
            + " |"
        ),
    ]

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
                lines.append(f"- {approval['author']}: `{approval['snippet']}` ({approval['url']})")
            else:
                lines.append(f"- {approval['author']}: `{approval['snippet']}`")

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
