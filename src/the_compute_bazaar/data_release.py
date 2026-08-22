"""Package and publish the sanitized market lake through GitHub Releases."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from .contracts import MARKET_LAKE_CONTRACT, require_contract
from .data_sync import _safe_relative_path, _validated_index


DEFAULT_RELEASE_REPOSITORY = "gustofied/the-compute-bazaar"
DEFAULT_RELEASE_TAG = "public-lake"


def build_release_assets(*, lake_root: str, output_root: str) -> dict[str, Any]:
    """Build one checksummed zip and its small release index."""
    source = Path(lake_root).expanduser().resolve()
    output = Path(output_root).expanduser().resolve()
    index = _validated_index((source / "index.json").read_bytes())
    portable = json.loads((source / "portable.json").read_text(encoding="utf-8"))
    require_contract(portable, contract=MARKET_LAKE_CONTRACT)
    if portable.get("private_evidence_removed") is not True:
        raise RuntimeError("Refusing to publish a lake that contains private evidence")

    run_slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(index["run_id"]))
    asset_name = f"compute-bazaar-lake-{run_slug}.zip"
    output.mkdir(parents=True, exist_ok=True)
    archive_path = output / asset_name
    temporary_archive = output / f".{asset_name}.tmp"

    try:
        with zipfile.ZipFile(
            temporary_archive,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            for item in index["files"]:
                relative = _safe_relative_path(item["path"])
                path = source / relative
                _validate_source_file(path, item=item)
                archive.write(path, relative.as_posix())
        temporary_archive.replace(archive_path)
    finally:
        temporary_archive.unlink(missing_ok=True)

    release_index = {
        **index,
        "distribution": {
            "format": "zip",
            "asset": asset_name,
            "size": archive_path.stat().st_size,
            "sha256": _file_sha256(archive_path),
        },
    }
    index_path = output / "index.json"
    index_path.write_text(
        json.dumps(release_index, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "run_id": index["run_id"],
        "observed_at": index["observed_at"],
        "providers": index["provider_scope"],
        "files": index["file_count"],
        "archive": str(archive_path),
        "archive_bytes": archive_path.stat().st_size,
        "index": str(index_path),
    }


def publish_release(
    *,
    lake_root: str,
    repository: str = DEFAULT_RELEASE_REPOSITORY,
    tag: str = DEFAULT_RELEASE_TAG,
) -> dict[str, Any]:
    """Package the public lake and replace the rolling GitHub release index."""
    gh = shutil.which("gh")
    if not gh:
        raise RuntimeError("Publishing requires the GitHub CLI: https://cli.github.com")

    with tempfile.TemporaryDirectory(prefix="compute-bazaar-public-lake-") as temp:
        result = build_release_assets(lake_root=lake_root, output_root=temp)
        archive = Path(str(result["archive"]))
        index = Path(str(result["index"]))
        release = _run_gh(gh, "release", "view", tag, "--repo", repository)
        if release.returncode == 0:
            _require_gh(
                gh,
                "release",
                "upload",
                tag,
                str(archive),
                "--clobber",
                "--repo",
                repository,
            )
            _require_gh(
                gh,
                "release",
                "upload",
                tag,
                str(index),
                "--clobber",
                "--repo",
                repository,
            )
        elif _release_is_missing(release):
            _require_gh(
                gh,
                "release",
                "create",
                tag,
                str(archive),
                str(index),
                "--repo",
                repository,
                "--title",
                "Public market lake",
                "--notes",
                "Sanitized Silver and Gold market data for compute-bazaar data sync.",
                "--latest=false",
            )
        else:
            raise RuntimeError(release.stderr.strip() or "Could not read GitHub release")

    return {
        "run_id": result["run_id"],
        "observed_at": result["observed_at"],
        "providers": result["providers"],
        "files": result["files"],
        "archive": archive.name,
        "archive_bytes": result["archive_bytes"],
        "index": index.name,
        "repository": repository,
        "tag": tag,
        "url": f"https://github.com/{repository}/releases/tag/{tag}",
    }


def _validate_source_file(path: Path, *, item: dict[str, Any]) -> None:
    if not path.is_file() or path.stat().st_size != item["size"]:
        raise RuntimeError(f"Portable lake file does not match its index: {item['path']}")
    if _file_sha256(path) != item["sha256"]:
        raise RuntimeError(f"Portable lake checksum does not match: {item['path']}")


def _file_sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _run_gh(gh: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [gh, *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("GitHub release command timed out") from exc


def _release_is_missing(result: subprocess.CompletedProcess[str]) -> bool:
    message = f"{result.stdout}\n{result.stderr}".lower()
    return "release not found" in message or "http 404" in message


def _require_gh(gh: str, *arguments: str) -> None:
    result = _run_gh(gh, *arguments)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "GitHub release command failed")
