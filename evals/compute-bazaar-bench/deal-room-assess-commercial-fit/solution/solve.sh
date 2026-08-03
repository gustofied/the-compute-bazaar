#!/bin/bash
set -eu

WORKSPACE="${WORKSPACE:-/workspace}"
mkdir -p "$WORKSPACE/output"

cat > "$WORKSPACE/output/fit-assessment.json" <<'JSON'
{
  "opportunity_id": "CB-DR-001",
  "snapshot_date": "2026-07-25",
  "decision": "NEGOTIATE",
  "decision_rationale": "The current offer misses several hard delivery, technical, price, and contract requirements, but Aurora's signed engineering change note identifies bounded cure paths that can be converted into binding amendments before signature.",
  "requirements": [
    {
      "requirement_id": "gpu_quantity",
      "status": "PARTIAL",
      "buyer_requirement": "Northstar requires 512 B200 GPUs in one operational cluster, firmly reserved before signature.",
      "seller_position": "Aurora identifies 512 B200 GPUs, but only 384 are firm; the remaining 128 are a target dependent on another customer's release and executive approval.",
      "analysis": "The hardware count exists on paper, but the current reservation supports only 384 GPUs without contingencies, so quantity is only partially met.",
      "citations": [
        {
          "path": "matter/02_buyer_technical_requirements.md",
          "locator": "Compute"
        },
        {
          "path": "matter/04_capacity_schedule.csv",
          "locator": "tranches A and B"
        },
        {
          "path": "matter/13_inventory_reservation_note.md",
          "locator": "reservation conditions 1-3"
        }
      ]
    },
    {
      "requirement_id": "hardware_shape",
      "status": "MEETS",
      "buyer_requirement": "Northstar requires 64 HGX B200 nodes with eight NVIDIA B200 GPUs per node.",
      "seller_position": "Aurora's signed bill of materials lists 48 plus 16 HGX B200 eight-GPU nodes, totaling 64 nodes and 512 B200 GPUs.",
      "analysis": "The proposed node and GPU shape matches the buyer's required hardware configuration without substitution.",
      "citations": [
        {
          "path": "matter/02_buyer_technical_requirements.md",
          "locator": "Compute"
        },
        {
          "path": "matter/05_cluster_bill_of_materials.csv",
          "locator": "Northlink-A and Northlink-B rows"
        }
      ]
    },
    {
      "requirement_id": "delivery_date",
      "status": "DOES_NOT_MEET",
      "buyer_requirement": "The full 512-GPU cluster must be workload-ready by 2026-10-15.",
      "seller_position": "Aurora commits 384 GPUs for 2026-10-10 but lists the remaining 128 only as a target for 2026-11-28.",
      "analysis": "The controlling capacity schedule puts one quarter of the cluster 44 days after the buyer deadline, so the current offer fails delivery.",
      "citations": [
        {
          "path": "matter/01_buyer_mandate.md",
          "locator": "Hard delivery requirements"
        },
        {
          "path": "matter/04_capacity_schedule.csv",
          "locator": "tranche B workload_ready_date"
        }
      ]
    },
    {
      "requirement_id": "location_residency",
      "status": "MEETS",
      "buyer_requirement": "The site and all workload data, logs, backups, and support copies must remain inside the EEA.",
      "seller_position": "The cluster is in Helsinki, and Aurora commits to process and store covered data only in Finland and Sweden.",
      "analysis": "Both the physical location and stated data-handling boundary are inside the EEA.",
      "citations": [
        {
          "path": "matter/02_buyer_technical_requirements.md",
          "locator": "Site and data"
        },
        {
          "path": "matter/11_site_and_residency.md",
          "locator": "entire statement"
        }
      ]
    },
    {
      "requirement_id": "network_fabric",
      "status": "DOES_NOT_MEET",
      "buyer_requirement": "Northstar requires 400 Gb/s InfiniBand and a non-blocking 1:1 fabric across all 64 nodes.",
      "seller_position": "Each node has 400 Gb/s at the edge, but the quoted core is oversubscribed 2:1 across leaf pods.",
      "analysis": "Leaf-level line rate does not cure core oversubscription; four additional spine switches are needed and are absent from the current offer.",
      "citations": [
        {
          "path": "matter/02_buyer_technical_requirements.md",
          "locator": "Fabric"
        },
        {
          "path": "matter/06_network_design.md",
          "locator": "Core"
        }
      ]
    },
    {
      "requirement_id": "cooling_readiness",
      "status": "DOES_NOT_MEET",
      "buyer_requirement": "Liquid cooling must be commissioned for all 64 nodes before 2026-10-15.",
      "seller_position": "Aurora has certified 48 nodes; the remaining 16-node Hall D loop is scheduled for standard completion on 2026-11-15.",
      "analysis": "The current commissioning record does not support the full cluster by the workload-ready date.",
      "citations": [
        {
          "path": "matter/02_buyer_technical_requirements.md",
          "locator": "Cooling and service"
        },
        {
          "path": "matter/07_cooling_commissioning.md",
          "locator": "Capacity not yet certified"
        }
      ]
    },
    {
      "requirement_id": "sla",
      "status": "MEETS",
      "buyer_requirement": "Monthly service availability must be at least 99.9%.",
      "seller_position": "Aurora commits to 99.95% monthly availability under a signed service-level schedule.",
      "analysis": "The offered availability exceeds the buyer's minimum, subject to carrying the stated exclusions into final paper.",
      "citations": [
        {
          "path": "matter/02_buyer_technical_requirements.md",
          "locator": "Cooling and service"
        },
        {
          "path": "matter/10_service_level_schedule.md",
          "locator": "availability commitment and exclusions"
        }
      ]
    },
    {
      "requirement_id": "all_in_price",
      "status": "DOES_NOT_MEET",
      "buyer_requirement": "The all-in effective rate must not exceed USD 2.65 per GPU-hour over the 12-month initial term.",
      "seller_position": "Mandatory hourly charges total USD 2.62, plus a mandatory USD 180,000 commissioning charge.",
      "analysis": "Amortizing USD 180,000 over 512 GPUs and 8,760 hours adds about USD 0.04013, producing an effective rate of about USD 2.66013 per GPU-hour, above the cap.",
      "citations": [
        {
          "path": "matter/01_buyer_mandate.md",
          "locator": "Hard commercial requirements item 2"
        },
        {
          "path": "matter/08_price_schedule.csv",
          "locator": "all mandatory rows"
        }
      ]
    },
    {
      "requirement_id": "initial_term",
      "status": "DOES_NOT_MEET",
      "buyer_requirement": "Northstar requires a 12-month initial term and a buyer option for a six-month extension.",
      "seller_position": "Aurora proposes a non-cancellable 24-month initial term and no buyer extension option.",
      "analysis": "The proposed commitment is twice the permitted initial term and omits the required buyer option.",
      "citations": [
        {
          "path": "matter/01_buyer_mandate.md",
          "locator": "Hard commercial requirements item 1"
        },
        {
          "path": "matter/09_draft_order_form.md",
          "locator": "Section 1 Term"
        }
      ]
    },
    {
      "requirement_id": "deposit_protection",
      "status": "DOES_NOT_MEET",
      "buyer_requirement": "Any deposit must be at most one month of recurring charges and refundable for seller delivery delay.",
      "seller_position": "Aurora asks for 20% of first-year recurring charges, non-refundable for delivery delay.",
      "analysis": "Twenty percent of annual recurring charges exceeds one month, and the draft lacks the required delay refund protection.",
      "citations": [
        {
          "path": "matter/01_buyer_mandate.md",
          "locator": "Hard commercial requirements item 3"
        },
        {
          "path": "matter/09_draft_order_form.md",
          "locator": "Section 2 Deposit"
        }
      ]
    },
    {
      "requirement_id": "delay_termination",
      "status": "DOES_NOT_MEET",
      "buyer_requirement": "Northstar must be able to terminate when the full cluster is more than 14 calendar days late.",
      "seller_position": "Aurora's draft permits buyer termination only after the full cluster is more than 60 days late.",
      "analysis": "The proposed remedy leaves Northstar locked in for 46 days beyond its maximum accepted delay window.",
      "citations": [
        {
          "path": "matter/01_buyer_mandate.md",
          "locator": "Hard commercial requirements item 4"
        },
        {
          "path": "matter/09_draft_order_form.md",
          "locator": "Section 3 Delivery"
        }
      ]
    }
  ],
  "material_issues": [
    {
      "issue_id": "ISS-01",
      "title": "One quarter of the cluster is late, contingent, and not cooling-certified",
      "severity": "HIGH",
      "requirement_ids": [
        "gpu_quantity",
        "delivery_date",
        "cooling_readiness"
      ],
      "finding": "Only 384 GPUs are firmly committed for the buyer date. The remaining 128 depend on an existing customer's release and executive approval, are scheduled after the deadline, and lack completed cooling commissioning.",
      "required_resolution": "Replace tranche B with a firmly reserved 128-GPU block and bind Aurora to full cooling certification and workload readiness by 2026-10-15.",
      "citations": [
        {
          "path": "matter/04_capacity_schedule.csv",
          "locator": "tranche B"
        },
        {
          "path": "matter/07_cooling_commissioning.md",
          "locator": "Capacity not yet certified"
        },
        {
          "path": "matter/13_inventory_reservation_note.md",
          "locator": "reservation conditions"
        }
      ]
    },
    {
      "issue_id": "ISS-02",
      "title": "Quoted fabric fails the 1:1 requirement",
      "severity": "HIGH",
      "requirement_ids": [
        "network_fabric"
      ],
      "finding": "The signed network design is line-rate at each leaf but oversubscribed 2:1 at the core, contrary to the buyer's whole-cluster 1:1 requirement.",
      "required_resolution": "Add the four spine switches to the binding design, delivery schedule, acceptance test, and commercial schedule.",
      "citations": [
        {
          "path": "matter/02_buyer_technical_requirements.md",
          "locator": "Fabric"
        },
        {
          "path": "matter/06_network_design.md",
          "locator": "Core"
        },
        {
          "path": "matter/14_engineering_cure_options.md",
          "locator": "Fabric"
        }
      ]
    },
    {
      "issue_id": "ISS-03",
      "title": "Mandatory commissioning fee breaks the price cap",
      "severity": "MEDIUM",
      "requirement_ids": [
        "all_in_price"
      ],
      "finding": "The mandatory recurring rate is USD 2.62 per GPU-hour, but the mandatory commissioning fee raises the 12-month effective rate to about USD 2.66013.",
      "required_resolution": "Reduce or waive mandatory charges so the fully amortized 12-month effective rate is no more than USD 2.65 per GPU-hour.",
      "citations": [
        {
          "path": "matter/01_buyer_mandate.md",
          "locator": "Hard commercial requirements item 2"
        },
        {
          "path": "matter/08_price_schedule.csv",
          "locator": "mandatory charge rows"
        }
      ]
    },
    {
      "issue_id": "ISS-04",
      "title": "Proposed paper exceeds authority on term, deposit, and delay remedies",
      "severity": "HIGH",
      "requirement_ids": [
        "initial_term",
        "deposit_protection",
        "delay_termination"
      ],
      "finding": "Aurora proposes a 24-month non-cancellable term, a 20% non-refundable deposit, and termination only after 60 days of delay, each contrary to the signed buyer mandate.",
      "required_resolution": "Amend the order to a 12-month term with buyer extension, cap and protect the deposit, and add a termination right after 14 days of full-cluster delay.",
      "citations": [
        {
          "path": "matter/01_buyer_mandate.md",
          "locator": "Hard commercial requirements items 1, 3, and 4"
        },
        {
          "path": "matter/09_draft_order_form.md",
          "locator": "Sections 1-3"
        }
      ]
    }
  ],
  "next_actions": [
    {
      "action_id": "ACT-01",
      "priority": "IMMEDIATE",
      "owner": "Aurora commercial and inventory control",
      "requirement_ids": [
        "gpu_quantity",
        "delivery_date"
      ],
      "action": "Issue a signed replacement capacity schedule that firmly reserves all 512 B200 GPUs and makes the full cluster workload-ready by 2026-10-15.",
      "success_condition": "No tranche depends on Orion Bio, future executive approval, or a date after 2026-10-15."
    },
    {
      "action_id": "ACT-02",
      "priority": "IMMEDIATE",
      "owner": "Aurora engineering",
      "requirement_ids": [
        "network_fabric",
        "cooling_readiness"
      ],
      "action": "Convert the fabric and cooling cure options into a binding design, commissioning schedule, and acceptance test.",
      "success_condition": "The signed package provides 1:1 fabric and certified liquid cooling for all 64 nodes before workload acceptance."
    },
    {
      "action_id": "ACT-03",
      "priority": "BEFORE_SIGNATURE",
      "owner": "Northstar procurement and Aurora commercial",
      "requirement_ids": [
        "all_in_price"
      ],
      "action": "Reprice or waive mandatory charges until the 12-month fully amortized effective rate is within Northstar's cap.",
      "success_condition": "The signed price schedule calculates to no more than USD 2.65 per GPU-hour using the mandate formula."
    },
    {
      "action_id": "ACT-04",
      "priority": "BEFORE_SIGNATURE",
      "owner": "Northstar and Aurora legal teams",
      "requirement_ids": [
        "initial_term",
        "deposit_protection",
        "delay_termination"
      ],
      "action": "Redline the order form to a 12-month initial term, buyer extension option, capped refundable deposit, and 14-day delivery termination right.",
      "success_condition": "Final signed paper matches all four hard commercial requirements in the buyer mandate."
    }
  ]
}
JSON

