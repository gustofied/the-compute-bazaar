#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any


WORKSPACE = Path("/workspace")
OUTPUT_DIR = WORKSPACE / "output"
ASSESSMENT_PATH = OUTPUT_DIR / "fit-assessment.json"
BRIEF_PATH = OUTPUT_DIR / "deal-brief.md"
EXPECTED_PATH = Path(__file__).with_name("expected.json")
REWARD_PATH = Path("/logs/verifier/reward.json")
DETAILS_PATH = Path("/logs/verifier/details.json")

EXPECTED: dict[str, Any] = json.loads(EXPECTED_PATH.read_text())
MAX_JSON_BYTES = 1_000_000
MAX_BRIEF_BYTES = 200_000
SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
DECISIONS = {"PROCEED", "NEGOTIATE", "PAUSE", "REJECT"}
STATUSES = {"MEETS", "PARTIAL", "DOES_NOT_MEET", "UNVERIFIED"}
PRIORITIES = {"IMMEDIATE", "BEFORE_SIGNATURE", "BEFORE_DEPLOYMENT"}

TOP_LEVEL_FIELDS = {
    "opportunity_id",
    "snapshot_date",
    "decision",
    "decision_rationale",
    "requirements",
    "material_issues",
    "next_actions",
}
REQUIREMENT_FIELDS = {
    "requirement_id",
    "status",
    "buyer_requirement",
    "seller_position",
    "analysis",
    "citations",
}
ISSUE_FIELDS = {
    "issue_id",
    "title",
    "severity",
    "requirement_ids",
    "finding",
    "required_resolution",
    "citations",
}
ACTION_FIELDS = {
    "action_id",
    "priority",
    "owner",
    "requirement_ids",
    "action",
    "success_condition",
}
CITATION_FIELDS = {"path", "locator"}


def _substantive(value: object, minimum: int = 20) -> bool:
    return isinstance(value, str) and minimum <= len(value.strip()) <= 10_000


def _read_regular_text(path: Path, max_bytes: int) -> tuple[str | None, str | None]:
    try:
        if path.is_symlink() or not path.is_file():
            return None, f"{path.name} is missing or is not a regular file"
        size = path.stat().st_size
        if size <= 0 or size > max_bytes:
            return None, f"{path.name} has invalid size {size}"
        return path.read_text(), None
    except (OSError, UnicodeError) as exc:
        return None, f"{path.name} is unreadable: {type(exc).__name__}"


