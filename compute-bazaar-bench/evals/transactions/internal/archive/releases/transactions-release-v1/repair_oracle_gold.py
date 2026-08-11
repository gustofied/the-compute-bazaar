from __future__ import annotations

import os
from pathlib import Path
from zipfile import ZipFile


REPO_ROOT = Path(__file__).resolve().parents[5]


def patch_docx(
    source_path: Path,
    target_path: Path,
    replacements: list[tuple[str, str]],
) -> None:
    with ZipFile(source_path) as source:
        infos = source.infolist()
        comment = source.comment
        members = {info.filename: source.read(info.filename) for info in infos}

    document = members["word/document.xml"]
    for old, new in replacements:
        old_bytes = old.encode("utf-8")
        if document.count(old_bytes) != 1:
            raise RuntimeError(f"expected one occurrence in {source_path}: {old!r}")
        document = document.replace(old_bytes, new.encode("utf-8"), 1)
    members["word/document.xml"] = document

    temporary = target_path.with_suffix(".docx.tmp")
    with ZipFile(temporary, "w") as target:
        target.comment = comment
        for info in infos:
            target.writestr(info, members[info.filename])
    os.replace(temporary, target_path)


def main() -> None:
    transactions = REPO_ROOT / "compute-bazaar-bench/evals/transactions"
    archive = transactions / "internal/archive/oracle-gold-v1-failed-001"
    patch_docx(
        archive / "normalize-buyer-mandate/buyer-mandate-brief.docx",
        transactions / "normalize-buyer-mandate/solution/buyer-mandate-brief.docx",
        [
            (
                "Current SOC 2 Type II; customer-managed encryption keys;",
                "Current SOC 2 Type II report; customer-managed encryption keys;",
            ),
            (
                "Base-term calculation uses the staged ramp and an end boundary of July 15, 2028:",
                "For calculation only, assume the first tranche starts service on January 15, 2027 inclusive and the 18-month base term ends on July 15, 2028 exclusive:",
            ),
            (
                "Any power, implementation, or other pass-through must be tested against the $3.35 all-in cap; egress pricing remains unresolved.",
                "Implementation charges were not discussed, and egress pricing remains unresolved. Any power or other operating pass-through must stay within the $3.35 all-in cap.",
            ),
        ],
    )
    patch_docx(
        archive
        / "draft-capacity-data-room-population-plan/capacity-data-room-population-plan.docx",
        transactions
        / (
            "draft-capacity-data-room-population-plan/solution/"
            "capacity-data-room-population-plan.docx"
        ),
        [
            (
                "Partial - easement update missing",
                "Collect current title, survey, easement, and amendment set",
            ),
            (
                "Staffing, monitoring and maintenance",
                "Operating procedures, staffing, monitoring and maintenance",
            ),
            (
                "Staffing plan draft",
                "Collect operating procedures, staffing, monitoring, and maintenance policy",
            ),
            (
                "Acceptance and benchmark plan",
                "Proposed service levels, acceptance, and benchmark plan",
            ),
            (
                "NCCL reference threshold open",
                "Collect proposed service levels and acceptance criteria",
            ),
            (
                "Current drafts ready",
                "Term sheet logged; collect offer, price build, and draft capacity agreement",
            ),
            (
                "Funding plan and liquidity",
                "Funding plan, liquidity, and proposed parent-guarantee credit support",
            ),
            (
                "Update after lender consent",
                "Collect proposed parent guarantee; update after lender consent",
            ),
            (
                "Every upload must carry a document date, version or execution status, relevant entity, DDRL mapping, owner, sensitivity label, and review status.",
                "Record each upload's date, version or execution status, entity, DDRL mapping, owner, sensitivity, review status, and every redaction and basis.",
            ),
            (
                "Formation, good standing, ownership and beneficial owners",
                "Formation, good standing, ownership, beneficial owners, and KYC materials",
            ),
            (
                "Permit matrix in review",
                "Collect requested permits; current status is not evidenced",
            ),
            (
                "Current as of Aug. 9",
                "Collect current design set, construction schedule, and punch list",
            ),
            (
                "Network topology, port map and oversubscription",
                "Network topology, port map, oversubscription, external capacity and redundancy",
            ),
            (
                "Cooling design basis and capacity model",
                "Cooling design, capacity, water/coolant dependencies and operating limits",
            ),
            (
                "Claims, compliance and regulatory materials",
                "Litigation, claims, regulatory correspondence, sanctions, export controls, environmental matters and compliance",
            ),
            (
                "Missing, stale, or partially responsive evidence remains open with an owner and next action.",
                "Keep missing, stale, or partial evidence open with an owner and next action.",
            ),
            (
                "No team member should infer that a requested document exists merely because it appears in this plan.",
                "A plan entry never proves that a document exists.",
            ),
        ],
    )


if __name__ == "__main__":
    main()
