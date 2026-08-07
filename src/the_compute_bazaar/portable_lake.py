"""Build and publish a credential-free portable market lake."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from .contracts import (
    GOLD_MARKET_CONTRACT,
    GPU_OFFERS_RUN_CONTRACT,
    PORTABLE_LAKE_CONTRACT,
)
from .prices.gold_manifest import (
    GOLD_MANIFEST_TABLE,
    gold_manifest_ref,
    latest_gold_manifest_ref,
    read_latest_gold_manifest,
)
from .prices.manifest import latest_manifest_ref
from .prices.schemas import to_jsonable
from .prices.storage import (
    read_json,
    read_parquet_rows,
    table_partition,
    write_bytes,
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


def build_portable_lake(
    *,
    source_lake_root: str,
    output_root: str,
) -> dict[str, Any]:
    """Materialize the public Silver/Gold contract without private evidence refs."""
    output = Path(output_root).resolve()
    if "://" not in source_lake_root and Path(source_lake_root).resolve() == output:
        raise ValueError("Portable-lake output must differ from its source lake")
    source_latest = read_latest_gold_manifest(source_lake_root)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    provider_scope = _supported_provider_scope(source_latest)
    _copy_latest_silver(
        source_manifest=source_latest,
        provider_scope=provider_scope,
        output_root=output,
    )
    table_refs, row_counts = _copy_latest_gold(
        source_manifest=source_latest,
        output_root=output,
    )
    if "fact_gpu_price_index_history" not in table_refs:
        raise RuntimeError("Gold manifest is missing fact_gpu_price_index_history")

    portable_manifest = _portable_gold_manifest(
        source_manifest=source_latest,
        output_root=output,
        provider_scope=provider_scope,
        table_refs=table_refs,
        row_counts=row_counts,
    )
    immutable_manifest_ref = gold_manifest_ref(
        str(output),
        observed_date=str(portable_manifest["observed_date"]),
        run_id=str(portable_manifest["run_id"]),
    )
    write_json(immutable_manifest_ref, portable_manifest)
    write_json(latest_gold_manifest_ref(str(output)), portable_manifest)
    _make_source_manifests_portable(output, provider_scope)

    metadata = {
        "contract": PORTABLE_LAKE_CONTRACT,
        "run_id": source_latest["run_id"],
        "observed_at": source_latest["observed_at"],
        "provider_scope": provider_scope,
        "history_row_count": row_counts.get("fact_gpu_price_index_history", 0),
        "history_mode": "complete",
        "private_evidence_removed": True,
    }
    write_json(str(output / "portable.json"), metadata)
    inventory = _write_inventory(output, metadata=metadata)
    return {**metadata, "file_count": inventory["file_count"]}


def publish_portable_lake(
    *,
    source_lake_root: str,
    output_root: str,
) -> dict[str, Any]:
    """Build locally, upload immutable files first, then publish the inventory."""
    with tempfile.TemporaryDirectory(prefix="compute-bazaar-public-lake-") as temp:
        local_root = Path(temp) / "lake"
        metadata = build_portable_lake(
            source_lake_root=source_lake_root,
            output_root=str(local_root),
        )
        paths = sorted(path for path in local_root.rglob("*") if path.is_file())
        paths.sort(key=lambda path: path.name == "index.json")
        for path in paths:
            relative = path.relative_to(local_root).as_posix()
            write_bytes(
                f"{output_root.rstrip('/')}/{relative}",
                path.read_bytes(),
                content_type=_content_type(path),
                cache_control=_cache_control(relative),
            )
    return {
        **metadata,
        "index_ref": f"{output_root.rstrip('/')}/index.json",
    }


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
        normalized_relative = f"silver/gpu_offers/{provider}/offers.parquet"
        manifest_relative = f"_manifests/gpu_offers/provider={provider}/latest.json"
        state_relative = f"silver/compute_market_state/{provider}/observations.parquet"
        source_run_id = source_run_ids.get(provider) or f"{provider}-portable"
        offer_rows = _sanitize_rows(read_parquet_rows(source_offer_refs[provider]))
        for row in offer_rows:
            row.update(
                {
                    "source_run_id": source_run_id,
                    "source_manifest_ref": manifest_relative,
                    "source_normalized_ref": normalized_relative,
                }
            )
        normalized_ref = output_root / normalized_relative
        write_parquet_rows(str(normalized_ref), offer_rows)

        state_ref: Path | None = None
        state_rows: list[dict[str, Any]] = []
        if provider in source_state_refs:
            state_rows = _sanitize_rows(read_parquet_rows(source_state_refs[provider]))
            for row in state_rows:
                row.update(
                    {
                        "source_run_id": source_run_id,
                        "source_manifest_ref": manifest_relative,
                        "source_normalized_ref": normalized_relative,
                        "source_market_state_ref": state_relative,
                    }
                )
            state_ref = output_root / state_relative
            write_parquet_rows(str(state_ref), state_rows)

        manifest_path = Path(latest_manifest_ref(str(output_root), provider=provider))
        write_json(
            str(manifest_path),
            {
                "contract": GPU_OFFERS_RUN_CONTRACT,
                "table": "gpu_offers",
                "provider": provider,
                "run_id": source_run_id,
                "observed_at": observed_at,
                "raw_ref": None,
                "normalized_ref": normalized_relative,
                "raw_offer_count": len(offer_rows),
                "normalized_offer_count": len(offer_rows),
                "published_events": 0,
                "publish_mode": "portable_lake",
                "unknown_gpu_names": [],
                "market_state_ref": (state_relative if state_ref else None),
                "market_state_observation_count": len(state_rows),
                "manifest_ref": _relative(output_root, str(manifest_path)),
                "ref_base": "lake_root",
            },
        )


def _copy_latest_gold(
    *,
    source_manifest: dict[str, Any],
    output_root: Path,
) -> tuple[dict[str, str], dict[str, int]]:
    table_refs: dict[str, str] = {}
    row_counts: dict[str, int] = {}
    observed_date = str(source_manifest["observed_date"])
    run_id = str(source_manifest["run_id"])
    for table_name, source_ref in dict(source_manifest.get("table_refs") or {}).items():
        rows = _portableize_lineage(
            _sanitize_rows(read_parquet_rows(str(source_ref))),
            output_root=output_root,
        )
        filename = PurePosixPath(urlparse(str(source_ref)).path).name
        target_ref = table_partition(
            str(output_root),
            table=f"gold/{table_name}",
            observed_date=observed_date,
            provider=None,
            run_id=run_id,
            filename=filename or f"{table_name}.parquet",
        )
        write_parquet_rows(target_ref, rows)
        table_refs[str(table_name)] = target_ref
        row_counts[str(table_name)] = len(rows)
    return table_refs, row_counts

def _portable_gold_manifest(
    *,
    source_manifest: dict[str, Any],
    output_root: Path,
    provider_scope: list[str],
    table_refs: dict[str, str],
    row_counts: dict[str, int],
) -> dict[str, Any]:
    manifest = {
        key: value
        for key, value in source_manifest.items()
        if key
        not in {
            "manifest_ref",
            "source_manifest_refs",
            "source_normalized_refs",
            "source_market_state_refs",
            "table_refs",
            "row_counts",
        }
    }
    manifest["contract"] = GOLD_MARKET_CONTRACT
    manifest["table"] = GOLD_MANIFEST_TABLE
    manifest["ref_base"] = "lake_root"
    manifest["provider_scope"] = provider_scope
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
        name: _relative(output_root, ref) for name, ref in table_refs.items()
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
        manifest["normalized_ref"] = f"silver/gpu_offers/{provider}/offers.parquet"
        manifest["manifest_ref"] = _relative(output_root, ref)
        write_json(ref, manifest)


def _write_inventory(
    output_root: Path,
    *,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    files = []
    for path in sorted(output_root.rglob("*")):
        if not path.is_file() or path.name == "index.json":
            continue
        payload = path.read_bytes()
        files.append(
            {
                "path": path.relative_to(output_root).as_posix(),
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    inventory = {
        "contract": PORTABLE_LAKE_CONTRACT,
        "run_id": metadata["run_id"],
        "observed_at": metadata["observed_at"],
        "provider_scope": metadata["provider_scope"],
        "history_mode": metadata["history_mode"],
        "file_count": len(files),
        "files": files,
    }
    write_json(str(output_root / "index.json"), inventory)
    return inventory


def _supported_provider_scope(manifest: dict[str, Any]) -> list[str]:
    refs = dict(manifest.get("source_normalized_refs") or {})
    scope = [
        str(provider)
        for provider in manifest.get("provider_scope") or []
        if provider in refs
    ]
    if not scope:
        raise RuntimeError("Source manifest has no supported provider observations")
    return scope


def _sanitize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_sanitize_mapping(row) for row in rows]


def _portableize_lineage(
    rows: list[dict[str, Any]], *, output_root: Path
) -> list[dict[str, Any]]:
    for row in rows:
        connector = str(row.get("source_connector") or "")
        if not connector:
            continue
        if "source_manifest_ref" in row:
            row["source_manifest_ref"] = (
                f"_manifests/gpu_offers/provider={connector}/latest.json"
            )
        if "source_normalized_ref" in row:
            row["source_normalized_ref"] = (
                f"silver/gpu_offers/{connector}/offers.parquet"
            )
        if "source_market_state_ref" in row:
            relative = f"silver/compute_market_state/{connector}/observations.parquet"
            row["source_market_state_ref"] = (
                relative if (output_root / relative).is_file() else None
            )
    return rows


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


def _content_type(path: Path) -> str:
    if path.suffix == ".json":
        return "application/json"
    if path.suffix == ".parquet":
        return "application/vnd.apache.parquet"
    return "application/octet-stream"


def _cache_control(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    if path.parts[0] == "gold" or (
        path.parts[:2] == ("_manifests", "gold_market") and path.name != "latest.json"
    ):
        return "public, max-age=31536000, immutable"
    return "public, max-age=60, must-revalidate"


def _relative(root: Path, ref: str) -> str:
    return Path(ref).resolve().relative_to(root).as_posix()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-lake-root", required=True)
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--output-root")
    destination.add_argument("--publish-output-root")
    args = parser.parse_args()
    if args.publish_output_root:
        result = publish_portable_lake(
            source_lake_root=args.source_lake_root,
            output_root=args.publish_output_root,
        )
    else:
        result = build_portable_lake(
            source_lake_root=args.source_lake_root,
            output_root=args.output_root,
        )
    print(json.dumps(to_jsonable(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
