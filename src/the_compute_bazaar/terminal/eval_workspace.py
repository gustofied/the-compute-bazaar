"""Mount the evaluation workspace into the Terminal."""

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
        if evaluation_root is None:
            return cls()
        bench_root = evaluation_root.resolve().parents[1]
        if not (bench_root / "viewer" / "app.py").is_file():
            return cls()
        root_text = str(bench_root)
        if root_text not in sys.path:
            sys.path.insert(0, root_text)
        module = importlib.import_module("viewer.app")
        create_app = getattr(module, "create_app", None)
        first_evaluation_url = getattr(module, "first_evaluation_url", None)
        if not callable(create_app) or not callable(first_evaluation_url):
            return cls()
        first_url = first_evaluation_url(evaluation_root)
        if first_url is None:
            return cls()
        return cls(
            app=create_app(evaluation_root, base_path="/eval"),
            first_url=first_url,
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
