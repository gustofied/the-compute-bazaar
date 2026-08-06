"""Build the credential-free public sample lake from an archived market lake."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .data_root import bundled_sample_lake_root
from .prices.datafusion import DataFusionEngine
from .prices.gold import build_gold_market_tables
from .prices.gold_manifest import (
    GOLD_MANIFEST_TABLE,
    GOLD_MANIFEST_VERSION,
    gold_manifest_prefix,
    gold_manifest_ref,
    is_canonical_market_run_id,
    latest_gold_manifest_ref,
)
from .prices.gold_models import gold_model_sql, gold_sql_models
from .prices.gold_sources import silver_source_cte, source_catalog_values
from .prices.manifest import latest_manifest_ref
from .prices.provider_registry import PROVIDERS
from .prices.schemas import to_jsonable
from .prices.storage import (
    list_refs,
    read_json,
    read_parquet_rows,
    table_partition,
    write_json,
    write_parquet_rows,
)


PRIVATE_REF_FIELDS = {
    "manifest_ref",
    "raw_ref",
    "source_manifest_ref",
    "source_market_state_ref",
    "source_normalized_ref",
}


def build_public_sample_lake(
    *,
    source_lake_root: str,
    output_root: str = bundled_sample_lake_root(),
    history_limit: int = 24,
) -> dict[str, Any]:
    source_latest = dict(read_json(latest_gold_manifest_ref(source_lake_root)))
    output = Path(output_root).resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    provider_scope = _supported_provider_scope(source_latest)
    _copy_latest_silver(
        source_manifest=source_latest,
        provider_scope=provider_scope,
        output_root=output,
    )
    observed_at = str(source_latest["observed_at"])
    build = build_gold_market_tables(
        lake_root=str(output),
        providers=provider_scope,
        run_id=str(source_latest["run_id"]),
        calculated_at=observed_at,
        manifest_observed_at=observed_at,
    )
    _restore_market_state_history(
        source_manifest=source_latest,
        table_refs=build.table_refs,
    )
    row_counts = _sanitize_gold_tables(build.table_refs)
    latest_manifest = _make_latest_manifest_portable(
        manifest=dict(read_json(build.manifest_ref)),
        output_root=output,
        row_counts=row_counts,
    )
    write_json(build.manifest_ref, latest_manifest)
    write_json(latest_gold_manifest_ref(str(output)), latest_manifest)
    _make_source_manifests_portable(output, provider_scope)

    history_manifests = _source_history(
        source_lake_root=source_lake_root,
        latest_observed_at=observed_at,
        limit=history_limit,
    )
    written_history = 0
    for source_manifest in history_manifests:
        if source_manifest.get("run_id") == source_latest.get("run_id"):
            written_history += 1
            continue
        _write_historical_price_index(
            source_manifest=source_manifest,
            output_root=output,
        )
        written_history += 1

    metadata = {
        "sample_type": "sanitized_public_market_snapshot",
        "run_id": source_latest["run_id"],
        "observed_at": observed_at,
        "provider_scope": provider_scope,
        "history_run_count": written_history,
        "private_evidence_removed": True,
    }
    write_json(str(output / "sample.json"), metadata)
    return metadata


def _copy_latest_silver(
    *,
    source_manifest: dict[str, Any],
    provider_scope: list[str],
    output_root: Path,
) -> None:
    source_offer_refs = dict(source_manifest.get("source_normalized_refs") or {})
    source_state_refs = dict(source_manifest.get("source_market_state_refs") or {})
    source_run_ids = dict(source_manifest.get("source_run_ids") or {})
    observed_at = str(source_manifest["observed_at"])

    for provider in provider_scope:
        offer_rows = _sanitize_rows(read_parquet_rows(source_offer_refs[provider]))
        normalized_ref = output_root / "silver" / "gpu_offers" / provider / "offers.parquet"
        write_parquet_rows(str(normalized_ref), offer_rows)

        state_ref: Path | None = None
        if provider in source_state_refs:
            state_rows = _sanitize_rows(
                read_parquet_rows(source_state_refs[provider])
            )
            state_ref = (
                output_root
                / "silver"
                / "compute_market_state"
                / provider
                / "observations.parquet"
            )
            write_parquet_rows(str(state_ref), state_rows)

        manifest_path = Path(
            latest_manifest_ref(str(output_root), provider=provider)
        )
        payload = {
            "manifest_version": "v1",
            "table": "gpu_offers",
            "provider": provider,
            "run_id": source_run_ids.get(provider) or f"{provider}-sample",
            "observed_at": observed_at,
            "raw_ref": None,
            "normalized_ref": str(normalized_ref),
            "raw_offer_count": len(offer_rows),
            "normalized_offer_count": len(offer_rows),
            "published_events": 0,
            "publish_mode": "bundled_sample",
            "unknown_gpu_names": [],
            "market_state_ref": str(state_ref) if state_ref else None,
            "market_state_observation_count": (
                len(state_rows) if state_ref else 0
            ),
            "manifest_ref": str(manifest_path),
        }
        write_json(str(manifest_path), payload)


def _restore_market_state_history(
    *,
    source_manifest: dict[str, Any],
    table_refs: dict[str, str],
) -> None:
    source_ref = source_manifest.get("table_refs", {}).get(
        "fact_compute_market_state_history"
    )
    if not source_ref:
        return
    history_rows = _sanitize_rows(read_parquet_rows(str(source_ref)))
    history_ref = table_refs["fact_compute_market_state_history"]
    write_parquet_rows(history_ref, history_rows)
    engine = DataFusionEngine({"fact_compute_market_state_history": history_ref})
    gpu_rows = engine.query(
        gold_model_sql(
            "fact_gpu_availability_history",
            fragments={"source_table": "fact_compute_market_state_history"},
        )
    )
    write_parquet_rows(
        table_refs["fact_gpu_availability_history"],
        _sanitize_rows(gpu_rows),
    )


def _sanitize_gold_tables(table_refs: dict[str, str]) -> dict[str, int]:
    row_counts: dict[str, int] = {}
    for table_name, table_ref in table_refs.items():
        rows = _sanitize_rows(read_parquet_rows(table_ref))
        write_parquet_rows(table_ref, rows)
        row_counts[table_name] = len(rows)
    return row_counts


def _make_latest_manifest_portable(
    *,
    manifest: dict[str, Any],
    output_root: Path,
    row_counts: dict[str, int],
) -> dict[str, Any]:
    provider_scope = list(manifest.get("provider_scope") or [])
    manifest["ref_base"] = "lake_root"
    manifest["source_manifest_refs"] = {
        provider: _relative(
            output_root,
            latest_manifest_ref(str(output_root), provider=provider),
        )
        for provider in provider_scope
    }
    manifest["source_normalized_refs"] = {
        provider: f"silver/gpu_offers/{provider}/offers.parquet"
        for provider in provider_scope
    }
    manifest["source_market_state_refs"] = {
        provider: f"silver/compute_market_state/{provider}/observations.parquet"
        for provider in provider_scope
        if (
            output_root
            / "silver"
            / "compute_market_state"
            / provider
            / "observations.parquet"
        ).is_file()
    }
    manifest["table_refs"] = {
        name: _relative(output_root, ref)
        for name, ref in dict(manifest.get("table_refs") or {}).items()
    }
    manifest["row_counts"] = row_counts
    manifest["manifest_ref"] = _relative(
        output_root,
        gold_manifest_ref(
            str(output_root),
            observed_date=str(manifest["observed_date"]),
            run_id=str(manifest["run_id"]),
        ),
    )
    return manifest


def _make_source_manifests_portable(
    output_root: Path,
    provider_scope: list[str],
) -> None:
    for provider in provider_scope:
        ref = latest_manifest_ref(str(output_root), provider=provider)
        manifest = dict(read_json(ref))
        manifest["ref_base"] = "lake_root"
        manifest["normalized_ref"] = f"silver/gpu_offers/{provider}/offers.parquet"
        state_path = (
            output_root
            / "silver"
            / "compute_market_state"
            / provider
            / "observations.parquet"
        )
        manifest["market_state_ref"] = (
            f"silver/compute_market_state/{provider}/observations.parquet"
            if state_path.is_file()
            else None
        )
        manifest["manifest_ref"] = _relative(output_root, ref)
        write_json(ref, manifest)


def _source_history(
    *,
    source_lake_root: str,
    latest_observed_at: str,
    limit: int,
) -> list[dict[str, Any]]:
    latest_time = _parse_time(latest_observed_at)
    manifests: list[dict[str, Any]] = []
    refs = sorted(
        ref
        for ref in list_refs(gold_manifest_prefix(source_lake_root), suffix=".json")
        if "/run_id=" in ref or "/run_id%3D" in ref
    )
    for ref in reversed(refs):
        manifest = dict(read_json(ref))
        if not is_canonical_market_run_id(manifest.get("run_id")):
            continue
        if _parse_time(str(manifest.get("observed_at") or "")) > latest_time:
            continue
        if not manifest.get("source_normalized_refs"):
            continue
        manifests.append(manifest)
        if len(manifests) >= max(1, limit):
            break
    return list(reversed(manifests))


def _write_historical_price_index(
    *,
    source_manifest: dict[str, Any],
    output_root: Path,
) -> None:
    provider_scope = _supported_provider_scope(source_manifest)
    refs = dict(source_manifest["source_normalized_refs"])
    source_run_ids = dict(source_manifest.get("source_run_ids") or {})
    run_id = str(source_manifest["run_id"])
    observed_at = str(source_manifest["observed_at"])
    observed_date = str(source_manifest.get("observed_date") or observed_at[:10])
    tables = {
        f"silver_gpu_offers_{index}": str(refs[provider])
        for index, provider in enumerate(provider_scope)
    }
    engine = DataFusionEngine(tables)
    context = {
        "source_run_id": ",".join(
            f"{provider}:{source_run_ids.get(provider, run_id)}"
            for provider in provider_scope
        ),
        "source_manifest_ref": "bundled-public-sample",
        "source_raw_ref": "bundled-public-sample",
        "source_normalized_ref": "bundled-public-sample",
        "source_market_state_ref": "bundled-public-sample",
        "gold_run_id": run_id,
        "gold_observed_date": observed_date,
        "calculated_at": observed_at,
    }
    source_cte = silver_source_cte(list(tables))
    listings = engine.query(
        gold_model_sql(
            "fact_gpu_listings",
            context,
            fragments={
                "silver_source_cte": source_cte,
                "source_catalog_values": source_catalog_values(provider_scope),
            },
        )
    )

    with tempfile.TemporaryDirectory() as temporary_directory:
        listings_ref = str(Path(temporary_directory) / "listings.parquet")
        constituents_ref = str(Path(temporary_directory) / "constituents.parquet")
        write_parquet_rows(listings_ref, listings)
        model_engine = DataFusionEngine({"fact_gpu_listings": listings_ref})
        constituents = model_engine.query(
            gold_model_sql("fact_gpu_price_index_constituents", context)
        )
        write_parquet_rows(constituents_ref, constituents)
        model_engine.register_tables(
            {"fact_gpu_price_index_constituents": constituents_ref}
        )
        rows = _sanitize_rows(
            model_engine.query(gold_model_sql("fact_gpu_price_index", context))
        )

    table_ref = table_partition(
        str(output_root),
        table="gold/fact_gpu_price_index",
        observed_date=observed_date,
        provider=None,
        run_id=run_id,
        filename="gpu_price_index.parquet",
    )
    write_parquet_rows(table_ref, rows)
    manifest_ref = gold_manifest_ref(
        str(output_root), observed_date=observed_date, run_id=run_id
    )
    payload = {
        "manifest_version": GOLD_MANIFEST_VERSION,
        "table": GOLD_MANIFEST_TABLE,
        "methodology_version": "gold_gpu_market_v4",
        "ref_base": "lake_root",
        "provider_scope": provider_scope,
        "run_id": run_id,
        "observed_at": observed_at,
        "observed_date": observed_date,
        "source_run_ids": {
            provider: source_run_ids.get(provider) for provider in provider_scope
        },
        "source_manifest_refs": {},
        "source_normalized_refs": {},
        "source_market_state_refs": {},
        "table_refs": {
            "fact_gpu_price_index": _relative(output_root, table_ref)
        },
        "row_counts": {"fact_gpu_price_index": len(rows)},
        "sql_models": gold_sql_models(["fact_gpu_price_index"]),
        "manifest_ref": _relative(output_root, manifest_ref),
    }
    write_json(manifest_ref, payload)


def _supported_provider_scope(manifest: dict[str, Any]) -> list[str]:
    known = {provider.name for provider in PROVIDERS}
    refs = dict(manifest.get("source_normalized_refs") or {})
    scope = [
        str(provider)
        for provider in manifest.get("provider_scope") or []
        if provider in known and provider in refs
    ]
    if not scope:
        raise RuntimeError("Source manifest has no supported provider observations")
    return scope


def _sanitize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_sanitize_mapping(row) for row in rows]


def _sanitize_mapping(row: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in row.items():
        if key in PRIVATE_REF_FIELDS:
            sanitized[key] = None
        elif key == "has_raw_evidence":
            sanitized[key] = False
        elif key == "metadata":
            continue
        else:
            sanitized[key] = _sanitize_value(value)
    return sanitized


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _sanitize_mapping(value)
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str) and value.startswith("s3://"):
        return None
    return value


def _relative(root: Path, ref: str) -> str:
    return Path(ref).resolve().relative_to(root).as_posix()


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-lake-root", required=True)
    parser.add_argument("--output-root", default=bundled_sample_lake_root())
    parser.add_argument("--history-limit", type=int, default=24)
    args = parser.parse_args()
    result = build_public_sample_lake(
        source_lake_root=args.source_lake_root,
        output_root=args.output_root,
        history_limit=args.history_limit,
    )
    print(json.dumps(to_jsonable(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
