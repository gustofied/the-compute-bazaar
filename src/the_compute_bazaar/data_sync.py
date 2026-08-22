"""Download and inspect the public market lake."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from .contracts import MARKET_LAKE_CONTRACT, require_contract
from .data_root import default_synced_lake_root
from .prices.gold_manifest import read_latest_gold_manifest


DEFAULT_PUBLIC_LAKE_URL = (
    "https://github.com/gustofied/the-compute-bazaar/"
    "releases/download/public-lake"
)
ASSET_NAME_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_LAKE_BYTES = 1024 * 1024 * 1024


def sync_public_lake(
    *,
    base_url: str = DEFAULT_PUBLIC_LAKE_URL,
    output_root: str | None = None,
) -> dict[str, Any]:
    """Download a checksummed lake generation and replace the cache atomically."""
    source_url = base_url.rstrip("/")
    destination = Path(output_root or default_synced_lake_root()).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)

    index_bytes = _download(f"{source_url}/index.json")
    index = _validated_index(index_bytes)
    if _generation_matches(destination, index=index):
        _write_sync_metadata(destination, source_url=source_url)
        return {
            "status": "current",
            "root": str(destination),
            "source_url": source_url,
            "run_id": index["run_id"],
            "observed_at": index["observed_at"],
            "providers": index["provider_scope"],
            "history_mode": index.get("history_mode"),
            "file_count": index["file_count"],
            "downloaded_bytes": 0,
        }

    staging = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent)
    )
    backup = destination.with_name(f".{destination.name}.previous")
    downloaded_bytes = 0
    try:
        distribution = index.get("distribution")
        if distribution:
            downloaded_bytes = _download_release_archive(
                source_url=source_url,
                staging=staging,
                index=index,
                distribution=distribution,
            )
        else:
            downloaded_bytes = _download_exploded_lake(
                source_url=source_url,
                source_cache=destination,
                staging=staging,
                index=index,
            )

        (staging / "index.json").write_bytes(index_bytes)
        _write_sync_metadata(staging, source_url=source_url)
        _validate_generation(staging, index=index)

        if backup.exists():
            shutil.rmtree(backup)
        if destination.exists():
            destination.replace(backup)
        staging.replace(destination)
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        if backup.exists() and not destination.exists():
            backup.replace(destination)
        raise

    return {
        "status": "synced",
        "root": str(destination),
        "source_url": source_url,
        "run_id": index["run_id"],
        "observed_at": index["observed_at"],
        "providers": index["provider_scope"],
        "history_mode": index.get("history_mode"),
        "file_count": index["file_count"],
        "downloaded_bytes": downloaded_bytes,
    }


def _download_exploded_lake(
    *,
    source_url: str,
    source_cache: Path,
    staging: Path,
    index: dict[str, Any],
) -> int:
    downloaded_bytes = 0
    for item in index["files"]:
        relative = _safe_relative_path(item["path"])
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if _reuse_cached_file(source_cache / relative, target, item=item):
            continue
        payload = _download(
            f"{source_url}/{quote(relative.as_posix(), safe='/=._-')}"
        )
        _validate_payload(payload, item=item, label=relative.as_posix())
        target.write_bytes(payload)
        downloaded_bytes += len(payload)
    return downloaded_bytes


def _download_release_archive(
    *,
    source_url: str,
    staging: Path,
    index: dict[str, Any],
    distribution: Any,
) -> int:
    archive = _validated_distribution(distribution)
    archive_path = staging.parent / f".{staging.name}.zip"
    try:
        downloaded_bytes = _download_to_file(
            f"{source_url}/{quote(archive['asset'], safe='._-')}",
            archive_path,
            expected_size=archive["size"],
            expected_sha256=archive["sha256"],
        )
        expected = {str(item["path"]): item for item in index["files"]}
        with zipfile.ZipFile(archive_path) as bundle:
            members = bundle.infolist()
            names = [member.filename for member in members]
            if len(names) != len(set(names)) or set(names) != set(expected):
                raise RuntimeError("Portable lake archive does not match its inventory")
            for member in members:
                relative = _safe_relative_path(member.filename)
                item = expected[relative.as_posix()]
                if member.is_dir() or member.file_size != item["size"]:
                    raise RuntimeError(
                        f"Size mismatch for {relative.as_posix()} in release archive"
                    )
                payload = bundle.read(member)
                _validate_payload(
                    payload,
                    item=item,
                    label=f"{relative.as_posix()} in release archive",
                )
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
        return downloaded_bytes
    except zipfile.BadZipFile as exc:
        raise RuntimeError("Public market lake release is not a valid zip archive") from exc
    finally:
        archive_path.unlink(missing_ok=True)


def _validate_payload(payload: bytes, *, item: dict[str, Any], label: str) -> None:
    if len(payload) != item["size"]:
        raise RuntimeError(f"Size mismatch for {label}")
    if hashlib.sha256(payload).hexdigest() != item["sha256"]:
        raise RuntimeError(f"Checksum mismatch for {label}")


def _reuse_cached_file(
    source: Path,
    target: Path,
    *,
    item: dict[str, Any],
) -> bool:
    if not source.is_file() or source.stat().st_size != item["size"]:
        return False
    with source.open("rb") as handle:
        checksum = hashlib.file_digest(handle, "sha256").hexdigest()
    if checksum != item["sha256"]:
        return False
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)
    return True


def _generation_matches(root: Path, *, index: dict[str, Any]) -> bool:
    if not root.is_dir():
        return False
    try:
        if _validated_index((root / "index.json").read_bytes()) != index:
            return False
        for item in index["files"]:
            target = root / _safe_relative_path(item["path"])
            if not target.is_file() or target.stat().st_size != item["size"]:
                return False
            with target.open("rb") as handle:
                checksum = hashlib.file_digest(handle, "sha256").hexdigest()
            if checksum != item["sha256"]:
                return False
        _validate_generation(root, index=index)
    except Exception:
        return False
    return True


def _write_sync_metadata(root: Path, *, source_url: str) -> None:
    (root / ".sync.json").write_text(
        json.dumps(
            {
                "source_url": source_url,
                "synced_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def inspect_lake(*, root: str, kind: str, label: str) -> dict[str, Any]:
    """Describe the local lake selected by the CLI without making a network call."""
    path = None if "://" in root else Path(root)
    if (
        path is not None
        and not (path / "_manifests" / "gold_market" / "latest.json").is_file()
    ):
        result = {
            "status": "missing",
            "kind": kind,
            "label": label,
            "root": root,
        }
        if kind == "public_cache":
            result.update(
                source_url=DEFAULT_PUBLIC_LAKE_URL,
                next_command="compute-bazaar data sync",
            )
        return result

    index = _read_mapping(path / "index.json") if path and path.is_dir() else {}
    sync = _read_mapping(path / ".sync.json") if path and path.is_dir() else {}
    portable = _read_mapping(path / "portable.json") if path and path.is_dir() else {}
    for payload in (index, portable):
        if payload and payload.get("contract") != MARKET_LAKE_CONTRACT:
            result = {
                "status": "incompatible",
                "kind": kind,
                "label": label,
                "root": root,
                "contract": payload.get("contract"),
            }
            if kind == "public_cache":
                result.update(
                    source_url=DEFAULT_PUBLIC_LAKE_URL,
                    next_command="compute-bazaar data sync",
                )
            return result

    manifest = read_latest_gold_manifest(root)
    observed_at = str(manifest.get("observed_at") or "")
    return {
        "status": "ready",
        "kind": kind,
        "label": label,
        "root": root,
        "run_id": manifest.get("run_id"),
        "observed_at": observed_at,
        "age_hours": _age_hours(observed_at),
        "providers": manifest.get("provider_scope") or [],
        "published_tables": len(manifest.get("table_refs") or {}),
        "file_count": index.get("file_count"),
        "history_mode": portable.get("history_mode"),
        "source_url": sync.get("source_url"),
        "synced_at": sync.get("synced_at"),
    }


def _download(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "compute-bazaar-data-sync"})
    with urlopen(request, timeout=60) as response:
        payload = response.read(MAX_FILE_BYTES + 1)
    if len(payload) > MAX_FILE_BYTES:
        raise RuntimeError(f"Portable lake file exceeds the download budget: {url}")
    return payload


def _download_to_file(
    url: str,
    destination: Path,
    *,
    expected_size: int,
    expected_sha256: str,
) -> int:
    request = Request(url, headers={"User-Agent": "compute-bazaar-data-sync"})
    checksum = hashlib.sha256()
    downloaded = 0
    with urlopen(request, timeout=60) as response, destination.open("wb") as target:
        while chunk := response.read(1024 * 1024):
            downloaded += len(chunk)
            if downloaded > MAX_LAKE_BYTES:
                raise RuntimeError("Public market lake release exceeds the download budget")
            checksum.update(chunk)
            target.write(chunk)
    if downloaded != expected_size:
        raise RuntimeError("Public market lake release has an unexpected size")
    if checksum.hexdigest() != expected_sha256:
        raise RuntimeError("Public market lake release checksum does not match")
    return downloaded


def _validate_generation(staging: Path, *, index: dict[str, Any]) -> None:
    required_paths = {
        "portable.json",
        "_manifests/gold_market/latest.json",
    }
    indexed_paths = {str(item["path"]) for item in index["files"]}
    missing = sorted(required_paths - indexed_paths)
    if missing:
        raise RuntimeError(
            f"Portable lake inventory is missing required file: {missing[0]}"
        )

    manifest = read_latest_gold_manifest(str(staging))
    portable = _read_mapping(staging / "portable.json")
    require_contract(portable, contract=MARKET_LAKE_CONTRACT)

    run_ids = {
        str(index.get("run_id") or ""),
        str(portable.get("run_id") or ""),
        str(manifest.get("run_id") or ""),
    }
    if "" in run_ids or len(run_ids) != 1:
        raise RuntimeError("Portable lake generation contains mixed run identities")

    index_providers = [str(value) for value in index.get("provider_scope") or []]
    portable_providers = [str(value) for value in portable.get("provider_scope") or []]
    manifest_providers = [str(value) for value in manifest.get("provider_scope") or []]
    if not index_providers or not (
        index_providers == portable_providers == manifest_providers
    ):
        raise RuntimeError("Portable lake generation contains mixed provider scopes")


def _validated_index(payload: bytes) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Market lake index is not valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Market lake index must be a JSON object")
    require_contract(value, contract=MARKET_LAKE_CONTRACT)
    files = value.get("files")
    if not isinstance(files, list) or value.get("file_count") != len(files):
        raise RuntimeError("Market lake index has an invalid file inventory")

    seen: set[str] = set()
    total = 0
    for item in files:
        if not isinstance(item, dict):
            raise RuntimeError("Portable lake index contains an invalid file")
        path = _safe_relative_path(item.get("path"))
        name = path.as_posix()
        if name in seen:
            raise RuntimeError(f"Portable lake index repeats {name}")
        seen.add(name)
        size = item.get("size")
        checksum = item.get("sha256")
        if not isinstance(size, int) or size < 0 or size > MAX_FILE_BYTES:
            raise RuntimeError(f"Portable lake file has an invalid size: {name}")
        if (
            not isinstance(checksum, str)
            or len(checksum) != 64
            or any(character not in "0123456789abcdef" for character in checksum)
        ):
            raise RuntimeError(f"Portable lake file has an invalid checksum: {name}")
        total += size
    if total > MAX_LAKE_BYTES:
        raise RuntimeError("Portable lake exceeds the download budget")
    if not value.get("run_id") or not value.get("observed_at"):
        raise RuntimeError("Portable lake index has no market run identity")
    if not isinstance(value.get("provider_scope"), list):
        raise RuntimeError("Portable lake index has no provider scope")
    if value.get("distribution") is not None:
        _validated_distribution(value["distribution"])
    return value


def _validated_distribution(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("format") != "zip":
        raise RuntimeError("Portable lake index has an invalid distribution")
    asset = value.get("asset")
    size = value.get("size")
    checksum = value.get("sha256")
    if (
        not isinstance(asset, str)
        or not asset
        or PurePosixPath(asset).name != asset
        or any(character not in ASSET_NAME_CHARACTERS for character in asset)
    ):
        raise RuntimeError("Portable lake distribution has an invalid asset name")
    if not isinstance(size, int) or size < 1 or size > MAX_LAKE_BYTES:
        raise RuntimeError("Portable lake distribution has an invalid size")
    if (
        not isinstance(checksum, str)
        or len(checksum) != 64
        or any(character not in "0123456789abcdef" for character in checksum)
    ):
        raise RuntimeError("Portable lake distribution has an invalid checksum")
    return {"format": "zip", "asset": asset, "size": size, "sha256": checksum}


def _safe_relative_path(value: Any) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise RuntimeError("Portable lake index contains an invalid path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeError(f"Unsafe market lake path: {value}")
    return path


def _read_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return dict(value) if isinstance(value, dict) else {}


def _age_hours(value: str) -> float | None:
    if not value:
        return None
    observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - observed).total_seconds() / 3600, 1)
