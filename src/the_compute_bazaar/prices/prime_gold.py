"""Build Prime offer-history, event, reference, and ladder Gold products."""

from __future__ import annotations

from typing import Any

from .datafusion import DataFusionEngine, TableRef
from .gold_sources import (
    history_seed_ref,
    retained_history_count,
    retained_history_refs,
)
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
    gold_observed_at: str,
    gpu_price_index_ref: TableRef,
) -> tuple[
    dict[str, list[dict[str, Any]]],
    dict[str, TableRef],
    dict[str, int],
]:
    previous_refs = dict(previous_gold_manifest.get("table_refs") or {})
    current_offers = normalize_prime_frontier_history(
        [
            {
                **row,
                "gold_run_id": gold_run_id,
                "gold_observed_at": row.get("observed_at") or row.get("calculated_at"),
                "gold_observed_date": observed_date,
            }
            for row in current_listing_rows
        ]
    )

    refs: dict[str, TableRef] = {
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
    counts: dict[str, int] = {}
    history_name = "fact_prime_frontier_offer_history"
    previous_history_ref = previous_refs.get(history_name)
    history_part_ref = str(refs[history_name])
    if history_seed_ref(previous_history_ref):
        previous_rows = DataFusionEngine(
            {history_name: history_seed_ref(previous_history_ref)}
        ).query(f"select * from {history_name}")
        history_part_rows = normalize_prime_frontier_history(
            [*previous_rows, *current_offers]
        )
    else:
        history_part_rows = current_offers
    if not history_part_rows and not previous_history_ref:
        return {}, {}, {}
    if history_part_rows:
        write_parquet_rows(history_part_ref, history_part_rows)
    refs[history_name] = retained_history_refs(
        previous_history_ref,
        history_part_ref,
        part_written=bool(history_part_rows),
    )
    counts[history_name] = retained_history_count(
        previous_gold_manifest,
        history_name,
        previous_history_ref,
        history_part_ref,
        history_part_rows,
    )
    rows_by_table: dict[str, list[dict[str, Any]]] = {history_name: history_part_rows}
    history_engine = DataFusionEngine({history_name: refs[history_name]})

    events_name = "fact_prime_frontier_offer_events"
    previous_events_ref = previous_refs.get(events_name)
    events_part_ref = str(refs[events_name])
    if history_seed_ref(previous_events_ref):
        event_input = history_engine.query(f"select * from {history_name}")
        events_part_rows = build_prime_frontier_offer_events(
            event_input,
            snapshot_keys=[(gold_observed_at, gold_run_id)],
        )
    else:
        previous_snapshot = _snapshot_for_run(
            previous_history_ref,
            str(previous_gold_manifest.get("run_id") or ""),
        )
        events_part_rows = [
            event
            for event in build_prime_frontier_offer_events(
                [*previous_snapshot, *current_offers],
                snapshot_keys=[(gold_observed_at, gold_run_id)],
            )
            if str(event.get("gold_run_id") or "") == gold_run_id
        ]
    rows_by_table[events_name] = events_part_rows
    if events_part_rows:
        write_parquet_rows(events_part_ref, events_part_rows)
    refs[events_name] = retained_history_refs(
        previous_events_ref,
        events_part_ref,
        part_written=bool(events_part_rows),
    )
    counts[events_name] = retained_history_count(
        previous_gold_manifest,
        events_name,
        previous_events_ref,
        events_part_ref,
        events_part_rows,
    )
    if not refs[events_name]:
        refs.pop(events_name)

    reference_name = "fact_prime_frontier_offer_reference_history"
    previous_reference_ref = previous_refs.get(reference_name)
    reference_part_ref = str(refs[reference_name])
    if history_seed_ref(previous_reference_ref):
        reference_source = history_engine
    elif current_offers:
        reference_source = DataFusionEngine({history_name: history_part_ref})
    else:
        reference_source = None
    reference_part_rows = (
        reference_source.query(prime_frontier_reference_history_sql())
        if reference_source
        else []
    )
    rows_by_table[reference_name] = reference_part_rows
    if reference_part_rows:
        write_parquet_rows(reference_part_ref, reference_part_rows)
    refs[reference_name] = retained_history_refs(
        previous_reference_ref,
        reference_part_ref,
        part_written=bool(reference_part_rows),
    )
    counts[reference_name] = retained_history_count(
        previous_gold_manifest,
        reference_name,
        previous_reference_ref,
        reference_part_ref,
        reference_part_rows,
    )
    if not refs[reference_name]:
        refs.pop(reference_name)
        rows_by_table["fact_prime_frontier_offer_ladder"] = []
        refs.pop("fact_prime_frontier_offer_ladder")
        return rows_by_table, refs, counts

    if not refs.get(events_name) or not current_offers:
        rows_by_table["fact_prime_frontier_offer_ladder"] = []
        refs.pop("fact_prime_frontier_offer_ladder")
        return rows_by_table, refs, counts
    ladder_engine = DataFusionEngine(
        {
            history_name: refs[history_name],
            reference_name: refs[reference_name],
            events_name: refs[events_name],
            "fact_gpu_price_index": gpu_price_index_ref,
        }
    )
    ladder = ladder_engine.query(
        prime_frontier_ladder_sql(current_gold_run_id=gold_run_id)
    )
    rows_by_table["fact_prime_frontier_offer_ladder"] = ladder
    if ladder:
        write_parquet_rows(str(refs["fact_prime_frontier_offer_ladder"]), ladder)
    else:
        refs.pop("fact_prime_frontier_offer_ladder")
    return rows_by_table, refs, counts


def _snapshot_for_run(history_ref: Any, gold_run_id: str) -> list[dict[str, Any]]:
    if not history_ref or not gold_run_id:
        return []
    engine = DataFusionEngine({"history": history_ref})
    escaped_run_id = gold_run_id.replace("'", "''")
    return engine.query(f"""
select *
from history
where gold_run_id = '{escaped_run_id}'
""")
