"""Build Prime offer-history, event, reference, and ladder Gold products."""

from __future__ import annotations

from typing import Any

from .datafusion import DataFusionEngine
from .offer_reference import (
    build_prime_frontier_offer_events,
    normalize_prime_frontier_history,
    prime_frontier_ladder_sql,
    prime_frontier_reference_history_sql,
)
from .storage import table_partition, write_parquet_rows


PRIME_FRONTIER_GOLD_TABLES = {
    "fact_prime_frontier_offer_history": "prime_frontier_offer_history.parquet",
    "fact_prime_frontier_offer_events": "prime_frontier_offer_events.parquet",
    "fact_prime_frontier_offer_reference_history": (
        "prime_frontier_offer_reference_history.parquet"
    ),
    "fact_prime_frontier_offer_ladder": "prime_frontier_offer_ladder.parquet",
}


def build_prime_frontier_gold_products(
    *,
    lake_root: str,
    previous_gold_manifest: dict[str, Any],
    current_listing_rows: list[dict[str, Any]],
    observed_date: str,
    gold_run_id: str,
    benchmark_values_ref: str,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    previous_history_ref = previous_gold_manifest.get("table_refs", {}).get(
        "fact_prime_frontier_offer_history"
    )
    historical_rows: list[dict[str, Any]] = []
    if previous_history_ref:
        historical_rows = DataFusionEngine(
            {"fact_prime_frontier_offer_history": str(previous_history_ref)}
        ).query("select * from fact_prime_frontier_offer_history")
    offer_history = normalize_prime_frontier_history(
        [
            *historical_rows,
            *[
                {
                    **row,
                    "gold_run_id": gold_run_id,
                    "gold_observed_at": row.get("observed_at")
                    or row.get("calculated_at"),
                    "gold_observed_date": observed_date,
                }
                for row in current_listing_rows
            ],
        ]
    )
    if not offer_history:
        return {}, {}

    refs = {
        table_name: table_partition(
            lake_root,
            table=f"gold/{table_name}",
            observed_date=observed_date,
            provider=None,
            run_id=gold_run_id,
            filename=filename,
        )
        for table_name, filename in PRIME_FRONTIER_GOLD_TABLES.items()
    }
    rows_by_table: dict[str, list[dict[str, Any]]] = {
        "fact_prime_frontier_offer_history": offer_history,
    }
    write_parquet_rows(refs["fact_prime_frontier_offer_history"], offer_history)
    engine = DataFusionEngine(
        {"fact_prime_frontier_offer_history": refs["fact_prime_frontier_offer_history"]}
    )

    events = build_prime_frontier_offer_events(offer_history)
    rows_by_table["fact_prime_frontier_offer_events"] = events
    if events:
        write_parquet_rows(refs["fact_prime_frontier_offer_events"], events)
    else:
        refs.pop("fact_prime_frontier_offer_events")

    reference_history = engine.query(prime_frontier_reference_history_sql())
    rows_by_table["fact_prime_frontier_offer_reference_history"] = reference_history
    if not reference_history:
        refs.pop("fact_prime_frontier_offer_reference_history")
        rows_by_table["fact_prime_frontier_offer_ladder"] = []
        refs.pop("fact_prime_frontier_offer_ladder")
        return rows_by_table, refs
    write_parquet_rows(
        refs["fact_prime_frontier_offer_reference_history"],
        reference_history,
    )
    engine.register_tables(
        {
            "fact_prime_frontier_offer_reference_history": refs[
                "fact_prime_frontier_offer_reference_history"
            ]
        }
    )

    if not events:
        rows_by_table["fact_prime_frontier_offer_ladder"] = []
        refs.pop("fact_prime_frontier_offer_ladder")
        return rows_by_table, refs
    engine.register_tables(
        {
            "fact_prime_frontier_offer_events": refs[
                "fact_prime_frontier_offer_events"
            ],
            "fact_benchmark_values": benchmark_values_ref,
        }
    )
    ladder = engine.query(prime_frontier_ladder_sql(current_gold_run_id=gold_run_id))
    rows_by_table["fact_prime_frontier_offer_ladder"] = ladder
    if ladder:
        write_parquet_rows(refs["fact_prime_frontier_offer_ladder"], ladder)
    else:
        refs.pop("fact_prime_frontier_offer_ladder")
    return rows_by_table, refs