def _load_assessment(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    text, error = _read_regular_text(path, MAX_JSON_BYTES)
    if error:
        return None, [error]
    try:
        value = json.loads(text or "")
    except json.JSONDecodeError as exc:
        return None, [f"fit-assessment.json is invalid JSON: {exc.msg}"]
    if not isinstance(value, dict):
        return None, ["fit-assessment.json is not a JSON object"]
    return value, []


def _citation_paths(value: object) -> tuple[set[str], bool]:
    known = set(EXPECTED["known_source_paths"])
    if not isinstance(value, list) or not value:
        return set(), False
    paths: set[str] = set()
    valid = True
    for citation in value:
        if not isinstance(citation, dict) or set(citation) != CITATION_FIELDS:
            valid = False
            continue
        path = citation.get("path")
        locator = citation.get("locator")
        if not isinstance(path, str) or path not in known:
            valid = False
        else:
            paths.add(path)
        if not isinstance(locator, str) or not locator.strip() or len(locator) > 500:
            valid = False
    return paths, valid


def _unique_strings(values: object, allowed: set[str]) -> tuple[set[str], bool]:
    if not isinstance(values, list) or not values:
        return set(), False
    if any(not isinstance(value, str) or value not in allowed for value in values):
        return set(), False
    unique = set(values)
    return unique, len(unique) == len(values)


def _groups_satisfied(paths: set[str], groups: list[list[str]]) -> bool:
    return all(paths.intersection(group) for group in groups)


def _recommendation_decision(brief: str) -> str | None:
    heading = "## Recommendation"
    if heading not in brief:
        return None
    section = brief.split(heading, 1)[1].split("\n## ", 1)[0]
    for line in section.splitlines():
        if not line.strip():
            continue
        decisions = [
            decision
            for decision in DECISIONS
            if re.search(rf"\b{decision}\b", line, flags=re.IGNORECASE)
        ]
        return decisions[0] if len(decisions) == 1 else None
    return None


def _dimension(criteria: dict[str, bool], prefixes: tuple[str, ...]) -> float:
    values = [
        passed
        for name, passed in criteria.items()
        if any(name.startswith(prefix) for prefix in prefixes)
    ]
    return sum(values) / len(values) if values else 0.0


def evaluate(
    workspace: Path = WORKSPACE,
) -> tuple[dict[str, float | int], dict[str, Any]]:
    assessment_path = workspace / "output" / "fit-assessment.json"
    brief_path = workspace / "output" / "deal-brief.md"
    assessment, load_errors = _load_assessment(assessment_path)
    brief, brief_error = _read_regular_text(brief_path, MAX_BRIEF_BYTES)
    criteria: dict[str, bool] = {}
    notes: list[str] = list(load_errors)
    if brief_error:
        notes.append(brief_error)

    criteria["format:assessment_regular_json"] = assessment is not None
    criteria["format:brief_regular_text"] = brief is not None

    requirement_ids = set(EXPECTED["requirement_ids"])
    material_ids = set(EXPECTED["material_requirement_ids"])
    requirements_by_id: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []

    if assessment is None:
        assessment = {}

    criteria["format:top_level_fields"] = set(assessment) == TOP_LEVEL_FIELDS
    criteria["format:opportunity_id_type"] = isinstance(
        assessment.get("opportunity_id"), str
    )
    criteria["format:snapshot_date_type"] = isinstance(
        assessment.get("snapshot_date"), str
    )
    criteria["format:decision_enum"] = assessment.get("decision") in DECISIONS
    criteria["format:decision_rationale"] = _substantive(
        assessment.get("decision_rationale"), 60
    )

    raw_requirements = assessment.get("requirements")
    requirement_format_valid = isinstance(raw_requirements, list)
    requirement_order: list[str] = []
    if isinstance(raw_requirements, list):
        for entry in raw_requirements:
            entry_valid = isinstance(entry, dict) and set(entry) == REQUIREMENT_FIELDS
            if not entry_valid:
                requirement_format_valid = False
                continue
            requirement_id = entry.get("requirement_id")
            status = entry.get("status")
            paths, citations_valid = _citation_paths(entry.get("citations"))
            entry_valid = (
                isinstance(requirement_id, str)
                and requirement_id in requirement_ids
                and status in STATUSES
                and _substantive(entry.get("buyer_requirement"))
                and _substantive(entry.get("seller_position"))
                and _substantive(entry.get("analysis"))
                and citations_valid
            )
            requirement_format_valid = requirement_format_valid and entry_valid
            if (
                not isinstance(requirement_id, str)
                or requirement_id not in requirement_ids
            ):
                continue
            requirement_order.append(requirement_id)
            if requirement_id in requirements_by_id:
                requirement_format_valid = False
            else:
                copied = dict(entry)
                copied["_citation_paths"] = paths
                requirements_by_id[requirement_id] = copied
    criteria["format:requirements_contract"] = requirement_format_valid
    criteria["format:requirements_exact_set"] = set(
        requirement_order
    ) == requirement_ids and len(requirement_order) == len(requirement_ids)

    raw_issues = assessment.get("material_issues")
    issue_format_valid = isinstance(raw_issues, list) and bool(raw_issues)
    issue_ids: set[str] = set()
    if isinstance(raw_issues, list):
        for entry in raw_issues:
            entry_valid = isinstance(entry, dict) and set(entry) == ISSUE_FIELDS
            if not entry_valid:
                issue_format_valid = False
                continue
            issue_id = entry.get("issue_id")
            linked_ids, links_valid = _unique_strings(
                entry.get("requirement_ids"), requirement_ids
            )
            paths, citations_valid = _citation_paths(entry.get("citations"))
            entry_valid = (
                isinstance(issue_id, str)
                and 1 <= len(issue_id.strip()) <= 100
                and issue_id not in issue_ids
                and _substantive(entry.get("title"), 5)
                and entry.get("severity") in SEVERITY_RANK
                and links_valid
                and _substantive(entry.get("finding"), 40)
                and _substantive(entry.get("required_resolution"), 30)
                and citations_valid
            )
            issue_format_valid = issue_format_valid and entry_valid
            if isinstance(issue_id, str):
                issue_ids.add(issue_id)
            copied = dict(entry)
            copied["_requirement_ids"] = linked_ids
            copied["_citation_paths"] = paths
            issues.append(copied)
    criteria["format:material_issues_contract"] = issue_format_valid

    raw_actions = assessment.get("next_actions")
    action_format_valid = isinstance(raw_actions, list) and bool(raw_actions)
    action_ids: set[str] = set()
    if isinstance(raw_actions, list):
        for entry in raw_actions:
            entry_valid = isinstance(entry, dict) and set(entry) == ACTION_FIELDS
            if not entry_valid:
                action_format_valid = False
                continue
            action_id = entry.get("action_id")
            linked_ids, links_valid = _unique_strings(
                entry.get("requirement_ids"), requirement_ids
            )
            entry_valid = (
                isinstance(action_id, str)
                and 1 <= len(action_id.strip()) <= 100
                and action_id not in action_ids
                and entry.get("priority") in PRIORITIES
                and _substantive(entry.get("owner"), 3)
                and links_valid
                and _substantive(entry.get("action"), 30)
                and _substantive(entry.get("success_condition"), 20)
            )
            action_format_valid = action_format_valid and entry_valid
            if isinstance(action_id, str):
                action_ids.add(action_id)
            copied = dict(entry)
            copied["_requirement_ids"] = linked_ids
            actions.append(copied)
    criteria["format:next_actions_contract"] = action_format_valid

    criteria["identity:opportunity"] = (
        assessment.get("opportunity_id") == EXPECTED["opportunity_id"]
    )
    criteria["identity:snapshot"] = (
        assessment.get("snapshot_date") == EXPECTED["snapshot_date"]
    )
    criteria["judgment:decision"] = (
        assessment.get("decision") == EXPECTED["expected_decision"]
    )

    for requirement_id in EXPECTED["requirement_ids"]:
        entry = requirements_by_id.get(requirement_id)
        criteria[f"requirements:{requirement_id}:present"] = entry is not None
        criteria[f"requirements:{requirement_id}:status"] = bool(
            entry
            and entry.get("status") == EXPECTED["expected_statuses"][requirement_id]
        )
        criteria[f"requirements:{requirement_id}:evidence"] = bool(
            entry
            and _groups_satisfied(
                entry.get("_citation_paths", set()),
                EXPECTED["required_citation_groups"][requirement_id],
            )
        )

    combined_work_product = (
        json.dumps(assessment, ensure_ascii=True, sort_keys=True) + "\n" + (brief or "")
    )
    for fact_name, patterns in EXPECTED["required_fact_patterns"].items():
        criteria[f"facts:{fact_name}"] = all(
            re.search(pattern, combined_work_product, flags=re.IGNORECASE) is not None
            for pattern in patterns
        )

    issue_coverage: set[str] = set()
    issue_max_severity = {requirement_id: 0 for requirement_id in material_ids}
    for issue in issues:
        linked_ids = issue.get("_requirement_ids", set())
        if not isinstance(linked_ids, set):
            continue
        issue_coverage.update(linked_ids)
        rank = SEVERITY_RANK.get(issue.get("severity"), 0)
        for requirement_id in linked_ids.intersection(material_ids):
            issue_max_severity[requirement_id] = max(
                issue_max_severity[requirement_id], rank
            )

    criteria["judgment:material_issue_coverage"] = material_ids.issubset(issue_coverage)
    for requirement_id in EXPECTED["material_requirement_ids"]:
        minimum = SEVERITY_RANK[EXPECTED["minimum_severity"][requirement_id]]
        criteria[f"judgment:severity:{requirement_id}"] = (
            issue_max_severity[requirement_id] >= minimum
        )

    action_coverage: set[str] = set()
    for action in actions:
        linked_ids = action.get("_requirement_ids", set())
        if isinstance(linked_ids, set):
            action_coverage.update(linked_ids)
    criteria["actionability:material_coverage"] = material_ids.issubset(action_coverage)

    if brief is None:
        brief = ""
    criteria["brief:substantive_length"] = 800 <= len(brief.strip()) <= MAX_BRIEF_BYTES
    criteria["brief:required_headings"] = all(
        heading in brief for heading in EXPECTED["brief_headings"]
    )
    criteria["brief:decision_consistency"] = (
        _recommendation_decision(brief) == EXPECTED["expected_decision"]
    )
    criteria["brief:requirement_consistency"] = all(
        re.search(
            rf"\b{re.escape(requirement_id)}\b[^\n]{{0,180}}\b"
            rf"{re.escape(EXPECTED['expected_statuses'][requirement_id])}\b",
            brief,
        )
        for requirement_id in EXPECTED["requirement_ids"]
    )
    brief_sources = set(re.findall(r"matter/[A-Za-z0-9_.-]+", brief)).intersection(
        EXPECTED["known_source_paths"]
    )
    criteria["brief:material_evidence"] = set(
        EXPECTED["required_brief_sources"]
    ).issubset(brief_sources)

    criterion_count = len(criteria)
    passed_count = sum(criteria.values())
    strict_pass = criterion_count > 0 and passed_count == criterion_count
    rewards: dict[str, float | int] = {
        "reward": float(strict_pass),
        "all_pass": int(strict_pass),
        "criterion_pass_rate": passed_count / criterion_count,
        "format": _dimension(criteria, ("format:", "identity:")),
        "factual_reconciliation": _dimension(criteria, ("requirements:", "facts:")),
        "judgment": _dimension(criteria, ("judgment:",)),
        "actionability": _dimension(criteria, ("actionability:",)),
        "work_product": _dimension(criteria, ("brief:",)),
        "verifier_integrity": 1,
    }
    details = {
        "task_id": EXPECTED["task_id"],
        "scorer_version": EXPECTED["scorer_version"],
        "criteria_total": criterion_count,
        "criteria_passed": passed_count,
        "failed_criteria": [name for name, passed in criteria.items() if not passed],
        "criteria": criteria,
        "notes": notes,
        "brief_sources": sorted(brief_sources),
    }
    return rewards, details


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> None:
    rewards, details = evaluate()
    for key, value in rewards.items():
        if isinstance(value, float) and not math.isfinite(value):
            raise RuntimeError(f"non-finite reward metric: {key}")
    _write_json(REWARD_PATH, rewards)
    _write_json(DETAILS_PATH, details)


if __name__ == "__main__":
    main()
