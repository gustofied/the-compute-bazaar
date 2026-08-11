from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


TASK_NAMES = (
    "normalize-buyer-mandate",
    "draft-capacity-data-room-population-plan",
    "compare-capacity-agreement-against-term-sheet",
)

DELIVERABLES = {
    "normalize-buyer-mandate": "buyer-mandate-brief.docx",
    "draft-capacity-data-room-population-plan": (
        "capacity-data-room-population-plan.docx"
    ),
    "compare-capacity-agreement-against-term-sheet": (
        "capacity-agreement-deviation-report.docx"
    ),
}

ORIGINAL_TASK_DIGESTS = {
    "normalize-buyer-mandate": (
        "sha256:2932b4083612616afa6f3867e0208a546743025424c484342f5fbad889083410"
    ),
    "draft-capacity-data-room-population-plan": (
        "sha256:d5132045ccf8068060fb483e7c70996cc4a61a410230f13238be87569b1fdbe7"
    ),
    "compare-capacity-agreement-against-term-sheet": (
        "sha256:370004ab122e5036ecf8f60ac074f609f8d527db216f5500620b6721c83532e6"
    ),
}

TASK_ROOT_FILES = ("task.toml", "instruction.md", "README.md")
TASK_RECURSIVE_DIRS = ("environment", "tests", "solution", "steps")
DEFAULT_IGNORES = {".DS_Store"}
DEFAULT_IGNORE_SUFFIXES = (".pyc", ".swp", ".swo", "~")

INTEGRITY_PATHS = (
    "tests/Dockerfile",
    "tests/deliverables.txt",
    "tests/extract.py",
    "tests/fail_closed.py",
    "tests/output-integrity/checks.py",
    "tests/test.sh",
    "tests/__support/validate_rewardkit.py",
)


class AdjudicationError(RuntimeError):
    pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def canonical_json_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=False) + "\n")


def file_record(path: Path, root: Path) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    return {
        "path": relative,
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def tree_manifest(root: Path, paths: Iterable[Path] | None = None) -> dict[str, Any]:
    selected = (
        paths
        if paths is not None
        else (
            path
            for path in root.rglob("*")
            if path.is_file() and not _ignored(path.relative_to(root))
        )
    )
    files = [file_record(path, root) for path in selected]
    files.sort(key=lambda row: row["path"])
    return {
        "files": files,
        "tree_sha256": canonical_json_sha256(files),
    }


def _ignored(path: Path) -> bool:
    if "__pycache__" in path.parts or path.name in DEFAULT_IGNORES:
        return True
    return path.name.endswith(DEFAULT_IGNORE_SUFFIXES)


def collect_task_files(task_dir: Path) -> list[Path]:
    files: list[Path] = []
    for relative in TASK_ROOT_FILES:
        path = task_dir / relative
        if path.is_file():
            files.append(path)
    for relative in TASK_RECURSIVE_DIRS:
        directory = task_dir / relative
        if not directory.is_dir():
            continue
        files.extend(
            path
            for path in directory.rglob("*")
            if path.is_file() and not _ignored(path.relative_to(task_dir))
        )
    return sorted(files, key=lambda path: path.relative_to(task_dir).as_posix())


def task_content_digest(task_dir: Path) -> str:
    outer = hashlib.sha256()
    for path in collect_task_files(task_dir):
        relative = path.relative_to(task_dir).as_posix()
        outer.update(f"{relative}\0{sha256_file(path)}\n".encode())
    return f"sha256:{outer.hexdigest()}"


def selected_files_manifest(
    task_dir: Path, relative_paths: Iterable[str]
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for relative in sorted(relative_paths):
        path = task_dir / relative
        if not path.is_file():
            raise AdjudicationError(f"required file missing: {path}")
        files.append(file_record(path, task_dir))
    return {
        "files": files,
        "tree_sha256": canonical_json_sha256(files),
    }


def relative_file_hashes(root: Path, paths: Iterable[Path]) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix())
    }


def task_file_diff(original: Path, corrected: Path) -> dict[str, Any]:
    original_hashes = relative_file_hashes(original, collect_task_files(original))
    corrected_hashes = relative_file_hashes(corrected, collect_task_files(corrected))
    original_paths = set(original_hashes)
    corrected_paths = set(corrected_hashes)
    return {
        "added": sorted(corrected_paths - original_paths),
        "removed": sorted(original_paths - corrected_paths),
        "changed": sorted(
            path
            for path in original_paths & corrected_paths
            if original_hashes[path] != corrected_hashes[path]
        ),
    }


def assert_regular_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise AdjudicationError(f"expected a regular file: {path}")


def repo_root_from(path: Path) -> Path:
    current = path.resolve()
    for parent in (current, *current.parents):
        if (parent / ".git").exists():
            return parent
    raise AdjudicationError(f"could not locate repository root from {path}")
