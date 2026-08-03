#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from score import EXPECTED, evaluate


def citation(path: str) -> dict[str, str]:
    return {"path": path, "locator": "controlling section or row"}


def valid_assessment() -> dict:
    requirements = []
    for requirement_id in EXPECTED["requirement_ids"]:
        paths = [
            group[0] for group in EXPECTED["required_citation_groups"][requirement_id]
        ]
        requirements.append(
            {
                "requirement_id": requirement_id,
                "status": EXPECTED["expected_statuses"][requirement_id],
                "buyer_requirement": (
                    f"The buyer's controlling requirement for {requirement_id} "
                    "is stated in the cited mandate."
                ),
                "seller_position": (
                    f"The seller's controlling position for {requirement_id} "
                    "is stated in the cited schedule."
                ),
                "analysis": (
                    f"The cited evidence supports the recorded "
                    f"{EXPECTED['expected_statuses'][requirement_id]} status "
                    "under the transaction snapshot."
                ),
                "citations": [citation(path) for path in paths],
            }
        )

    issues = []
    actions = []
    for index, requirement_id in enumerate(
        EXPECTED["material_requirement_ids"], start=1
    ):
        source_path = EXPECTED["required_citation_groups"][requirement_id][-1][0]
        issues.append(
            {
                "issue_id": f"ISS-{index:02d}",
                "title": f"Material gap for {requirement_id}",
                "severity": EXPECTED["minimum_severity"][requirement_id],
                "requirement_ids": [requirement_id],
                "finding": (
                    f"The current seller offer does not satisfy the controlling "
                    f"{requirement_id} requirement on the cited record."
                ),
                "required_resolution": (
                    f"Obtain a binding amendment that cures {requirement_id} "
                    "before the buyer signs."
                ),
                "citations": [citation(source_path)],
            }
        )
        actions.append(
            {
                "action_id": f"ACT-{index:02d}",
                "priority": "BEFORE_SIGNATURE",
                "owner": "Northstar procurement lead",
                "requirement_ids": [requirement_id],
                "action": (
                    f"Negotiate a binding cure for {requirement_id} in the "
                    "controlling seller schedules."
                ),
                "success_condition": (
                    f"Signed paper expressly satisfies {requirement_id}."
                ),
            }
        )

    return {
        "opportunity_id": EXPECTED["opportunity_id"],
        "snapshot_date": EXPECTED["snapshot_date"],
        "decision": EXPECTED["expected_decision"],
        "decision_rationale": (
            "The current offer misses material hard requirements, while the "
            "signed engineering note shows bounded technical cure paths that "
            "make a focused negotiation preferable to rejection."
        ),
        "requirements": requirements,
        "material_issues": issues,
        "next_actions": actions,
    }


