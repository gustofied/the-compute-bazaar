"""Repo-backed SQL models and view blueprints."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .prices.query_catalog import MAX_QUERY_LIMIT, validate_catalog_sql


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ANALYSIS_ROOT = Path(
    os.getenv("COMPUTE_BAZAAR_ANALYSIS_ROOT", PROJECT_ROOT / "analyses")
)
ARTIFACT_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
TABLE_REF_PATTERN = re.compile(
    r"\b(?:silver|gold|fleet)\.[A-Za-z_][A-Za-z0-9_]*\b",
    flags=re.IGNORECASE,
)


class AnalysisModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str
    title: str = Field(min_length=1, max_length=96)
    description: str = Field(default="", max_length=500)
    default_limit: int = Field(default=500, ge=1, le=MAX_QUERY_LIMIT)
    created_at: datetime
    updated_at: datetime
    sql: str
    tables: tuple[str, ...] = ()


class ViewBlueprint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blueprint_id: str
    model_id: str
    title: str = Field(min_length=1, max_length=96)
    description: str = Field(default="", max_length=500)
    markdown: str = Field(default="", max_length=20_000)
    viewer: Literal["perspective"]
    viewer_config: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AnalysisStore:
    """Persist analysis artifacts as ordinary, reviewable repo files."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or DEFAULT_ANALYSIS_ROOT).resolve()
        self.models_root = self.root / "models"
        self.blueprints_root = self.root / "blueprints"

    def list_models(self) -> list[AnalysisModel]:
        if not self.models_root.is_dir():
            return []
        return [
            self.load_model(path.stem)
            for path in sorted(self.models_root.glob("*.json"))
        ]

    def list_blueprints(self) -> list[ViewBlueprint]:
        if not self.blueprints_root.is_dir():
            return []
        return [
            self.load_blueprint(path.stem)
            for path in sorted(self.blueprints_root.glob("*.json"))
        ]

    def load_model(self, model_id: str) -> AnalysisModel:
        selected_id = _artifact_id(model_id)
        metadata = _read_json(self.models_root / f"{selected_id}.json")
        sql = (self.models_root / f"{selected_id}.sql").read_text(encoding="utf-8")
        return AnalysisModel(
            **metadata,
            sql=_analysis_sql(sql),
            tables=_table_refs(sql),
        )

    def load_blueprint(self, blueprint_id: str) -> ViewBlueprint:
        selected_id = _artifact_id(blueprint_id)
        blueprint = ViewBlueprint.model_validate(
            _read_json(self.blueprints_root / f"{selected_id}.json")
        )
        self.load_model(blueprint.model_id)
        return blueprint

    def save_model(
        self,
        *,
        model_id: str,
        title: str,
        description: str,
        sql: str,
        default_limit: int = 500,
    ) -> AnalysisModel:
        selected_id = _artifact_id(model_id)
        statement = _analysis_sql(sql)
        now = datetime.now(UTC)
        existing = self._model_metadata(selected_id)
        model = AnalysisModel(
            model_id=selected_id,
            title=title.strip(),
            description=description.strip(),
            default_limit=default_limit,
            created_at=(existing or {}).get("created_at", now),
            updated_at=now,
            sql=statement,
            tables=_table_refs(statement),
        )
        self.models_root.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.models_root / f"{selected_id}.sql", f"{statement}\n")
        metadata = model.model_dump(mode="json", exclude={"sql", "tables"})
        _atomic_json(self.models_root / f"{selected_id}.json", metadata)
        return model

    def save_blueprint(
        self,
        *,
        blueprint_id: str,
        model_id: str,
        title: str,
        description: str,
        markdown: str = "",
        viewer: Literal["perspective"],
        viewer_config: dict[str, Any],
    ) -> ViewBlueprint:
        selected_id = _artifact_id(blueprint_id)
        selected_model_id = _artifact_id(model_id)
        self.load_model(selected_model_id)
        now = datetime.now(UTC)
        existing = self._blueprint_metadata(selected_id)
        blueprint = ViewBlueprint(
            blueprint_id=selected_id,
            model_id=selected_model_id,
            title=title.strip(),
            description=description.strip(),
            markdown=markdown.strip(),
            viewer=viewer,
            viewer_config=viewer_config,
            created_at=(existing or {}).get("created_at", now),
            updated_at=now,
        )
        self.blueprints_root.mkdir(parents=True, exist_ok=True)
        _atomic_json(
            self.blueprints_root / f"{selected_id}.json",
            blueprint.model_dump(mode="json"),
        )
        return blueprint

    def save_analysis(
        self,
        *,
        title: str,
        description: str,
        markdown: str = "",
        sql: str,
        default_limit: int,
        viewer: Literal["perspective"],
        viewer_config: dict[str, Any],
        model_id: str | None = None,
        blueprint_id: str | None = None,
    ) -> tuple[AnalysisModel, ViewBlueprint]:
        selected_model_id = _artifact_id(model_id or _slug(title))
        selected_blueprint_id = _artifact_id(blueprint_id or selected_model_id)
        model = self.save_model(
            model_id=selected_model_id,
            title=title,
            description=description,
            sql=sql,
            default_limit=default_limit,
        )
        blueprint = self.save_blueprint(
            blueprint_id=selected_blueprint_id,
            model_id=selected_model_id,
            title=title,
            description=description,
            markdown=markdown,
            viewer=viewer,
            viewer_config=viewer_config,
        )
        return model, blueprint

    def delete_model(self, model_id: str) -> None:
        selected_id = _artifact_id(model_id)
        dependants = [
            blueprint.blueprint_id
            for blueprint in self.list_blueprints()
            if blueprint.model_id == selected_id
        ]
        if dependants:
            raise ValueError(f"Model {selected_id} is used by: {', '.join(dependants)}")
        (self.models_root / f"{selected_id}.json").unlink(missing_ok=True)
        (self.models_root / f"{selected_id}.sql").unlink(missing_ok=True)

    def delete_blueprint(self, blueprint_id: str) -> None:
        selected_id = _artifact_id(blueprint_id)
        (self.blueprints_root / f"{selected_id}.json").unlink(missing_ok=True)

    def _model_metadata(self, model_id: str) -> dict[str, Any] | None:
        path = self.models_root / f"{model_id}.json"
        return _read_json(path) if path.is_file() else None

    def _blueprint_metadata(self, blueprint_id: str) -> dict[str, Any] | None:
        path = self.blueprints_root / f"{blueprint_id}.json"
        return _read_json(path) if path.is_file() else None


def model_payload(model: AnalysisModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


def blueprint_payload(blueprint: ViewBlueprint) -> dict[str, Any]:
    return blueprint.model_dump(mode="json")


def _analysis_sql(sql: str) -> str:
    statement = validate_catalog_sql(sql).strip().rstrip(";").strip()
    first_word = re.match(r"^(select|with|values)\b", statement, re.IGNORECASE)
    if not first_word:
        raise ValueError(
            "Analysis models must be read-only SELECT, WITH, or VALUES SQL"
        )
    return statement


def _table_refs(sql: str) -> tuple[str, ...]:
    return tuple(sorted({match.lower() for match in TABLE_REF_PATTERN.findall(sql)}))


def _artifact_id(value: str) -> str:
    selected = value.strip().lower()
    if not ARTIFACT_ID_PATTERN.fullmatch(selected):
        raise ValueError(
            "Artifact IDs use lowercase letters, numbers, and single hyphens"
        )
    return selected


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not slug:
        raise ValueError("Analysis title must contain a letter or number")
    return slug


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write(path, f"{json.dumps(payload, indent=2, sort_keys=True)}\n")
