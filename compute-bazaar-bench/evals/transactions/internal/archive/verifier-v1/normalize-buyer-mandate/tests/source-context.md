# Trusted source context

This packet summarizes only the closed matter files supplied to the agent. The dated procurement follow-up controls where it expressly changes the initial intake. The August 4 workload requirements remain controlling for technical facts.

## buyer-compute-intake.docx - July 29, 2026

- Opportunity: CB-2026-041.
- Buyer: Northstar Models, Inc.
- Mandate owner: Maya Chen, Director of Infrastructure Procurement.
- Initial intake: 1,024 NVIDIA B200 SXM GPUs, with a possible second 1,024; dedicated eight-GPU HGX B200 nodes; January 1, 2027 full delivery; 12-month term.
- Initial commercial notes: $3.10/GPU-hour was marked as an all-in maximum; four months of prepayment might be possible; egress and implementation charges were not discussed.
- Initial location: Virginia preferred, with US East or US Midwest possible.
- Open at intake: provider and campus, capacity-control evidence, acceptance test and threshold, and expansion timing and price.

## workload-requirements.docx - August 4, 2026

- Workload: sustained multimodal model pretraining followed by fine-tuning and evaluation; full-cluster jobs may run for days.
- Firm configuration: 1,024 B200 SXM GPUs in 128 dedicated eight-GPU HGX B200 nodes. No shared or fractional service. Northstar must approve any GPU-generation or material node change in writing.
- Software: buyer image must work with CUDA 13; provider supplies a validated driver and firmware matrix.
- Fabric: at least one 400 Gb/s endpoint per GPU; dual-rail 800 Gb/s is preferred. Evidence includes topology, port map, oversubscription statement, and burn-in results.
- External ingress: at least 200 Gb/s committed; 400 Gb/s preferred. Evidence includes carrier order and test results.
- Storage: 6 PiB usable; sustained aggregate throughput of 1.2 TB/s read and 800 GB/s write.
- Availability: at least 99.5% per calendar month across accepted GPUs.
- Maintenance: no more than eight hours per month and at least seven days' notice.
- Acceptance: 72 continuous hours of burn-in, serial-number and node inventory attestation, and an NCCL benchmark against a reference. The reference cluster, workload, and pass threshold remain open and must be agreed before signing.
- Security: United States data residency, current SOC 2 Type II, customer-managed keys, exportable administrative and workload-access logs, and named-person physical access records for the GPU hall.

## procurement-follow-up.eml - August 7, 2026

- Firm demand remains 1,024 B200 SXM GPUs. The other 1,024 is only an expansion option.
- Controlling ramp: 512 GPUs by January 15, 2027 and the remaining 512 by February 1, 2027.
- Firm term: 18 months from first-tranche service, with one six-month extension option.
- $3.10/GPU-hour is the target, not the ceiling. The hard all-in cap is $3.35/GPU-hour excluding taxes. Operating pass-throughs must fit within that cap.
- Prepayment may not exceed three months of committed charges.
- Egress pricing remains open and needs a separate schedule.
- US East or US Midwest is acceptable; Virginia is preferred, not required. Customer data and the production cluster must remain in the United States.
- Hourly renewable matching is useful for reporting, not a condition to proceed.
- Open diligence: contracting entity, control of site and GPUs, hardware liens, and evidence for delivery dates. Network proof and the NCCL reference and pass threshold also remain open.

## Reproducible base-term calculation

- First tranche: 512 GPUs for January 15 through January 31, 2027.
- Full cluster: 1,024 GPUs from February 1, 2027 through July 14, 2028.
- Using 24 hours per day and an end boundary of July 15, 2028 gives 13,234,176 committed GPU-hours.
- At $3.10/GPU-hour: $41,025,945.60.
- At $3.35/GPU-hour: $44,334,489.60.
- A deposit dollar estimate requires an explicit monthly-hours and rate convention; otherwise it remains open.