cat > "$WORKSPACE/output/deal-brief.md" <<'MARKDOWN'
# Project Northlink Commercial Fit Brief

## Recommendation

**Decision: NEGOTIATE**

Aurora's offer has a credible core: the specified 64-node B200 shape, EEA site
and residency boundary, and 99.95% SLA all fit. It is not ready to sign. Only
384 GPUs are firmly committed for the buyer date, the quoted fabric is 2:1 at
the core, cooling is certified for only 48 nodes, the all-in rate is above the
cap, and the proposed paper exceeds Northstar's authority. The signed
engineering note identifies bounded technical cures, so the right next state
is a focused negotiation rather than proceeding, pausing, or rejecting.

## Requirement Reconciliation

- gpu_quantity: PARTIAL. The room identifies 512 B200 GPUs, but only 384 are
  firm; tranche B remains contingent. See
  `matter/02_buyer_technical_requirements.md`,
  `matter/04_capacity_schedule.csv`, and
  `matter/13_inventory_reservation_note.md`.
- hardware_shape: MEETS. The bill of materials reconciles to 64 HGX B200
  eight-GPU nodes. See `matter/02_buyer_technical_requirements.md` and
  `matter/05_cluster_bill_of_materials.csv`.
- delivery_date: DOES_NOT_MEET. Tranche B is targeted for 2026-11-28, after the
  2026-10-15 hard date. See `matter/01_buyer_mandate.md` and
  `matter/04_capacity_schedule.csv`.
