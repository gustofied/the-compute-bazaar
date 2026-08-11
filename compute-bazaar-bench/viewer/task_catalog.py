"""Discover authored Harbor tasks before evaluation jobs exist."""

from __future__ import annotations

import ast
from pathlib import Path
import tomllib
from typing import Any
from urllib.parse import quote

from viewer.schema import GraderInfo, LaunchSpec, TaskInfo, TaskLink


def discover_task_definitions(bench_root: Path) -> dict[str, TaskInfo]:
    """Return the Harbor tasks authored beneath ``evals/`` keyed by task slug."""
    tasks: dict[str, TaskInfo] = {}
    evals_root = bench_root / "evals"
    for config_path in sorted(evals_root.glob("**/task.toml")):
        path_parts = config_path.relative_to(evals_root).parts
        if (
            "adjudication" in path_parts
            or "internal" in path_parts
            or "releases" in path_parts
        ):
            continue
        task = _load_task(config_path, bench_root)
        if task.slug in tasks:
            raise RuntimeError(f"duplicate task slug: {task.slug}")
        tasks[task.slug] = task
    return tasks


def _load_task(
    config_path: Path,
    bench_root: Path,
) -> TaskInfo:
    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    task_config = _mapping(raw.get("task"))
    verifier = _mapping(raw.get("verifier"))
    task_root = config_path.parent

    registry_name = str(task_config.get("name") or task_root.name)
    slug = registry_name.rsplit("/", 1)[-1]
    title = _read_title(task_root, slug)
    instruction_path = task_root / "instruction.md"
    instruction = (
        instruction_path.read_text(encoding="utf-8").strip()
        if instruction_path.is_file()
        else ""
    )

    keywords = [str(keyword) for keyword in task_config.get("keywords", [])]
    domain = _fallback_domain(task_root, keywords)

    links = [
        TaskLink(
            label="Harbor task",
            href=(
                "https://hub.harborframework.com/tasks/"
                f"{quote(registry_name, safe='/')}/latest"
            ),
        )
    ]
    package_path = task_root.relative_to(bench_root.parent).as_posix()
    return TaskInfo(
        slug=slug,
        name=title,
        domain=domain.replace("-", " ").title(),
        description=str(task_config.get("description") or ""),
        instruction=instruction,
        grader=_grader_info(task_root, verifier),
        links=links,
        launch=LaunchSpec(package_path=package_path, task_id=slug),
    )


def _read_title(task_root: Path, slug: str) -> str:
    candidates = [task_root / "README.md"]
    if task_root.name in {"harbor", "task"}:
        candidates.append(task_root.parent / "README.md")
    for path in candidates:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                return slug.replace("-", " ").title() if title == slug else title
    return slug.replace("-", " ").title()


def _fallback_domain(task_root: Path, keywords: list[str]) -> str:
    if "market-game" in keywords:
        return "compute-market-games"
    return task_root.parent.name


def _grader_info(
    task_root: Path,
    verifier: dict[str, Any],
) -> GraderInfo:
    test_script = task_root / "tests" / "test.sh"
    script = test_script.read_text(encoding="utf-8") if test_script.is_file() else ""
    reward_config = task_root / "tests" / "reward.toml"
    rewards: list[str] = []
    if reward_config.is_file():
        raw_rewards = tomllib.loads(reward_config.read_text(encoding="utf-8"))
        rewards = [
            str(item.get("name"))
            for item in raw_rewards.get("reward", [])
            if isinstance(item, dict) and item.get("name")
        ]

    criterion_count, deterministic_count = _criterion_counts(task_root)
    metric_parts = []
    if criterion_count:
        metric_parts.append(f"{criterion_count} semantic criteria")
    if deterministic_count:
        metric_parts.append(f"{deterministic_count} deterministic check")

    separate = verifier.get("environment_mode") == "separate"
    return GraderInfo(
        kind="RewardKit" if "rewardkit" in script.lower() else "Deterministic verifier",
        primary_reward=", ".join(rewards) if rewards else "Task-defined reward",
        incomplete_outcome="Defined by the task verifier",
        metrics=", ".join(metric_parts) if metric_parts else "Task-defined diagnostics",
        integrity=(
            "Separate verifier environment" if separate else "Task verifier environment"
        ),
    )


def _criterion_counts(task_root: Path) -> tuple[int, int]:
    tests_root = task_root / "tests"
    semantic = 0
    for path in tests_root.glob("**/quality.toml"):
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        criteria = raw.get("criterion", [])
        if isinstance(criteria, list):
            semantic += len(criteria)

    deterministic = 0
    for path in tests_root.glob("**/checks.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(_decorator_name(item) == "criterion" for item in node.decorator_list):
                deterministic += 1
    return semantic, deterministic


def _decorator_name(node: ast.expr) -> str | None:
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
