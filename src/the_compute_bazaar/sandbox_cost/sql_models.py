"""Sandbox-specific DataFusion model registry."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from the_compute_bazaar.prices.sql_models import (
    render_sql_from,
    sql_metadata_from,
)


SQL_ROOT = Path(__file__).with_name("sql")

SANDBOX_MODELS = {
    "sandbox_workload_batch_history": "workload_batch_history.sql",
    "sandbox_workload_run_history": "workload_run_history.sql",
    "sandbox_workload_latest_replicates": "workload_latest_replicates.sql",
    "sandbox_workload_latest_phases": "workload_latest_phases.sql",
    "sandbox_workload_phase_summary": "workload_phase_summary.sql",
    "sandbox_workload_service_summary": "workload_service_summary.sql",
}


def sandbox_model_sql(
    table_name: str,
    context: dict[str, Any] | None = None,
    *,
    fragments: dict[str, str] | None = None,
) -> str:
    return render_sql_from(
        SQL_ROOT,
        _model_path(table_name),
        context,
        fragments=fragments,
    )


def sandbox_sql_models(table_names: Iterable[str]) -> dict[str, dict[str, str]]:
    return {
        table_name: {
            "model_id": table_name,
            **sql_metadata_from(
                SQL_ROOT,
                _model_path(table_name),
                path_prefix="sandbox_cost/sql",
            ),
        }
        for table_name in table_names
    }


def _model_path(table_name: str) -> str:
    try:
        return SANDBOX_MODELS[table_name]
    except KeyError as exc:
        raise KeyError(f"Unknown sandbox SQL model: {table_name}") from exc
