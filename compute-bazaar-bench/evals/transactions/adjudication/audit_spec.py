from __future__ import annotations

from typing import Any, Iterable


def criterion_ids(*parts: int | tuple[int, int]) -> list[str]:
    values: list[int] = []
    for part in parts:
        if isinstance(part, tuple):
            values.extend(range(part[0], part[1] + 1))
        else:
            values.append(part)
    return [f"C-{value:03d}" for value in values]


def refs(file: str, *locations: str) -> list[dict[str, str]]:
    return [{"file": file, "location": location} for location in locations]


def group(
    ids: Iterable[str],
    evidence: list[dict[str, str]],
    note: str,
    *,
    flags: Iterable[str] = (),
    disposition: str = "unchanged",
    derivation: str | None = None,
    evidence_scope: str = "cited_excerpts",
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "ids": list(ids),
        "evidence": evidence,
        "audit_note": note,
        "v1_flags": list(flags),
        "v2_disposition": disposition,
        "evidence_scope": evidence_scope,
    }
    if derivation:
        value["derivation"] = derivation
    return value


NORMALIZE_GROUPS = [
    group(
        criterion_ids(1),
        refs("buyer-compute-intake.docx", "T01-R01-C02"),
        "The intake identifies the opportunity.",
    ),
    group(
        criterion_ids(2),
        refs(
            "buyer-compute-intake.docx",
            "T01-R02-C02",
            "T01-R03-C02",
        ),
        "The intake identifies both buyer and mandate owner.",
    ),
    group(
        criterion_ids(3),
        refs("procurement-follow-up.eml", "L003", "L013")
        + refs("workload-requirements.docx", "T01-R03-C02"),
        "The dated follow-up states its conflict priority and preserves the August 4 engineering requirements.",
        flags=("summary_sensitive",),
    ),
    group(
        criterion_ids(4, 5),
        refs("procurement-follow-up.eml", "L005"),
        "The follow-up separates firm and optional capacity.",
    ),
    group(
        criterion_ids(6, 7, 8),
        refs(
            "workload-requirements.docx",
            "T03-R02-C02",
            "T03-R03-C02",
            "T03-R04-C02",
        )
        + refs("procurement-follow-up.eml", "L005", "L013"),
        "The engineering table and follow-up establish node count, dedicated configuration, and no fractional service.",
    ),
    group(
        criterion_ids(9, 10),
        refs("buyer-compute-intake.docx", "P009")
        + refs("procurement-follow-up.eml", "L007"),
        "The later ramp expressly supersedes the intake delivery date.",
    ),
    group(
        criterion_ids(11, 12, 13),
        refs("buyer-compute-intake.docx", "P010")
        + refs("procurement-follow-up.eml", "L007"),
        "The follow-up replaces the 12-month term with an 18-month term and a six-month option.",
    ),
    group(
        criterion_ids(14, 15),
        refs("buyer-compute-intake.docx", "P011")
        + refs("procurement-follow-up.eml", "L011"),
        "The documents distinguish acceptable regions, US-only operation, and the Virginia preference.",
    ),
    group(
        criterion_ids((16, 20)),
        refs("buyer-compute-intake.docx", "P013", "P014")
        + refs("procurement-follow-up.eml", "L009"),
        "The follow-up corrects target, cap, pass-through, and prepayment terms.",
    ),
    group(
        criterion_ids((21, 25)),
        refs(
            "workload-requirements.docx",
            "T04-R02-C02",
            "T04-R03-C02",
            "T04-R04-C02",
            "T04-R05-C02",
            "T04-R06-C02",
        ),
        "The engineering table supplies each fabric, ingress, and storage requirement.",
    ),
    group(
        criterion_ids(26),
        refs("workload-requirements.docx", "P006"),
        "The workload profile states the training, fine-tuning, and evaluation sequence.",
    ),
    group(
        criterion_ids((27, 29)),
        refs("workload-requirements.docx", "P012", "P013", "P014"),
        "The operating requirements state availability, maintenance, and notice thresholds.",
    ),
    group(
        criterion_ids((30, 32)),
        refs(
            "workload-requirements.docx",
            "P017",
            "P018",
            "P019",
            "P020",
        ),
        "The acceptance section states the burn-in, inventory, NCCL, and unresolved benchmark terms.",
    ),
    group(
        criterion_ids((33, 36), 38),
        refs(
            "workload-requirements.docx",
            "P022",
            "P023",
            "P024",
            "P025",
            "P026",
        ),
        "The security section supplies the control, residency, key, log, and physical-access requirements.",
    ),
    group(
        criterion_ids(37),
        refs("procurement-follow-up.eml", "L011"),
        "The follow-up expressly makes hourly renewable matching non-gating.",
    ),
    group(
        criterion_ids(39, 40),
        refs(
            "workload-requirements.docx",
            "T03-R05-C02",
            "T03-R06-C02",
            "T03-R06-C03",
        ),
        "The engineering table states CUDA compatibility and written-consent controls.",
    ),
    group(
        criterion_ids((41, 44)),
        refs("procurement-follow-up.eml", "L007", "L009"),
        "The reference figures are derived from the staged ramp, 18-month term, and stated rates, but V1 did not disclose that 'by' requires a service-date convention.",
        flags=("summary_sensitive", "ambiguous_without_assumption"),
        disposition="repaired_to_disclosed_calendar_convention",
        derivation=(
            "Reference convention only: January 15 inclusive and July 15, 2028 "
            "exclusive. 512 GPUs x 17 days x 24 hours plus 1,024 GPUs x 530 days x "
            "24 hours equals 13,234,176 GPU-hours; multiply the candidate's internally "
            "consistent hours by $3.10 and $3.35. Accept another disclosed reasonable "
            "interpretation of 'by'."
        ),
    ),
    group(
        criterion_ids(45),
        refs("procurement-follow-up.eml", "L009") + refs("instruction.md", "L001"),
        "The three-month cap is known, but a deposit-dollar estimate needs a billing-hours and price convention.",
        flags=("summary_sensitive", "ambiguous_without_assumption"),
    ),
    group(
        criterion_ids(46),
        refs("buyer-compute-intake.docx", "P016")
        + refs("procurement-follow-up.eml", "L009"),
        "The intake leaves egress and implementation charges undiscussed; the follow-up keeps egress open and constrains operating pass-throughs.",
        flags=("overly_broad",),
        disposition="reworded_to_exact_open_charges",
    ),
    group(
        criterion_ids(47),
        refs("procurement-follow-up.eml", "L007") + refs("instruction.md", "L001"),
        "The extension exists, but no price or exercise deadline is provided anywhere in the closed matter.",
        flags=("summary_sensitive",),
        evidence_scope="complete_normalized_matter",
    ),
    group(
        criterion_ids((48, 50)),
        refs("buyer-compute-intake.docx", "P026", "P027")
        + refs("procurement-follow-up.eml", "L013"),
        "The intake and follow-up identify counterparty, control, title, liens, and delivery evidence as open.",
    ),
    group(
        criterion_ids(51),
        refs("workload-requirements.docx", "T04-R02-C03", "T04-R03-C03")
        + refs("procurement-follow-up.eml", "L013"),
        "The engineering table identifies network evidence and the follow-up keeps proof open.",
    ),
    group(
        criterion_ids(52),
        refs("workload-requirements.docx", "P019", "P020")
        + refs("procurement-follow-up.eml", "L013"),
        "The NCCL reference and pass threshold remain expressly unresolved.",
    ),
    group(
        criterion_ids(53),
        refs("instruction.md", "L001")
        + refs("buyer-compute-intake.docx", "P025")
        + refs("procurement-follow-up.eml", "L013"),
        "This is a bounded anti-invention safeguard covering the named unresolved categories.",
        flags=("overly_broad", "summary_sensitive"),
        evidence_scope="complete_normalized_matter",
    ),
    group(
        criterion_ids(54),
        refs("instruction.md", "L001")
        + refs("procurement-follow-up.eml", "L003", "L013"),
        "The task requires a normalized and usable professional brief.",
        flags=("professional_judgment",),
    ),
    group(
        criterion_ids(55),
        refs(
            "buyer-compute-intake.docx",
            "T01-R04-C02",
            "T01-R05-C02",
        )
        + refs(
            "procurement-follow-up.eml",
            "HEADER-FROM",
            "HEADER-DATE",
            "L003",
            "L013",
        )
        + refs(
            "workload-requirements.docx",
            "T01-R01-C02",
            "T01-R03-C02",
        ),
        "The matter identifies and dates the initial intake, controlling follow-up, and preserved engineering requirements.",
        flags=("professional_judgment",),
    ),
    group(
        criterion_ids(56),
        refs("instruction.md", "L001")
        + refs("procurement-follow-up.eml", "L009", "L013")
        + refs("workload-requirements.docx", "P020"),
        "The closed matter contains open commercial, supplier, technical, and acceptance workstreams.",
        flags=("professional_judgment",),
    ),
]