def valid_brief() -> str:
    lines = [
        "# Project Northlink Commercial Fit Brief",
        "",
        "## Recommendation",
        "",
        f"**Decision: {EXPECTED['expected_decision']}**",
        "",
        (
            "The offer needs binding technical and commercial amendments before "
            "signature. The room supports a bounded negotiation rather than an "
            "unqualified proceed, pause, or rejection."
        ),
        (
            "The decisive record is 384 firm GPUs plus 128 contingent GPUs, "
            "against a 2026-10-15 deadline and a 2026-11-28 tranche date. "
            "The 64-node 8-GPU B200 cluster is in Helsinki with EEA residency. "
            "Its core is 2:1 rather than 1:1, and cooling covers 48 of 64 nodes. "
            "The 99.95% SLA exceeds 99.9%. Mandatory USD 2.62 hourly charges "
            "plus USD 180,000 produce about USD 2.66013 versus a USD 2.65 cap. "
            "The 24-month paper must become 12-month paper; the 20% "
            "non-refundable deposit must become no more than one month; and "
            "the 60 days delay exit must become 14 days."
        ),
        "",
        "## Requirement Reconciliation",
        "",
    ]
    for requirement_id in EXPECTED["requirement_ids"]:
        source = EXPECTED["required_citation_groups"][requirement_id][-1][0]
        lines.append(
            f"- {requirement_id}: {EXPECTED['expected_statuses'][requirement_id]} "
            f"under `{source}` and the controlling buyer requirement."
        )
    lines.extend(
        [
            "",
            "## Material Issues",
            "",
            (
                "Capacity, delivery, fabric, cooling, price, term, deposit, and "
                "delay remedies all require signed cures. The current evidence "
                "cannot be replaced by the non-binding sales email."
            ),
            "",
            "## Required Next Actions",
            "",
            (
                "Northstar should negotiate a binding capacity reservation, "
                "accelerated commissioning, 1:1 fabric, capped all-in economics, "
                "a 12-month term, a protected deposit, and a 14-day delay exit."
            ),
            "",
            (
                "The team should validate the resulting amendment against "
                "`matter/01_buyer_mandate.md`, "
                "`matter/02_buyer_technical_requirements.md`, "
                "`matter/04_capacity_schedule.csv`, "
                "`matter/06_network_design.md`, "
                "`matter/07_cooling_commissioning.md`, "
                "`matter/08_price_schedule.csv`, and "
                "`matter/09_draft_order_form.md`, plus "
                "`matter/13_inventory_reservation_note.md`."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


class Workspace:
    def __enter__(self) -> tuple[Path, dict]:
        self._temporary = tempfile.TemporaryDirectory()
        root = Path(self._temporary.name)
        output = root / "output"
        output.mkdir()
        payload = valid_assessment()
        (output / "fit-assessment.json").write_text(
            json.dumps(payload, indent=2) + "\n"
        )
        (output / "deal-brief.md").write_text(valid_brief())
        return root, payload

    def __exit__(self, *_args: object) -> None:
        self._temporary.cleanup()


def write_assessment(root: Path, payload: dict) -> None:
    (root / "output" / "fit-assessment.json").write_text(
        json.dumps(payload, indent=2) + "\n"
    )


def write_brief(root: Path, brief: str) -> None:
    (root / "output" / "deal-brief.md").write_text(brief)


class ScorerTests(unittest.TestCase):
    def test_reference_work_product_all_passes(self) -> None:
        with Workspace() as (root, _):
            rewards, details = evaluate(root)
        self.assertEqual(rewards["reward"], 1.0, details["failed_criteria"])
        self.assertEqual(rewards["criterion_pass_rate"], 1.0)
        self.assertEqual(rewards["verifier_integrity"], 1)

    def test_requirement_order_is_not_semantic(self) -> None:
        with Workspace() as (root, payload):
            payload["requirements"].reverse()
            write_assessment(root, payload)
            rewards, details = evaluate(root)
        self.assertEqual(rewards["reward"], 1.0, details["failed_criteria"])

    def test_wrong_decision_fails_strict_reward(self) -> None:
        with Workspace() as (root, payload):
            payload["decision"] = "PROCEED"
            write_assessment(root, payload)
            rewards, details = evaluate(root)
        self.assertEqual(rewards["reward"], 0.0)
        self.assertIn("judgment:decision", details["failed_criteria"])

    def test_wrong_requirement_status_fails(self) -> None:
        with Workspace() as (root, payload):
            payload["requirements"][0]["status"] = "MEETS"
            write_assessment(root, payload)
            rewards, details = evaluate(root)
        self.assertEqual(rewards["reward"], 0.0)
        self.assertIn("requirements:gpu_quantity:status", details["failed_criteria"])

    def test_missing_decisive_fact_fails(self) -> None:
        with Workspace() as (root, payload):
            write_assessment(root, payload)
            brief_path = root / "output" / "deal-brief.md"
            brief_path.write_text(valid_brief().replace("2026-11-28", "a later date"))
            rewards, details = evaluate(root)
        self.assertEqual(rewards["reward"], 0.0)
        self.assertIn("facts:capacity_and_delivery", details["failed_criteria"])

    def test_missing_controlling_citation_fails(self) -> None:
        with Workspace() as (root, payload):
            payload["requirements"][4]["citations"] = [
                citation("matter/02_buyer_technical_requirements.md")
            ]
            write_assessment(root, payload)
            rewards, details = evaluate(root)
        self.assertEqual(rewards["reward"], 0.0)
        self.assertIn(
            "requirements:network_fabric:evidence", details["failed_criteria"]
        )

    def test_unknown_citation_fails_contract(self) -> None:
        with Workspace() as (root, payload):
            payload["requirements"][0]["citations"][0]["path"] = (
                "matter/not-in-the-room.md"
            )
            write_assessment(root, payload)
            rewards, details = evaluate(root)
        self.assertEqual(rewards["reward"], 0.0)
        self.assertIn("format:requirements_contract", details["failed_criteria"])

    def test_omitted_material_issue_fails(self) -> None:
        with Workspace() as (root, payload):
            payload["material_issues"] = [
                issue
                for issue in payload["material_issues"]
                if "network_fabric" not in issue["requirement_ids"]
            ]
            write_assessment(root, payload)
            rewards, details = evaluate(root)
        self.assertEqual(rewards["reward"], 0.0)
        self.assertIn("judgment:material_issue_coverage", details["failed_criteria"])

    def test_low_severity_material_issue_fails(self) -> None:
        with Workspace() as (root, payload):
            payload["material_issues"][0]["severity"] = "LOW"
            write_assessment(root, payload)
            rewards, details = evaluate(root)
        self.assertEqual(rewards["reward"], 0.0)
        self.assertIn("judgment:severity:gpu_quantity", details["failed_criteria"])

    def test_omitted_next_action_fails(self) -> None:
        with Workspace() as (root, payload):
            payload["next_actions"] = [
                action
                for action in payload["next_actions"]
                if "delay_termination" not in action["requirement_ids"]
            ]
            write_assessment(root, payload)
            rewards, details = evaluate(root)
        self.assertEqual(rewards["reward"], 0.0)
        self.assertIn("actionability:material_coverage", details["failed_criteria"])

    def test_next_action_may_preserve_satisfied_requirement(self) -> None:
        with Workspace() as (root, payload):
            payload["next_actions"][0]["requirement_ids"].append("sla")
            write_assessment(root, payload)
            rewards, details = evaluate(root)
        self.assertEqual(rewards["reward"], 1.0, details["failed_criteria"])

    def test_unknown_next_action_requirement_fails_contract(self) -> None:
        with Workspace() as (root, payload):
            payload["next_actions"][0]["requirement_ids"].append("unknown")
            write_assessment(root, payload)
            rewards, details = evaluate(root)
        self.assertEqual(rewards["reward"], 0.0)
        self.assertIn("format:next_actions_contract", details["failed_criteria"])

    def test_brief_accepts_explicit_decision_without_reference_formatting(self) -> None:
        with Workspace() as (root, _):
            write_brief(
                root,
                valid_brief().replace("**Decision: NEGOTIATE**", "**NEGOTIATE.**"),
            )
            rewards, details = evaluate(root)
        self.assertEqual(rewards["reward"], 1.0, details["failed_criteria"])

    def test_brief_rejects_wrong_explicit_decision(self) -> None:
        with Workspace() as (root, _):
            write_brief(
                root,
                valid_brief().replace("**Decision: NEGOTIATE**", "**PROCEED.**"),
            )
            rewards, details = evaluate(root)
        self.assertEqual(rewards["reward"], 0.0)
        self.assertIn("brief:decision_consistency", details["failed_criteria"])

    def test_brief_must_match_structured_statuses(self) -> None:
        with Workspace() as (root, _):
            brief_path = root / "output" / "deal-brief.md"
            brief_path.write_text(
                valid_brief().replace(
                    "network_fabric: DOES_NOT_MEET",
                    "network_fabric: MEETS",
                )
            )
            rewards, details = evaluate(root)
        self.assertEqual(rewards["reward"], 0.0)
        self.assertIn("brief:requirement_consistency", details["failed_criteria"])

    def test_missing_outputs_fail_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rewards, details = evaluate(root)
        self.assertEqual(rewards["reward"], 0.0)
        self.assertEqual(rewards["verifier_integrity"], 1)
        self.assertTrue(details["notes"])

    def test_extra_top_level_field_fails(self) -> None:
        with Workspace() as (root, payload):
            payload["hidden_guess"] = "anything"
            write_assessment(root, payload)
            rewards, details = evaluate(root)
        self.assertEqual(rewards["reward"], 0.0)
        self.assertIn("format:top_level_fields", details["failed_criteria"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
