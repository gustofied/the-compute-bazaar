from __future__ import annotations

import hashlib
from pathlib import Path

from rewardkit import criterion


@criterion(description="The required DOCX passed the verifier's archive and text-extraction checks.")
def valid_deliverable(workspace: Path) -> bool:
    name = "capacity-agreement-deviation-report.docx"
    document = workspace / name
    extracted = workspace / f"{name}.md"
    marker = workspace / f".{name}.integrity.sha256"
    if document.is_symlink() or not document.is_file() or not extracted.is_file() or not marker.is_file():
        return False
    digest = hashlib.sha256(document.read_bytes()).hexdigest()
    return marker.read_text().strip() == digest and bool(extracted.read_text().strip())