def ddrl_row(row: int, *columns: str) -> list[dict[str, str]]:
    return refs(
        "buyer-capacity-ddrl.docx",
        *(f"T03-R{row:02d}-C{column}" for column in columns),
    )


DILIGENCE_GROUPS = [
    group(
        criterion_ids(1),
        refs("project-stakeholder-map.docx", "P002")
        + refs(
            "evidence-register.xlsx", "Evidence Register!A1", "Evidence Register!A2"
        ),
        "The stakeholder map and register identify the opportunity and campus.",
    ),
    group(
        criterion_ids(2),
        refs("instruction.md", "L001")
        + refs("buyer-capacity-ddrl.docx", "P010")
        + refs("operator-instructions.eml", "L015"),
        "The task is a population plan and both source documents forbid treating planned or missing evidence as complete.",
    ),
    group(
        criterion_ids(3),
        refs(
            "project-stakeholder-map.docx",
            "T03-R02-C01",
            "T03-R04-C01",
            "T03-R05-C01",
            "T04-R01-C01",
        )
        + refs("operator-instructions.eml", "L005"),
        "The entity map and operator instruction explain which affiliates hold delivery rights.",
        flags=("summary_sensitive",),
    ),
    group(
        criterion_ids(4),
        refs("instruction.md", "L001")
        + refs(
            "precedent-index-data-center.docx",
            "T03-R01-C01",
            "T03-R01-C02",
            "T03-R02-C01",
            "T03-R02-C02",
            "T03-R03-C01",
            "T03-R03-C02",
            "T03-R04-C01",
            "T03-R04-C02",
            "T03-R05-C01",
            "T03-R05-C02",
            "T03-R06-C01",
            "T03-R06-C02",
        )
        + refs(
            "precedent-index-gpu-capacity.docx",
            "T03-R01-C01",
            "T03-R01-C02",
            "T03-R02-C01",
            "T03-R02-C02",
            "T03-R03-C01",
            "T03-R03-C02",
            "T03-R04-C01",
            "T03-R04-C02",
            "T03-R05-C01",
            "T03-R05-C02",
            "T03-R06-C01",
            "T03-R06-C02",
        ),
        "Both precedents use numbered top-level folders with descriptive headings; V1 overreached by requiring separately numbered subfolders.",
        flags=("professional_judgment", "overly_broad"),
        disposition="reworded_to_supported_hierarchy",
    ),
    group(
        criterion_ids(5),
        ddrl_row(2, "02", "03")
        + refs("precedent-index-gpu-capacity.docx", "T03-R02-C03"),
        "D-01 and the compute precedent define corporate and authority coverage.",
    ),
    group(
        criterion_ids(6),
        ddrl_row(3, "02", "03")
        + refs("precedent-index-data-center.docx", "T03-R03-C03"),
        "D-02 and the site precedent define site-control coverage.",
    ),
    group(
        criterion_ids(7),
        ddrl_row(5, "02", "03")
        + ddrl_row(6, "02", "03")
        + ddrl_row(7, "02", "03")
        + refs("precedent-index-data-center.docx", "T03-R04-C03"),
        "D-04 through D-06 and the precedent define utility, ramp, and electrical evidence.",
    ),
    group(
        criterion_ids(8),
        ddrl_row(4, "02", "03")
        + ddrl_row(9, "02", "03")
        + refs("precedent-index-data-center.docx", "T03-R05-C03"),
        "D-03 and D-08 cover permits, design, construction, life safety, and commissioning.",
    ),
    group(
        criterion_ids(9),
        ddrl_row(10, "02", "03")
        + ddrl_row(11, "02", "03")
        + refs("precedent-index-gpu-capacity.docx", "T03-R03-C03"),
        "D-09, D-10, and the compute precedent define hardware and warranty evidence.",
    ),
    group(
        criterion_ids(10),
        ddrl_row(12, "02", "03")
        + refs("precedent-index-gpu-capacity.docx", "T03-R05-C03"),
        "D-11 defines the network and carrier evidence.",
    ),
    group(
        criterion_ids(11),
        ddrl_row(8, "02", "03")
        + refs("precedent-index-data-center.docx", "T03-R06-C03"),
        "D-07 and the data-center precedent define cooling and water coverage.",
    ),
    group(
        criterion_ids(12),
        ddrl_row(13, "02", "03")
        + ddrl_row(23, "02", "03")
        + refs("precedent-index-gpu-capacity.docx", "T03-R06-C03"),
        "D-12 and D-22 define security and data handling.",
    ),
    group(
        criterion_ids(13),
        ddrl_row(14, "02", "03")
        + ddrl_row(15, "02", "03")
        + ddrl_row(24, "02", "03")
        + refs("precedent-index-gpu-capacity.docx", "T03-R07-C03"),
        "D-13, D-14, and D-23 cover operations, incidents, staffing, SLA, and acceptance.",
    ),
    group(
        criterion_ids(14),
        ddrl_row(16, "02", "03")
        + ddrl_row(17, "02", "03")
        + refs("precedent-index-gpu-capacity.docx", "T03-R08-C03"),
        "D-15 and D-16 define capacity commitments and commercial materials.",
    ),
    group(
        criterion_ids(15),
        ddrl_row(18, "02", "03")
        + ddrl_row(19, "02", "03")
        + refs("precedent-index-gpu-capacity.docx", "T03-R09-C03"),
        "D-17 and D-18 define finance, debt, collateral, and support evidence.",
    ),
    group(
        criterion_ids(16),
        ddrl_row(20, "02", "03")
        + refs(
            "evidence-register.xlsx",
            "Evidence Register!C27",
            "Evidence Register!C28",
        ),
        "D-19 and the register cover all named insurance lines.",
    ),
    group(
        criterion_ids(17),
        ddrl_row(4, "02", "03") + ddrl_row(21, "02", "03"),
        "D-03 and D-20 cover permits, claims, regulation, sanctions, export controls, and compliance.",
    ),
    group(
        criterion_ids(18),
        ddrl_row(22, "02", "03")
        + refs("precedent-index-data-center.docx", "T03-R09-C03"),
        "D-21 and the data-center precedent define sustainability and environmental evidence.",
    ),
    group(
        criterion_ids(19),
        refs("operator-instructions.eml", "L003")
        + refs("precedent-index-data-center.docx", "T02-R01-C01")
        + refs("precedent-index-gpu-capacity.docx", "T02-R01-C01"),
        "The operator says to use both precedents for shape while the warnings prohibit uncritical copying.",
        flags=("summary_sensitive",),
    ),
    group(
        criterion_ids(20),
        refs("instruction.md", "L001")
        + refs("buyer-capacity-ddrl.docx", "P007")
        + refs("precedent-index-data-center.docx", "P007"),
        "The task and sources call for a working index with request mapping and document actions.",
        flags=("professional_judgment",),
    ),
    group(
        criterion_ids(21),
        sum(
            (ddrl_row(row, "01") for row in range(2, 26)),
            [],
        )
        + refs("buyer-capacity-ddrl.docx", "P010"),
        "The request table contains D-01 through D-24 and requires unsatisfied requests to remain open.",
    ),
    group(
        criterion_ids(22),
        refs(
            "project-stakeholder-map.docx",
            "T05-R02-C01",
            "T05-R02-C03",
            "T05-R03-C01",
            "T05-R03-C03",
            "T05-R04-C01",
            "T05-R04-C03",
            "T05-R05-C01",
            "T05-R05-C03",
            "T05-R06-C01",
            "T05-R06-C03",
            "T05-R07-C01",
            "T05-R07-C03",
        )
        + refs("operator-instructions.eml", "L015"),
        "The stakeholder map assigns named owners and the operator requires an owner on every line.",
    ),
    group(
        criterion_ids(23),
        refs("operator-instructions.eml", "L003", "L007", "L015")
        + refs(
            "buyer-capacity-ddrl.docx",
            "T01-R04-C02",
            "T01-R05-C02",
        ),
        "The sources define phases, clean-team staging, and explicit status per line.",
    ),
    group(
        criterion_ids(24),
        refs(
            "precedent-index-gpu-capacity.docx",
            "P007",
            "P008",
            "P009",
            "P010",
        ),
        "The compute precedent defines the four access levels.",
    ),
    group(
        criterion_ids(25),
        refs(
            "evidence-register.xlsx",
            "Status Summary!C4",
            "Status Summary!C5",
            "Status Summary!C6",
            "Status Summary!C7",
            "Status Summary!C8",
        )
        + refs("operator-instructions.eml", "L015"),
        "The status summary and operator instructions require visible readiness and next steps.",
    ),
    group(
        criterion_ids(26),
        refs(
            "buyer-capacity-ddrl.docx",
            "T01-R04-C02",
            "T01-R05-C02",
        )
        + refs("operator-instructions.eml", "L003"),
        "The DDRL and operator instruction state both phase dates.",
    ),
    group(
        criterion_ids(27),
        refs("operator-instructions.eml", "L007", "L009", "L013")
        + refs(
            "evidence-register.xlsx",
            "Evidence Register!L17",
            "Status Summary!D7",
            "Status Summary!D8",
        ),
        "The instructions identify clean-team, approval, consent, lender, and engineering dependencies.",
        flags=("overly_broad",),
        disposition="reworded_to_exact_dependencies",
    ),
    group(
        criterion_ids(28),
        refs("buyer-capacity-ddrl.docx", "P009")
        + refs("operator-instructions.eml", "L007", "L009")
        + refs("precedent-index-gpu-capacity.docx", "P009"),
        "The request, operator, and precedent identify the materials requiring clean-team handling.",
    ),
    group(
        criterion_ids(29),
        refs(
            "buyer-capacity-ddrl.docx",
            "P007",
            "P008",
            "P009",
            "P010",
        )
        + refs("precedent-index-data-center.docx", "P007"),
        "The production instructions and precedent require mapping, versioning, review, and archived superseded copies.",
        flags=("overly_broad",),
        disposition="reworded_to_exact_release_controls",
    ),
    group(
        criterion_ids(30),
        refs("operator-instructions.eml", "L015")
        + refs(
            "evidence-register.xlsx",
            "Status Summary!D5",
            "Status Summary!D6",
            "Status Summary!D7",
            "Status Summary!D8",
        ),
        "The sources require unresolved items to retain status, owner, escalation, and next step.",
        flags=("overly_broad",),
        disposition="reworded_to_exact_issue_controls",
    ),
    group(
        criterion_ids((31, 33)),
        ddrl_row(6, "01", "03")
        + refs("evidence-register.xlsx", "Evidence Register!L8")
        + refs("operator-instructions.eml", "L013"),
        "D-05 requests 24 MW by January 15, while the register supports a 12 MW January and 12 MW April ramp.",
        flags=("summary_sensitive",),
    ),
    group(
        criterion_ids(34),
        refs(
            "evidence-register.xlsx",
            "Evidence Register!C7",
            "Evidence Register!K7",
            "Evidence Register!L7",
        )
        + refs("operator-instructions.eml", "L011"),
        "The option is listed below the $500,000 threshold but expressly classified as operationally critical.",
        flags=("ambiguous",),
        disposition="reworded_to_exact_threshold_evidence",
    ),
    group(
        criterion_ids(35),
        refs(
            "evidence-register.xlsx",
            "Evidence Register!E7",
            "Evidence Register!L7",
        ),
        "The register gives both the October 31 deadline and responsible owner.",
        flags=("overly_broad",),
        disposition="reworded_to_exact_deadline_owner_action",
    ),
    group(
        criterion_ids(36),
        refs("operator-instructions.eml", "L013")
        + refs("precedent-index-data-center.docx", "P007"),
        "The operator names all five agreements and the precedent defines a separate consent tracker.",
    ),
    group(
        criterion_ids(37),
        refs("operator-instructions.eml", "L013", "L015")
        + refs("precedent-index-data-center.docx", "P007"),
        "The operator names all five consent workstreams and requires an owner, status, and next step on every line.",
        flags=("overly_broad",),
        disposition="reworded_to_exact_consent_tracker_fields",
    ),
    group(
        criterion_ids(38, 39),
        refs(
            "evidence-register.xlsx",
            "Evidence Register!C13",
            "Evidence Register!F13",
            "Evidence Register!L13",
            "Evidence Register!L14",
        )
        + refs("operator-instructions.eml", "L013")
        + refs("project-stakeholder-map.docx", "T06-R06-C03"),
        "The register and instruction identify the stale report, current design basis, Kestrel refresh, and priority.",
    ),
    group(
        criterion_ids(40),
        refs("buyer-capacity-ddrl.docx", "P009", "T03-R05-C03")
        + refs(
            "evidence-register.xlsx",
            "Evidence Register!H9",
            "Evidence Register!L9",
        )
        + refs("operator-instructions.eml", "L009"),
        "The buyer requests unredacted tariff support while release is on hold pending Owen and Marcus approval.",
        flags=("summary_sensitive",),
    ),
    group(
        criterion_ids(41),
        refs("buyer-capacity-ddrl.docx", "P009", "T03-R05-C03")
        + refs(
            "evidence-register.xlsx",
            "Evidence Register!H9",
            "Evidence Register!L9",
        )
        + refs(
            "operator-instructions.eml",
            "HEADER-FROM",
            "L009",
        )
        + refs(
            "project-stakeholder-map.docx",
            "T05-R03-C01",
            "T05-R03-C02",
            "T05-R05-C01",
            "T05-R05-C02",
        ),
        "Owen's instruction names Marcus and requires the utility disclosure conflict to be escalated for controlled clean-team treatment.",
        flags=("summary_sensitive", "imprecise_actor"),
        disposition="reworded_to_named_approvers",
    ),
    group(
        criterion_ids(42, 43),
        refs("buyer-capacity-ddrl.docx", "P009", "T03-R10-C03", "T03-R11-C03")
        + refs(
            "evidence-register.xlsx",
            "Evidence Register!L15",
            "Evidence Register!L18",
        )
        + refs("operator-instructions.eml", "L007"),
        "The requested unredacted provenance conflicts with the instructed two-stage supplier release.",
        flags=("summary_sensitive",),
    ),
    group(
        criterion_ids(44),
        refs(
            "evidence-register.xlsx",
            "Evidence Register!K19",
            "Evidence Register!L19",
            "Evidence Register!K21",
            "Evidence Register!L21",
        )
        + refs("operator-instructions.eml", "L011"),
        "Both agreements are below threshold and expressly operationally critical.",
    ),
    group(
        criterion_ids(45),
        refs(
            "evidence-register.xlsx",
            "Evidence Register!H29",
            "Evidence Register!K29",
            "Evidence Register!L29",
        )
        + refs("operator-instructions.eml", "L011"),
        "The register and operator require document-specific treatment of board material.",
    ),
    group(
        criterion_ids(46),
        ddrl_row(10, "03")
        + ddrl_row(19, "03")
        + refs(
            "evidence-register.xlsx",
            "Evidence Register!C17",
            "Evidence Register!K17",
            "Evidence Register!L17",
        )
        + refs("operator-instructions.eml", "L013"),
        "The DDRL, register, and operator identify Crestline collateral, consent, and release mechanics as a hardware-control priority.",
    ),
    group(
        criterion_ids(47),
        ddrl_row(20, "03")
        + refs(
            "evidence-register.xlsx",
            "Evidence Register!C28",
            "Evidence Register!E28",
            "Evidence Register!H28",
            "Evidence Register!L28",
        )
        + refs(
            "project-stakeholder-map.docx",
            "T05-R03-C01",
            "T05-R03-C02",
            "T05-R03-C03",
        ),
        "The insurance request and register show cyber and technology E&O as missing and assign Marcus Hale.",
    ),
    group(
        criterion_ids(48),
        refs(
            "project-stakeholder-map.docx",
            "T06-R02-C01",
            "T06-R03-C01",
            "T06-R04-C01",
            "T06-R05-C01",
            "T06-R06-C01",
        ),
        "The external-coordination table names each required third party.",
    ),
    group(
        criterion_ids(49),
        refs("operator-instructions.eml", "L013"),
        "The operator expressly prioritizes power, site, hardware control, and cooling refresh.",
        flags=("summary_sensitive",),
    ),
    group(
        criterion_ids(50),
        refs("operator-instructions.eml", "L003", "L007")
        + refs("precedent-index-data-center.docx", "P007"),
        "The sources support an initial index, phased releases, review, clean-team staging, and delta updates.",
        flags=("professional_judgment",),
    ),
    group(
        criterion_ids(51),
        refs(
            "precedent-index-gpu-capacity.docx",
            "P007",
            "P008",
            "P009",
            "P010",
        )
        + refs("operator-instructions.eml", "L007", "L009", "L011"),
        "The access convention and operator instructions define handling for each sensitivity class.",
    ),
    group(
        criterion_ids(52),
        refs("buyer-capacity-ddrl.docx", "P010")
        + refs("operator-instructions.eml", "L015")
        + refs("evidence-register.xlsx", "Status Summary!D5", "Status Summary!D6"),
        "The source materials explicitly prohibit completing or inventing missing evidence.",
        flags=("overly_broad",),
        evidence_scope="complete_normalized_matter",
    ),
    group(
        criterion_ids(53),
        refs("instruction.md", "L001") + refs("operator-instructions.eml", "L015"),
        "This is an integrative usability check grounded in the requested operating plan and per-line controls.",
        flags=("overly_broad", "professional_judgment"),
        evidence_scope="complete_normalized_matter",
    ),
]


