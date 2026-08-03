# Project Northlink Fabric Design

Approved by Aurora Network Engineering: 2026-07-21

## Node edge

Each of the 64 HGX B200 nodes receives 400 Gb/s InfiniBand connectivity.
The leaf layer is line-rate and non-blocking within each 16-node pod.

## Core

The currently quoted design has aggregate 2:1 oversubscription between the
four leaf pods and the spine layer. Traffic crossing pods therefore does not
receive a non-blocking 1:1 path.

Four additional spine switches would produce a 1:1 fabric across all 64 nodes.
Those switches are not included in the current offer or price schedule.