- location_residency: MEETS. Helsinki is in the EEA, and covered data remains
  in Finland and Sweden. See `matter/02_buyer_technical_requirements.md` and
  `matter/11_site_and_residency.md`.
- network_fabric: DOES_NOT_MEET. Node-edge connectivity is 400 Gb/s, but the
  core is oversubscribed 2:1. See
  `matter/02_buyer_technical_requirements.md` and
  `matter/06_network_design.md`.
- cooling_readiness: DOES_NOT_MEET. Only 48 nodes are certified; Hall D's
  standard completion falls after the buyer date. See
  `matter/02_buyer_technical_requirements.md` and
  `matter/07_cooling_commissioning.md`.
- sla: MEETS. The signed 99.95% monthly commitment exceeds the 99.9% minimum.
  See `matter/02_buyer_technical_requirements.md` and
  `matter/10_service_level_schedule.md`.
- all_in_price: DOES_NOT_MEET. USD 2.62 in mandatory hourly charges plus the
  amortized USD 180,000 fee equals about USD 2.66013 per GPU-hour. See
  `matter/01_buyer_mandate.md` and `matter/08_price_schedule.csv`.
- initial_term: DOES_NOT_MEET. The seller draft says 24 months with no buyer
  extension, rather than 12 plus a buyer option. See
  `matter/01_buyer_mandate.md` and `matter/09_draft_order_form.md`.