def contract_refs(
    term_locations: Iterable[str] = (),
    negotiation_locations: Iterable[str] = (),
    agreement_locations: Iterable[str] = (),
    checklist_locations: Iterable[str] = (),
) -> list[dict[str, str]]:
    return (
        refs("agreed-capacity-term-sheet.docx", *term_locations)
        + refs("negotiation-summary.eml", *negotiation_locations)
        + refs("reserved-capacity-agreement.docx", *agreement_locations)
        + refs("buyer-risk-checklist.xlsx", *checklist_locations)
    )


CONTRACT_GROUPS = [
    group(
        criterion_ids((1, 5)),
        contract_refs(
            term_locations=("T03-R05-C02",),
            agreement_locations=("P019", "T04-R03-C02", "T04-R03-C03"),
            checklist_locations=("Buyer Risk Checklist!H14",),
        ),
        "The term sheet and Section 4.1 say 2%, Schedule 2 says 3%, and the checklist requires correction.",
        flags=("summary_sensitive",),
        derivation="$3.10 x 1.02 = $3.162; Schedule 2 states $3.193, a $0.031 difference.",
    ),
    group(
        criterion_ids((6, 8)),
        contract_refs(
            term_locations=("T03-R03-C02",),
            negotiation_locations=("L005",),
            agreement_locations=("P010", "P011", "P012"),
            checklist_locations=(
                "Buyer Risk Checklist!C17",
                "Buyer Risk Checklist!H17",
            ),
        ),
        "The term sheet, negotiated change, agreement, and checklist establish the staged but agreed ramp and acceptance-based billing.",
        flags=("summary_sensitive",),
    ),
    group(
        criterion_ids((9, 14)),
        contract_refs(
            term_locations=("T03-R11-C02",),
            negotiation_locations=("L007",),
            agreement_locations=("P035", "P036", "P037"),
            checklist_locations=(
                "Buyer Risk Checklist!C12",
                "Buyer Risk Checklist!H12",
            ),
        ),
        "The lower threshold was negotiated only with the original credit rate and cap, which the draft reduces.",
        flags=("summary_sensitive",),
    ),
    group(
        criterion_ids((15, 18)),
        contract_refs(
            term_locations=("T03-R06-C02", "T03-R07-C02"),
            negotiation_locations=("L011",),
            agreement_locations=("P020",),
            checklist_locations=(
                "Buyer Risk Checklist!C13",
                "Buyer Risk Checklist!H13",
            ),
        ),
        "The term sheet and negotiation preserve controlled pass-throughs, while the draft broadly reallocates power costs.",
        flags=("summary_sensitive",),
    ),
    group(
        criterion_ids((19, 21)),
        contract_refs(
            term_locations=("T03-R08-C02",),
            negotiation_locations=("L011",),
            agreement_locations=("P023",),
            checklist_locations=(
                "Buyer Risk Checklist!C15",
                "Buyer Risk Checklist!E15",
                "Buyer Risk Checklist!H15",
            ),
        ),
        "The draft changes both amount and refund treatment, contrary to the term sheet and checklist hard stop.",
        flags=("summary_sensitive",),
    ),
    group(
        criterion_ids((22, 26)),
        contract_refs(
            term_locations=("T03-R13-C02",),
            negotiation_locations=("L011",),
            agreement_locations=("P015", "P016", "P017"),
            checklist_locations=(
                "Buyer Risk Checklist!C16",
                "Buyer Risk Checklist!H16",
            ),
        ),
        "The draft weakens weekly delay credits, changes the cap and exit, and contains incorrect ten-week arithmetic.",
        flags=("summary_sensitive",),
        derivation="10 weeks x $150,000 equals $1.5 million, not the stated $2.5 million cap.",
    ),
    group(
        criterion_ids((27, 29)),
        contract_refs(
            term_locations=("T03-R09-C02",),
            negotiation_locations=("L011",),
            agreement_locations=("P027",),
            checklist_locations=(
                "Buyer Risk Checklist!C10",
                "Buyer Risk Checklist!E10",
                "Buyer Risk Checklist!H10",
            ),
        ),
        "The objective fabric obligation becomes discretionary wording and is a checklist hard stop.",
        flags=("summary_sensitive",),
    ),
    group(
        criterion_ids(30),
        contract_refs(
            term_locations=("T03-R10-C02",),
            agreement_locations=("P028", "P029"),
            checklist_locations=(
                "Buyer Risk Checklist!C18",
                "Buyer Risk Checklist!H18",
            ),
        ),
        "The draft qualifies the storage-throughput terms but preserves the separate 200 Gb/s external-ingress commitment; V1 incorrectly called the throughput sustained.",
        flags=("summary_sensitive", "overly_broad"),
        disposition="reworded_to_exact_storage_qualification",
    ),
    group(
        criterion_ids(31),
        contract_refs(
            term_locations=("T03-R10-C02",),
            agreement_locations=("P028", "P029"),
            checklist_locations=(
                "Buyer Risk Checklist!C18",
                "Buyer Risk Checklist!H18",
            ),
        ),
        "The draft converts measurable storage-throughput commitments into qualified design targets while preserving external ingress.",
        flags=("summary_sensitive",),
    ),
    group(
        criterion_ids(32),
        contract_refs(
            term_locations=("T03-R10-C02",),
            agreement_locations=("P028", "P029"),
            checklist_locations=(
                "Buyer Risk Checklist!C18",
                "Buyer Risk Checklist!H18",
            ),
        ),
        "The checklist requires measurable storage performance and a confirmed test method; the agreement already preserves the 200 Gb/s ingress term, and V1 prescribed additional cure mechanics not stated in the matter.",
        flags=("summary_sensitive", "overly_broad"),
        disposition="reworded_to_exact_measurability_fix",
    ),
    group(
        criterion_ids((33, 35)),
        contract_refs(
            term_locations=("T03-R15-C02",),
            negotiation_locations=("L011",),
            agreement_locations=("P007",),
            checklist_locations=("Buyer Risk Checklist!C9", "Buyer Risk Checklist!H9"),
        ),
        "The draft permits H200 or similar-memory substitutions without the required consent.",
        flags=("summary_sensitive",),
    ),
    group(
        criterion_ids((36, 38)),
        contract_refs(
            term_locations=("T03-R14-C02",),
            negotiation_locations=("L011",),
            agreement_locations=("P031", "P032", "P033"),
            checklist_locations=(
                "Buyer Risk Checklist!C11",
                "Buyer Risk Checklist!E11",
                "Buyer Risk Checklist!H11",
            ),
        ),
        "The negotiated objective acceptance package is replaced by provider tests and deemed acceptance.",
        flags=("summary_sensitive",),
    ),
    group(
        criterion_ids((39, 41)),
        contract_refs(
            term_locations=("T03-R12-C02",),
            agreement_locations=("P038",),
            checklist_locations=(
                "Buyer Risk Checklist!C20",
                "Buyer Risk Checklist!H20",
            ),
        ),
        "The draft increases maintenance by four hours and reduces notice by two days.",
        flags=("summary_sensitive",),
        derivation="12 hours is 50% greater than the agreed 8-hour limit.",
    ),
    group(
        criterion_ids(42, 43),
        contract_refs(
            term_locations=("T03-R17-C02",),
            negotiation_locations=("L011",),
            agreement_locations=("P048",),
            checklist_locations=(
                "Buyer Risk Checklist!C22",
                "Buyer Risk Checklist!H22",
            ),
        ),
        "The force-majeure exit changes from 90 to 180 days and the checklist supplies the response.",
        flags=("summary_sensitive",),
    ),
    group(
        criterion_ids(44, 45),
        contract_refs(
            term_locations=("T03-R16-C02",),
            negotiation_locations=("L011",),
            agreement_locations=("P044", "P045"),
            checklist_locations=(
                "Buyer Risk Checklist!C21",
                "Buyer Risk Checklist!H21",
            ),
        ),
        "The draft removes agreed affiliate assignment and controlled-customer use rights.",
        flags=("summary_sensitive",),
    ),
    group(
        criterion_ids((46, 48)),
        contract_refs(
            term_locations=("P007",),
            agreement_locations=("P050", "P051"),
            checklist_locations=(
                "Buyer Risk Checklist!C5",
                "Buyer Risk Checklist!C6",
                "Buyer Risk Checklist!C8",
                "Buyer Risk Checklist!H8",
            ),
        ),
        "The term sheet requires objective control evidence while the draft offers qualified rights and provider-selected consents.",
        flags=("summary_sensitive",),
    ),
    group(
        criterion_ids(49, 50),
        contract_refs(
            term_locations=("P010",),
            agreement_locations=("P052",),
            checklist_locations=(
                "Buyer Risk Checklist!C5",
                "Buyer Risk Checklist!E5",
                "Buyer Risk Checklist!H5",
            ),
        ),
        "The parent guarantee is a signing condition and hard stop, but the draft postpones it.",
        flags=("summary_sensitive",),
    ),
    group(
        criterion_ids((51, 53)),
        contract_refs(
            term_locations=("P008",),
            agreement_locations=("P040", "P041", "P042"),
            checklist_locations=(
                "Buyer Risk Checklist!C19",
                "Buyer Risk Checklist!E19",
                "Buyer Risk Checklist!H19",
            ),
        ),
        "The term sheet conditions signing on an agreed security schedule, which is absent while the draft relies on it.",
        flags=("summary_sensitive",),
    ),
    group(
        criterion_ids(54, 55),
        contract_refs(
            term_locations=("T03-R18-C02",),
            negotiation_locations=("L011",),
            agreement_locations=("P055",),
            checklist_locations=(
                "Buyer Risk Checklist!C23",
                "Buyer Risk Checklist!E23",
                "Buyer Risk Checklist!H23",
            ),
        ),
        "The draft replaces agreed arbitration with Virginia litigation; the checklist requires approval or restoration.",
        flags=("summary_sensitive", "professional_judgment"),
    ),
    group(
        criterion_ids(56),
        contract_refs(
            negotiation_locations=("HEADER-DATE", "L009"),
            agreement_locations=("P013",),
            checklist_locations=(
                "Buyer Risk Checklist!C24",
                "Buyer Risk Checklist!E24",
                "Buyer Risk Checklist!H24",
            ),
        ),
        "The expansion option is expressly negotiated, reflected, and classified as favorable.",
    ),
    group(
        criterion_ids(57),
        contract_refs(
            term_locations=("P007",),
            checklist_locations=(
                "Buyer Risk Checklist!C6",
                "Buyer Risk Checklist!E6",
                "Buyer Risk Checklist!H6",
            ),
        ),
        "The contracting checklist itself states the 12 MW January plus 12 MW April mismatch and hard-stop treatment.",
    ),
    group(
        criterion_ids(58),
        contract_refs(
            term_locations=("P007",),
            checklist_locations=(
                "Buyer Risk Checklist!C7",
                "Buyer Risk Checklist!E7",
                "Buyer Risk Checklist!F7",
                "Buyer Risk Checklist!H7",
            ),
        ),
        "V1 imported an October 31 deadline from a different task. V2 uses only the contracting checklist's open site-control hard stop and required exercise/extension plus consent.",
        flags=("unsupported", "cross_task_contamination"),
        disposition="repaired_to_contracting_matter_only",
    ),
    group(
        criterion_ids(59),
        contract_refs(
            term_locations=("P007",),
            agreement_locations=("P050",),
            checklist_locations=(
                "Buyer Risk Checklist!C8",
                "Buyer Risk Checklist!E8",
                "Buyer Risk Checklist!H8",
            ),
        ),
        "The checklist keeps hardware title, serial allocation, liens, consent, and release mechanics open.",
    ),
    group(
        criterion_ids(60),
        contract_refs(
            checklist_locations=(
                "Buyer Risk Checklist!C25",
                "Buyer Risk Checklist!E25",
                "Buyer Risk Checklist!F25",
                "Buyer Risk Checklist!H25",
            ),
        ),
        "The checklist keeps insurance, financial capacity, and the final credit package open.",
    ),
    group(
        criterion_ids(61),
        contract_refs(
            checklist_locations=(
                "Gate Summary!D4",
                "Gate Summary!D5",
                "Gate Summary!D6",
                "Gate Summary!D7",
            ),
        )
        + refs("instruction.md", "L001"),
        "The gate summary supplies the execution hierarchy and do-not-sign rule.",
        flags=("professional_judgment",),
    ),
    group(
        criterion_ids(62),
        refs("instruction.md", "L001")
        + contract_refs(
            term_locations=("P012",),
            negotiation_locations=("L003", "L013"),
        ),
        "The instruction and hierarchy clauses require buyer-perspective, source-grounded classification across the whole report.",
        flags=("overly_broad", "professional_judgment", "summary_sensitive"),
        evidence_scope="complete_normalized_matter",
    ),
]


AUDIT_GROUPS = {
    "normalize-buyer-mandate": NORMALIZE_GROUPS,
    "draft-capacity-data-room-population-plan": DILIGENCE_GROUPS,
    "compare-capacity-agreement-against-term-sheet": CONTRACT_GROUPS,
}
