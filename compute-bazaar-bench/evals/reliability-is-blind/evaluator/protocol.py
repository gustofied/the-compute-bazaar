"""Prepare and run matched Reliability Is Blind Harbor protocols."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from typing import Any, Sequence

from analysis import (
    AnalysisError,
    DEFAULT_TASK_ROOT,
    _bundle_risk,
    _load_engine_module,
    _load_json,
    write_protocol_analysis,
)


PROTOCOL_SCHEMA_VERSION = "reliability-is-blind.protocol.v1"
DEFAULT_PROTOCOL_ID = "reliability-is-blind-mistral-matched-20"
DEFAULT_MODELS = (
    "mistral/mistral-medium-3-5",
    "mistral/mistral-small-2603",
    "mistral/mistral-large-2512",
)
STRATA = (
    ("easy-opening", 0.0, 0.01),
    ("near-target-opening", 0.01, 0.05),
    ("uncertain-opening", 0.05, 0.20),
    ("high-risk-opening", 0.20, 1.01),
)


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, data)
    finally:
        os.close(descriptor)


def _load_or_create_secret(path: Path) -> bytes:
    if path.exists():
        value = path.read_bytes()
        if len(value) < 32:
            raise AnalysisError("protocol seed secret must contain at least 32 bytes")
        os.chmod(path, 0o600)
        return value
    value = secrets.token_bytes(32)
    _write_private(path, value)
    return value


def _candidate_seed(secret: bytes, index: int) -> int:
    digest = hmac.new(
        secret,
        f"reliability-is-blind:candidate:{index}".encode(),
        hashlib.sha256,
    ).digest()
    return int.from_bytes(digest[:8], "big") or 1


def _seed_metrics(module: Any, seed: int) -> dict[str, float]:
    engine = module.MarketEngine()
    engine.reset(seed)
    private = engine._private_suppliers_for_qa()
    opening = tuple(supplier.supplier_id for supplier in private[:4])
    best = tuple(
        supplier.supplier_id
        for supplier in sorted(
            private,
            key=lambda supplier: (supplier.failure_probability, supplier.supplier_id),
        )[:4]
    )
    return {
        "opening_bundle_expected_failure_probability": _bundle_risk(private, opening),
        "best_initial_bundle_expected_failure_probability": _bundle_risk(private, best),
    }


def _stratum(risk: float) -> str | None:
    for name, lower, upper in STRATA:
        if lower <= risk < upper:
            return name
    return None


def prepare_protocol(
    *,
    private_manifest: Path,
    commitment_path: Path,
    secret_path: Path,
    task_root: Path = DEFAULT_TASK_ROOT,
    protocol_id: str = DEFAULT_PROTOCOL_ID,
    candidates: int = 5000,
) -> tuple[Path, Path]:
    if private_manifest.exists() or commitment_path.exists():
        raise AnalysisError("protocol manifest or commitment already exists")
    engine_path = task_root / "environment" / "market-sidecar" / "market_engine.py"
    engine_sha256 = hashlib.sha256(engine_path.read_bytes()).hexdigest()
    module = _load_engine_module(task_root, engine_sha256)
    secret = _load_or_create_secret(secret_path)
    selected: dict[str, list[dict[str, Any]]] = {name: [] for name, _, _ in STRATA}
    seen: set[int] = set()
    for index in range(candidates):
        seed = _candidate_seed(secret, index)
        if seed in seen:
            continue
        seen.add(seed)
        metrics = _seed_metrics(module, seed)
        name = _stratum(metrics["opening_bundle_expected_failure_probability"])
        if name is not None and len(selected[name]) < 5:
            selected[name].append(
                {
                    "seed": seed,
                    "candidate_index": index,
                    "difficulty_stratum": name,
                    "engine_metrics": metrics,
                }
            )
        if all(len(values) == 5 for values in selected.values()):
            break
    if not all(len(values) == 5 for values in selected.values()):
        counts = {name: len(values) for name, values in selected.items()}
        raise AnalysisError(f"candidate pool did not fill every stratum: {counts}")

    cells: list[dict[str, Any]] = []
    for name, _, _ in STRATA:
        for item in selected[name]:
            cell_id = f"rib-{len(cells) + 1:03d}"
            cells.append(
                {
                    **item,
                    "cell_id": cell_id,
                    "job_name": f"{protocol_id}-{cell_id}",
                }
            )
    by_stratum = {
        name: [cell for cell in cells if cell["difficulty_stratum"] == name]
        for name, _, _ in STRATA
    }
    canary_ids = [
        by_stratum["easy-opening"][0]["cell_id"],
        by_stratum["uncertain-opening"][0]["cell_id"],
        by_stratum["high-risk-opening"][0]["cell_id"],
    ]
    manifest = {
        "schema_version": PROTOCOL_SCHEMA_VERSION,
        "protocol_id": protocol_id,
        "task": "reliability-is-blind",
        "engine_sha256": engine_sha256,
        "engine_version": module.ENGINE_VERSION,
        "selection": {
            "algorithm": "hmac-candidate-first-five-per-opening-risk-stratum",
            "candidate_count": candidates,
            "strata": [
                {"name": name, "lower_inclusive": lower, "upper_exclusive": upper}
                for name, lower, upper in STRATA
            ],
        },
        "agent": "opencode",
        "models": list(DEFAULT_MODELS),
        "environment": "modal",
        "environment_kwargs": {"modal_vm_runtime": True},
        "attempts_per_cell": 1,
        "max_retries": 0,
        "canary_cell_ids": canary_ids,
        "cells": cells,
    }
    manifest_bytes = _canonical_bytes(manifest)
    _write_private(private_manifest, manifest_bytes)
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    commitment = {
        "schema_version": PROTOCOL_SCHEMA_VERSION,
        "protocol_id": protocol_id,
        "private_manifest_sha256": manifest_sha256,
        "engine_sha256": engine_sha256,
        "engine_version": module.ENGINE_VERSION,
        "seed_count": 20,
        "canary_seed_count": 3,
        "planned_trials": 60,
        "models": list(DEFAULT_MODELS),
        "selection_algorithm": manifest["selection"]["algorithm"],
        "stratum_counts": {name: 5 for name, _, _ in STRATA},
        "raw_seeds_public": False,
    }
    commitment_path.parent.mkdir(parents=True, exist_ok=True)
    commitment_path.write_bytes(_canonical_bytes(commitment))
    return private_manifest, commitment_path


def verify_commitment(manifest_path: Path, commitment_path: Path) -> None:
    commitment = _load_json(commitment_path)
    actual = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if actual != commitment.get("private_manifest_sha256"):
        raise AnalysisError("private protocol manifest does not match its commitment")


def _job_is_complete(job_dir: Path, expected_trials: int) -> bool:
    result_path = job_dir / "result.json"
    if not result_path.exists():
        return False
    stats = _load_json(result_path).get("stats") or {}
    return (
        stats.get("n_completed_trials") == expected_trials
        and stats.get("n_errored_trials") == 0
        and stats.get("n_pending_trials") == 0
        and stats.get("n_retries") == 0
    )


def _harbor_command(
    *, cell: dict[str, Any], manifest: dict[str, Any], jobs_dir: Path, env_file: Path
) -> list[str]:
    command = [
        "harbor",
        "run",
        "-p",
        "compute-bazaar-bench/evals/reliability-is-blind/task",
        "-a",
        str(manifest["agent"]),
    ]
    for model in manifest["models"]:
        command.extend(["-m", str(model)])
    command.extend(
        [
            "-e",
            str(manifest["environment"]),
            "-o",
            str(jobs_dir),
            "--job-name",
            str(cell["job_name"]),
            "-k",
            str(manifest["attempts_per_cell"]),
            "-n",
            str(len(manifest["models"])),
            "--n-concurrent-agents",
            str(len(manifest["models"])),
            "--max-retries",
            str(manifest["max_retries"]),
            "--ek",
            "modal_vm_runtime=true",
            "--env-file",
            str(env_file),
        ]
    )
    return command


async def _run_cell(
    semaphore: asyncio.Semaphore,
    *,
    cell: dict[str, Any],
    manifest: dict[str, Any],
    jobs_dir: Path,
    env_file: Path,
    logs_dir: Path,
) -> tuple[str, int]:
    async with semaphore:
        command = _harbor_command(
            cell=cell, manifest=manifest, jobs_dir=jobs_dir, env_file=env_file
        )
        environment = os.environ.copy()
        environment["MARKET_SEED"] = str(cell["seed"])
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=Path(__file__).resolve().parents[4],
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await process.communicate()
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / f"{cell['cell_id']}.log").write_bytes(output)
        return str(cell["cell_id"]), int(process.returncode or 0)


async def run_protocol(
    *,
    manifest_path: Path,
    commitment_path: Path,
    jobs_dir: Path,
    env_file: Path,
    phase: str,
    job_concurrency: int,
) -> list[tuple[str, int]]:
    verify_commitment(manifest_path, commitment_path)
    manifest = _load_json(manifest_path)
    cell_ids = (
        set(manifest["canary_cell_ids"])
        if phase == "canary"
        else {cell["cell_id"] for cell in manifest["cells"]}
    )
    cells = [cell for cell in manifest["cells"] if cell["cell_id"] in cell_ids]
    jobs_dir.mkdir(parents=True, exist_ok=True)
    expected_trials = len(manifest["models"])
    pending: list[dict[str, Any]] = []
    for cell in cells:
        job_dir = jobs_dir / cell["job_name"]
        if job_dir.exists():
            if _job_is_complete(job_dir, expected_trials):
                continue
            raise AnalysisError(
                f"existing job is not a clean completed cell: {job_dir}"
            )
        pending.append(cell)
    if not pending:
        return []
    if shutil.which("harbor") is None:
        raise AnalysisError("harbor executable is not available")
    if not env_file.exists():
        raise AnalysisError(f"credential file is missing: {env_file}")
    if job_concurrency <= 0:
        raise AnalysisError("job concurrency must be positive")
    semaphore = asyncio.Semaphore(job_concurrency)
    logs_dir = jobs_dir / f"{manifest['protocol_id']}-run-logs"
    return await asyncio.gather(
        *(
            _run_cell(
                semaphore,
                cell=cell,
                manifest=manifest,
                jobs_dir=jobs_dir,
                env_file=env_file,
                logs_dir=logs_dir,
            )
            for cell in pending
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rib-protocol")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--manifest", type=Path, required=True)
    prepare.add_argument("--commitment", type=Path, required=True)
    prepare.add_argument("--secret", type=Path, required=True)
    prepare.add_argument("--task-root", type=Path, default=DEFAULT_TASK_ROOT)
    prepare.add_argument("--candidates", type=int, default=5000)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--commitment", type=Path, required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--commitment", type=Path, required=True)
    run.add_argument(
        "--jobs-dir", type=Path, default=Path("compute-bazaar-bench/jobs/raw")
    )
    run.add_argument("--env-file", type=Path, required=True)
    run.add_argument("--phase", choices=("canary", "full"), required=True)
    run.add_argument("--job-concurrency", type=int, default=2)
    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("--manifest", type=Path, required=True)
    analyze.add_argument("--commitment", type=Path, required=True)
    analyze.add_argument(
        "--jobs-dir", type=Path, default=Path("compute-bazaar-bench/jobs/raw")
    )
    analyze.add_argument("--phase", choices=("canary", "full"), required=True)
    analyze.add_argument("--output", type=Path)
    analyze.add_argument("--task-root", type=Path, default=DEFAULT_TASK_ROOT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare":
            paths = prepare_protocol(
                private_manifest=args.manifest,
                commitment_path=args.commitment,
                secret_path=args.secret,
                task_root=args.task_root,
                candidates=args.candidates,
            )
            print("\n".join(str(path) for path in paths))
        elif args.command == "verify":
            verify_commitment(args.manifest, args.commitment)
            print("commitment verified")
        elif args.command == "run":
            results = asyncio.run(
                run_protocol(
                    manifest_path=args.manifest,
                    commitment_path=args.commitment,
                    jobs_dir=args.jobs_dir,
                    env_file=args.env_file,
                    phase=args.phase,
                    job_concurrency=args.job_concurrency,
                )
            )
            failed = [cell_id for cell_id, code in results if code]
            if failed:
                raise AnalysisError(f"Harbor jobs failed: {', '.join(failed)}")
            print(f"completed {len(results)} new job(s)")
        else:
            verify_commitment(args.manifest, args.commitment)
            destination = write_protocol_analysis(
                args.manifest,
                args.jobs_dir,
                phase=args.phase,
                output_dir=args.output,
                task_root=args.task_root,
            )
            print(destination)
    except (AnalysisError, OSError, subprocess.SubprocessError) as exc:
        print(f"rib-protocol: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