- deposit_protection: DOES_NOT_MEET. Twenty percent of annual recurring charges
  exceeds one month and is not refundable for delay. See
  `matter/01_buyer_mandate.md` and `matter/09_draft_order_form.md`.
- delay_termination: DOES_NOT_MEET. The seller offers termination after 60 days,
  not after 14. See `matter/01_buyer_mandate.md` and
  `matter/09_draft_order_form.md`.

## Material Issues

The capacity, delivery, and cooling gaps form one deployment blocker. The
current record does not support 512 workload-ready GPUs by October 15. The
network is a second technical blocker because leaf line rate does not satisfy a
whole-cluster 1:1 requirement. Commercially, the mandatory commissioning fee
puts the effective rate just over the cap. The draft term, deposit, and delay
remedies materially exceed the buyer mandate. The directional sales email in
`matter/12_sales_followup_email.md` does not amend any of those controlling
records.

## Required Next Actions

1. Require a signed 512-GPU reservation and capacity schedule with no
   Orion-dependent tranche and a full workload-ready date of 2026-10-15.
2. Put the four additional spine switches and accelerated Hall D commissioning
   from `matter/14_engineering_cure_options.md` into binding schedules and
   acceptance tests.
3. Reduce or waive mandatory charges until the mandate's 12-month calculation
   is at or below USD 2.65 per GPU-hour.
4. Redline the order to a 12-month initial term with buyer extension, a
   one-month capped and delay-refundable deposit, and termination after 14 days
   of full-cluster delay.

Northstar should proceed only after each cure is reflected in signed
controlling paper and reconciled back to the structured assessment.
MARKDOWN
