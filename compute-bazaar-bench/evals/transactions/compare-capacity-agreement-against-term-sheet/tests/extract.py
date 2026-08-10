#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

MANIFEST = Path(__file__).with_name("deliverables.txt")
MIN_FILE_BYTES = 1_024
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MIN_TEXT_CHARS = 200
MAX_TEXT_CHARS = 500_000


class OutputError(RuntimeError):
    pass


def deliverable_name() -> str:
    if not MANIFEST.is_file():
        raise RuntimeError("deliverable manifest is missing")
    names = [line.strip() for line in MANIFEST.read_text().splitlines() if line.strip()]
    if len(names) != 1:
        raise RuntimeError("deliverable manifest must contain exactly one filename")
    name = names[0]
    pure = PurePosixPath(name)
    if pure.name != name or pure.suffix.lower() != ".docx":
        raise RuntimeError("deliverable manifest must contain one plain DOCX filename")
    return name


def validate_docx(path: Path) -> None:
    if not path.exists():
        raise OutputError(f"required deliverable not produced: {path.name}")
    if path.is_symlink() or not path.is_file():
        raise OutputError(f"deliverable is not a regular file: {path.name}")
    size = path.stat().st_size
    if not MIN_FILE_BYTES <= size <= MAX_FILE_BYTES:
        raise OutputError(f"deliverable size is outside the accepted range: {size} bytes")

    try:
        with ZipFile(path) as archive:
            infos = archive.infolist()
            names = {info.filename for info in infos}
            required = {"[Content_Types].xml", "word/document.xml"}
            if not required.issubset(names):
                raise OutputError("deliverable is not a readable Word document")
            if len(infos) > 2_000:
                raise OutputError("deliverable archive contains too many entries")
            total_size = 0
            for info in infos:
                parts = PurePosixPath(info.filename).parts
                if info.filename.startswith("/") or "\\" in info.filename or ".." in parts:
                    raise OutputError("deliverable archive contains an unsafe path")
                if stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK:
                    raise OutputError("deliverable archive contains a symbolic link")
                total_size += info.file_size
                if info.compress_size and info.file_size / info.compress_size > 500:
                    raise OutputError("deliverable archive contains an unsafe compression ratio")
            if total_size > MAX_ARCHIVE_BYTES:
                raise OutputError("deliverable archive expands beyond the accepted size")
            corrupt = archive.testzip()
            if corrupt is not None:
                raise OutputError(f"deliverable archive contains a corrupt entry: {corrupt}")
    except BadZipFile as exc:
        raise OutputError("deliverable is not a valid DOCX archive") from exc


def extract_docx(path: Path) -> str:
    try:
        result = subprocess.run(
            ["pandoc", str(path), "-t", "markdown", "--wrap=none", "--track-changes=accept"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise OutputError("DOCX extraction exceeded 60 seconds") from exc
    if result.returncode != 0:
        detail = result.stderr.strip()[:500]
        raise OutputError(f"DOCX extraction failed: {detail}")
    text = result.stdout.strip()
    if not MIN_TEXT_CHARS <= len(text) <= MAX_TEXT_CHARS:
        raise OutputError(f"extracted text length is outside the accepted range: {len(text)}")
    return text


def main() -> int:
    workspace = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/app")
    try:
        name = deliverable_name()
        source = workspace / name
        validate_docx(source)
        text = extract_docx(source)
        (workspace / f"{name}.md").write_text(text + "\n", encoding="utf-8")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        (workspace / f".{name}.integrity.sha256").write_text(digest + "\n", encoding="ascii")
        print(f"validated and extracted {name}")
        return 0
    except OutputError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"verifier setup failed: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
