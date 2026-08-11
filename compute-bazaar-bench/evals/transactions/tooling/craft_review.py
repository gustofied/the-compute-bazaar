"""Prepare and unblind the frozen Transactions document-craft review."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
from pathlib import Path
import shutil
import sys
from typing import Any

from analysis import AnalysisError, load_object, sha256
from comparison import (
    task_name_from_result,
    validate_commitment,
    validate_run_record,
)


def opaque_id(salt: bytes, protocol_id: str, model_key: str, trial_id: str) -> str:
    message = f"{protocol_id}/{model_key}/{trial_id}".encode()
    return hmac.new(salt, message, hashlib.sha256).hexdigest()[:16]


def load_salt(path: Path, expected_sha256: str) -> bytes:
    value = path.read_text().strip()
    if hashlib.sha256(value.encode()).hexdigest() != expected_sha256:
        raise AnalysisError("blind-review salt digest mismatch")
    try:
        return bytes.fromhex(value)
    except ValueError as exc:
        raise AnalysisError("blind-review salt is not hexadecimal") from exc


def rubric_ids(rubric: dict[str, Any]) -> tuple[set[str], set[str]]:
    criteria = rubric.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise AnalysisError("craft rubric has no criteria")
    all_ids = {item.get("id") for item in criteria if isinstance(item, dict)}
    if len(all_ids) != len(criteria) or None in all_ids:
        raise AnalysisError("craft rubric criterion IDs are invalid")
    critical_ids = {
        item["id"]
        for item in criteria
        if isinstance(item, dict) and item.get("critical")
    }
    return all_ids, critical_ids


def prepare(args: argparse.Namespace) -> int:
    protocol_path = args.protocol.resolve()
    protocol = validate_commitment(protocol_path)
    run_record = load_object(args.run_record)
    jobs_root = args.jobs_root.resolve()
    validate_run_record(
        run_record, protocol_path, protocol, jobs_root=jobs_root
    )
    visual = protocol["reporting"]["visual_review"]
    rubric_path = protocol_path.parent / visual["rubric_path"]
    rubric = load_object(rubric_path)
    blinding = rubric["blinding"]
    salt = load_salt(args.salt_file, blinding["local_salt_sha256"])
    tasks = {task["name"]: task for task in protocol["tasks"]}

    output_dir = args.output_dir.resolve()
    mapping_path = args.mapping.resolve()
    template_path = args.template.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise AnalysisError(f"blind output directory is not empty: {output_dir}")
    if mapping_path.exists() or template_path.exists():
        raise AnalysisError("blind-review mapping or template already exists")
    output_dir.mkdir(parents=True, exist_ok=True)
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    template_path.parent.mkdir(parents=True, exist_ok=True)

    mappings: dict[str, Any] = {}
    reviews: dict[str, Any] = {}
    for model in protocol["models"]:
        job_name = run_record["official_jobs"].get(model["key"])
        if job_name is None:
            continue
        job_dir = jobs_root / job_name
        for result_path in sorted(job_dir.glob("*/result.json")):
            trial_dir = result_path.parent
            result = load_object(result_path)
            task_name = task_name_from_result(result)
            if task_name not in tasks:
                raise AnalysisError(f"unknown task in {trial_dir}")
            task = tasks[task_name]
            manifest = load_object_list(trial_dir / "artifacts" / "manifest.json")
            expected_source = f"/app/{task['deliverable']}"
            matches = [
                item
                for item in manifest
                if isinstance(item, dict)
                and item.get("source") == expected_source
                and item.get("status") == "ok"
            ]
            if len(matches) != 1:
                continue
            source = trial_dir / "artifacts" / "app" / task["deliverable"]
            if not source.is_file():
                raise AnalysisError(
                    f"manifest says ok but artifact is absent: {source}"
                )
            review_id = opaque_id(
                salt, protocol["protocol_id"], model["key"], trial_dir.name
            )
            if review_id in mappings:
                raise AnalysisError("blind-review ID collision")
            destination = output_dir / f"{review_id}.docx"
            shutil.copy2(source, destination)
            mappings[review_id] = {
                "model_key": model["key"],
                "job": job_name,
                "trial": trial_dir.name,
                "task": task_name,
                "source_sha256": sha256(source),
            }
            reviews[review_id] = {
                "review_id": review_id,
                "page_count": None,
                "criterion_values": {
                    criterion["id"]: None for criterion in rubric["criteria"]
                },
                "practical_usability": None,
                "notes": "",
            }

    mapping = {
        "schema_version": "compute-bazaar-bench.transactions.blind-map.v1",
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(protocol_path),
        "run_record_sha256": sha256(args.run_record),
        "rubric_sha256": sha256(rubric_path),
        "documents": mappings,
    }
    template = {
        "schema_version": "compute-bazaar-bench.transactions.blind-craft-review.v1",
        "protocol_id": protocol["protocol_id"],
        "rubric_sha256": sha256(rubric_path),
        "trials": reviews,
    }
    mapping_path.write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
    template_path.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
    print(f"prepared={len(mappings)}")
    print(f"mapping={mapping_path}")
    print(f"template={template_path}")
    return 0


def load_object_list(path: Path) -> list[Any]:
    try:
        value = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise AnalysisError(f"invalid artifact manifest {path}: {exc}") from exc
    if not isinstance(value, list):
        raise AnalysisError(f"artifact manifest is not a list: {path}")
    return value


def unblind(args: argparse.Namespace) -> int:
    mapping = load_object(args.mapping)
    review = load_object(args.review)
    rubric = load_object(args.rubric)
    if mapping.get("rubric_sha256") != sha256(args.rubric):
        raise AnalysisError("mapping and craft rubric do not match")
    if review.get("rubric_sha256") != sha256(args.rubric):
        raise AnalysisError("review and craft rubric do not match")
    documents = mapping.get("documents")
    items = review.get("trials")
    if not isinstance(documents, dict) or not isinstance(items, dict):
        raise AnalysisError("blind mapping or review has no trials")
    if set(documents) != set(items):
        raise AnalysisError("blind review IDs do not match the frozen mapping")
    all_ids, critical_ids = rubric_ids(rubric)

    unblinded: dict[str, Any] = {}
    for review_id, item in items.items():
        if not isinstance(item, dict) or item.get("review_id") != review_id:
            raise AnalysisError(f"invalid review record for {review_id}")
        values = item.get("criterion_values")
        if not isinstance(values, dict) or set(values) != all_ids:
            raise AnalysisError(f"craft criterion mismatch for {review_id}")
        if any(not isinstance(value, bool) for value in values.values()):
            raise AnalysisError(f"unfinished craft criteria for {review_id}")
        if not isinstance(item.get("page_count"), int) or item["page_count"] < 1:
            raise AnalysisError(f"invalid page count for {review_id}")
        failed = {criterion_id for criterion_id, value in values.items() if not value}
        expected_rating = (
            "poor" if failed & critical_ids else "mixed" if failed else "good"
        )
        if item.get("practical_usability") != expected_rating:
            raise AnalysisError(f"craft rating does not follow rubric for {review_id}")
        identity = documents[review_id]
        key = f"{identity['model_key']}/{identity['trial']}"
        unblinded[key] = {
            **item,
            "review_id": review_id,
            "task": identity["task"],
            "source_sha256": identity["source_sha256"],
            "clipping": not values["no-clipping"],
            "overlap": not values["no-overlap"],
        }

    output = {
        "schema_version": "compute-bazaar-bench.transactions.craft-review.v1",
        "protocol_id": mapping["protocol_id"],
        "rubric_sha256": mapping["rubric_sha256"],
        "blind_mapping_sha256": sha256(args.mapping),
        "blind_review_sha256": sha256(args.review),
        "trials": unblinded,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"unblinded={len(unblinded)}")
    print(f"output={args.output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--protocol", required=True, type=Path)
    prepare_parser.add_argument("--run-record", required=True, type=Path)
    prepare_parser.add_argument("--jobs-root", required=True, type=Path)
    prepare_parser.add_argument("--salt-file", required=True, type=Path)
    prepare_parser.add_argument("--output-dir", required=True, type=Path)
    prepare_parser.add_argument("--mapping", required=True, type=Path)
    prepare_parser.add_argument("--template", required=True, type=Path)
    prepare_parser.set_defaults(handler=prepare)

    unblind_parser = subparsers.add_parser("unblind")
    unblind_parser.add_argument("--mapping", required=True, type=Path)
    unblind_parser.add_argument("--review", required=True, type=Path)
    unblind_parser.add_argument("--rubric", required=True, type=Path)
    unblind_parser.add_argument("--output", required=True, type=Path)
    unblind_parser.set_defaults(handler=unblind)

    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AnalysisError as exc:
        print(f"craft review error: {exc}", file=sys.stderr)
        raise SystemExit(2)
