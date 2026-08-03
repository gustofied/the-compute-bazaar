# Project Northlink Technical Requirements

Approved: 2026-07-18

## Compute

- 512 NVIDIA B200 GPUs.
- 64 HGX B200 nodes with eight B200 GPUs per node.
- One operational cluster; substitute GPU models are not acceptable.

## Site and data

- The site must be inside the European Economic Area.
- Northstar workload data, logs, and support copies must remain inside the EEA.

## Fabric

- 400 Gb/s InfiniBand connectivity to each compute node.
- Non-blocking 1:1 fabric across all 64 nodes. Leaf-level line rate does not
  satisfy the requirement if the core is oversubscribed.

## Cooling and service

- The liquid-cooling system must be commissioned for all 64 nodes before the
  workload-ready date.
- Monthly service availability must be at least 99.9%, excluding only the
  maintenance exclusions stated in the final order.
