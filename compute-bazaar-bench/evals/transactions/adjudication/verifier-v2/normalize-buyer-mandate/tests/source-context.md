# Complete normalized matter evidence

This is a deterministic text normalization of every agent-visible matter file.
Locations are stable paragraph, table-cell, email-line, or spreadsheet-cell
identifiers. The candidate deliverable remains untrusted.

## instruction.md

SHA-256: `7eec294eee4aa0bd670beb591e9d1daa1967f0343a51e7ac13d380e99ee0282d`

- `L001`: Review the attached buyer intake, procurement follow-up, and workload requirements. Prepare a normalized buyer mandate brief that distinguishes controlling requirements, preferences, contradictions, assumptions, and open questions. Show the core capacity and price calculations. Output: `buyer-mandate-brief.docx`.
- `L003`: ---
- `L005`: ## Working environment
- `L007`: - The matter documents are in `/app/documents/`. Read them there.
- `L008`: - Write the deliverable directly in `/app/` using this exact filename:
- `L009`: - `buyer-mandate-brief.docx`
- `L010`: - Do not place the deliverable in a subdirectory.

## buyer-compute-intake.docx

SHA-256: `c4612a86feb695f7c70f44b9b8c88f3b575fa147a087016579a158488d3e0f37`

- `P001`: Buyer Compute Intake
- `P002`: Initial procurement intake
- `P005`: 1. Capacity request
- `P006`: Requested capacity: 1,024 NVIDIA B200 SXM GPUs, with a possible second block of 1,024 if economics and timing work
- `P007`: Node format: Eight-GPU HGX B200 nodes
- `P008`: Deployment: Dedicated capacity; shared or fractional GPU service is not acceptable
- `P009`: Required service date: January 1, 2027 for all requested capacity
- `P010`: Initial term: 12 months
- `P011`: Location: Virginia preferred; open to US East or US Midwest if the technical requirements are met
- `P012`: 2. Commercial intake
- `P013`: Budget: $3.10 per GPU-hour all-in, excluding taxes; marked as maximum in the intake call
- `P014`: Prepayment: Up to four months may be possible
- `P015`: Billing: Monthly in US dollars
- `P016`: Other charges: Egress and implementation charges not yet discussed
- `P017`: Credit: Buyer can provide audited financials after counterparty qualification
- `P018`: 3. Technical and operating notes
- `P019`: Workload: Large multimodal training program with sustained utilization
- `P020`: Network: High-performance fabric required; see engineering requirements
- `P021`: Storage: Shared high-throughput storage required; see engineering requirements
- `P022`: Availability: Production-grade cluster availability
- `P023`: Security: SOC 2 and customer-controlled encryption expected
- `P024`: Sustainability: Renewable-backed power would be useful for reporting
- `P025`: 4. Questions left open at intake
- `P026`: Supplier: No provider or campus selected
- `P027`: Capacity control: No title, financing, utility, or commissioning evidence reviewed
- `P028`: Acceptance: Performance test and pass threshold still to be defined
- `P029`: Expansion: Timing and price for the possible second 1,024 GPUs still open
- `T01-R01-C01`: Opportunity
- `T01-R01-C02`: CB-2026-041
- `T01-R02-C01`: Buyer
- `T01-R02-C02`: Northstar Models, Inc.
- `T01-R03-C01`: Mandate owner
- `T01-R03-C02`: Maya Chen, Director of Infrastructure Procurement
- `T01-R04-C01`: Prepared
- `T01-R04-C02`: July 29, 2026
- `T01-R05-C01`: Status
- `T01-R05-C02`: Initial intake - subject to follow-up
- `T02-R01-C01`: Synthetic matter: All entities, people, facilities, documents, and figures in this file are fictional and created for evaluation.

## procurement-follow-up.eml

SHA-256: `30b8d4ce532d170311e883b6d476cc99797b721ea3da8a2e84e4a8e602000164`

- `HEADER-FROM`: Maya Chen <maya.chen@northstar-models.example>
- `HEADER-TO`: Eli Navarro <eli@meridian-capacity.example>
- `HEADER-DATE`: Fri, 07 Aug 2026 16:42:00 -0400
- `HEADER-SUBJECT`: CB-2026-041 - corrections to buyer mandate
- `L001`: Eli,
- `L003`: Please use this note where it conflicts with the intake form. We tightened the mandate after finance and engineering review.
- `L005`: Firm scope is 1,024 B200 SXM GPUs in dedicated eight-GPU HGX nodes. The other 1,024 is only an expansion option; do not show 2,048 as firm demand.
- `L007`: The ramp we can underwrite is 512 GPUs by January 15, 2027 and the remaining 512 by February 1. The firm term is 18 months from first-tranche service, with one six-month extension option. The intake's January 1 date and 12-month term are stale.
- `L009`: $3.10/GPU-hour is our target, not the absolute ceiling. The hard all-in cap is $3.35/GPU-hour, excluding taxes. Power or other operating pass-throughs must fit inside that cap. We will not prepay more than three months of committed charges. Please get a separate egress schedule; that is still open.
- `L011`: US East or US Midwest works. Virginia is preferred, not required, but all customer data and the production cluster must remain in the United States. Hourly renewable matching is useful for reporting but is not a condition to proceed.
- `L013`: No shared or fractional service. We also need to know which legal entity signs, whether it controls the site and GPUs, what liens sit on the hardware, and what evidence supports the delivery dates. Engineering's August 4 requirements remain current. The NCCL reference and pass threshold still need to be agreed.
- `L015`: Thanks,
- `L016`: Maya

