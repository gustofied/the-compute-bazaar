"""Adapter that mounts the existing evaluation viewer into the Terminal."""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI


@dataclass(frozen=True)
class EvalWorkspace:
    app: FastAPI | None = None
    first_url: str | None = None

    @classmethod
    def load(cls, evaluation_root: Path | None) -> EvalWorkspace:
        if evaluation_root is None or not evaluation_root.is_dir():
            return cls()
        bench_root = evaluation_root.resolve().parents[1]
        if not (bench_root / "viewer" / "app.py").is_file():
            return cls()
        root_text = str(bench_root)
        if root_text not in sys.path:
            sys.path.insert(0, root_text)
        module = importlib.import_module("viewer.app")
        return cls(
            app=module.create_app(evaluation_root, base_path="/eval"),
            first_url=_first_evaluation_url(evaluation_root),
        )

    @property
    def available(self) -> bool:
        return self.app is not None and self.first_url is not None

    def destination(self) -> dict[str, str | bool | None]:
        return {
            "available": self.available,
            "href": "/eval" if self.available else None,
        }

    def mount(self, shell: FastAPI) -> None:
        if not self.available or self.app is None:
            return
        shell.mount("/eval", self.app, name="evaluation-workspace")


def _first_evaluation_url(evaluation_root: Path) -> str | None:
    for container in ("runs", "jobs"):
        for run_dir in sorted(evaluation_root.glob(f"*/{container}/*")):
            if (run_dir / "view.json").is_file() or (
                (run_dir / "protocol.json").is_file()
                and (run_dir / "trials.json").is_file()
            ):
                return f"/eval/evals/{run_dir.parent.parent.name}"
    return None