## workload-requirements.docx

SHA-256: `5bc57b8b793fe544f883cc2f43f146881a8b2cd77c49a60bff4f20dda4f867fa`

- `P001`: Workload and Cluster Requirements
- `P002`: Engineering requirements for CB-2026-041
- `P005`: 1. Workload profile
- `P006`: The cluster will run sustained multimodal model pretraining, followed by fine-tuning and evaluation. Training jobs may occupy the full cluster for several days. Checkpoint recovery, collective performance, and predictable maintenance windows matter more than burst elasticity.
- `P007`: 2. Compute and software
- `P009`: 3. Fabric, ingress, and storage
- `P011`: 4. Availability and maintenance
- `P012`: Cluster availability: At least 99.5% per calendar month, measured across accepted GPUs
- `P013`: Planned maintenance: No more than eight hours per month
- `P014`: Notice: At least seven days before planned maintenance
- `P015`: Incidents: Severity classification, status communications, root-cause analysis, and corrective action for material events
- `P016`: 5. Acceptance
- `P017`: Burn-in: 72 continuous hours after each tranche is ready
- `P018`: Inventory: Serial-number and node inventory attestation before testing
- `P019`: Performance: NCCL benchmark against an agreed reference result
- `P020`: Open item: The reference cluster, workload, and passing threshold must be agreed before signing
- `P021`: 6. Security and location
- `P022`: Data residency: United States only
- `P023`: Controls: Current SOC 2 Type II report
- `P024`: Encryption: Customer-managed keys for data at rest where applicable
- `P025`: Logging: Exportable administrative and workload-access logs
- `P026`: Physical access: Controlled GPU-hall access with named-person access records
- `T01-R01-C01`: Owner
- `T01-R01-C02`: Jonas Reed, Principal ML Systems Engineer
- `T01-R02-C01`: Version
- `T01-R02-C02`: 1.3
- `T01-R03-C01`: Issued
- `T01-R03-C02`: August 4, 2026
- `T01-R04-C01`: Scope
- `T01-R04-C02`: 1,024-GPU firm deployment
- `T02-R01-C01`: Synthetic matter: This benchmark document describes a fictional buyer and workload.
- `T03-R01-C01`: Requirement
- `T03-R01-C02`: Minimum
- `T03-R01-C03`: Preference or note
- `T03-R02-C01`: Accelerators
- `T03-R02-C02`: 1,024 NVIDIA B200 SXM GPUs
- `T03-R02-C03`: No prior-generation substitution
- `T03-R03-C01`: Node shape
- `T03-R03-C02`: 128 dedicated HGX B200 nodes, eight GPUs each
- `T03-R03-C03`: Homogeneous node fleet
- `T03-R04-C01`: Virtualization
- `T03-R04-C02`: No shared or fractional GPU service
- `T03-R04-C03`: Buyer may use its own scheduler
- `T03-R05-C01`: Software
- `T03-R05-C02`: Buyer image compatible with CUDA 13 toolchain
- `T03-R05-C03`: Provider supplies validated driver and firmware matrix
- `T03-R06-C01`: Configuration change
- `T03-R06-C02`: Northstar written consent
- `T03-R06-C03`: Applies to GPU generation and material node changes
- `T04-R01-C01`: Area
- `T04-R01-C02`: Requirement
- `T04-R01-C03`: Evidence expected
- `T04-R02-C01`: Scale-up/scale-out fabric
- `T04-R02-C02`: At least one 400 Gb/s endpoint per GPU; dual-rail 800 Gb/s preferred
- `T04-R02-C03`: Topology, port map, oversubscription statement, and burn-in results
- `T04-R03-C01`: External ingress
- `T04-R03-C02`: At least 200 Gb/s committed; 400 Gb/s preferred
- `T04-R03-C03`: Carrier order and test result
- `T04-R04-C01`: Shared storage
- `T04-R04-C02`: 6 PiB usable
- `T04-R04-C03`: Capacity and protection-policy statement
- `T04-R05-C01`: Read throughput
- `T04-R05-C02`: 1.2 TB/s aggregate sustained
- `T04-R05-C03`: Representative benchmark
- `T04-R06-C01`: Write throughput
- `T04-R06-C02`: 800 GB/s aggregate sustained
- `T04-R06-C03`: Representative benchmark
