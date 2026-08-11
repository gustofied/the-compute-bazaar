from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any

from common import (
    DELIVERABLES,
    AdjudicationError,
    sha256_file,
    tree_manifest,
)


@dataclass(frozen=True)
class ModalRuntimeResult:
    returncode: int
    stdout: str
    stderr: str
    runtime_identity: dict[str, Any]


class ModalVerifierRuntime:
    """Run corrected verifier images in isolated Modal VM sandboxes."""

    def __init__(
        self,
        *,
        openrouter_key: str | None = None,
        mock_rewards: dict[str, tuple[dict[str, Any], dict[str, Any]]] | None = None,
        app_name: str = "compute-bazaar-adjudication",
    ) -> None:
        try:
            import modal
        except ImportError as error:
            raise AdjudicationError(
                "Modal backend requires the installed Harbor Modal environment"
            ) from error

        if bool(openrouter_key) == bool(mock_rewards):
            raise AdjudicationError(
                "Modal runtime requires exactly one of an OpenRouter key or mock rewards"
            )
        self.modal = modal
        self.openrouter_key = openrouter_key
        self.mock_rewards = mock_rewards
        self.app_name = app_name
        self.app = modal.App.lookup(app_name, create_if_missing=True)
        self.images: dict[str, Any] = {}
        self.builds: dict[str, dict[str, Any]] = {}
        self.last_runs: dict[str, dict[str, Any]] = {}

    @property
    def is_mock(self) -> bool:
        return self.mock_rewards is not None

    def prepare(
        self, task_name: str, corrected_task: Path, verifier_digest: str
    ) -> None:
        tests_dir = corrected_task / "tests"
        dockerfile = tests_dir / "Dockerfile"
        dockerignore = tests_dir / ".dockerignore"
        context_digest = tree_manifest(tests_dir)["tree_sha256"]
        if context_digest != verifier_digest:
            raise AdjudicationError(
                f"Modal build context drift for {task_name}: "
                f"expected {verifier_digest}, got {context_digest}"
            )
        started = time.monotonic()
        started_at = datetime.now(timezone.utc).isoformat()
        image = self.modal.Image.from_dockerfile(
            dockerfile,
            context_dir=tests_dir,
            force_build=False,
        ).build(self.app)
        image_object_id = image.object_id
        if not isinstance(image_object_id, str) or not image_object_id.startswith(
            "im-"
        ):
            raise AdjudicationError(
                f"Modal did not expose a usable image object ID for {task_name}"
            )
        self.images[task_name] = image
        self.builds[task_name] = {
            "backend": "modal_sandbox",
            "modal_sdk_version": self.modal.__version__,
            "modal_app_name": self.app_name,
            "modal_app_id": self.app.app_id,
            "modal_image_object_id": image_object_id,
            "dockerfile_sha256": sha256_file(dockerfile),
            "dockerignore_sha256": sha256_file(dockerignore),
            "context_tree_sha256": context_digest,
            "corrected_verifier_tree_sha256": verifier_digest,
            "build_started_at": started_at,
            "build_seconds": time.monotonic() - started,
            "force_build": False,
            "identity_boundary": (
                "Modal exposes its immutable image object ID, not an OCI manifest "
                "digest; Dockerfile and complete effective context are separately "
                "bound by SHA-256."
            ),
        }

    def identity(self, task_name: str) -> dict[str, Any]:
        build = self.builds.get(task_name)
        if build is None:
            return {
                "backend": "modal_sandbox",
                "modal_sdk_version": self.modal.__version__,
                "modal_app_name": self.app_name,
                "build_status": "not_prepared",
                "mode": "mock_preflight" if self.is_mock else "paid_adjudication",
            }
        return {
            **build,
            "build_status": "prepared",
            "mode": "mock_preflight" if self.is_mock else "paid_adjudication",
            "last_sandbox": self.last_runs.get(task_name),
        }

    @staticmethod
    def _read_process(process: Any) -> tuple[str, str, int]:
        stdout = process.stdout.read()
        stderr = process.stderr.read()
        returncode = process.wait()
        return stdout, stderr, returncode

    def _exec(self, sandbox: Any, *args: str, **kwargs: Any) -> tuple[str, str, int]:
        return self._read_process(sandbox.exec(*args, **kwargs))

    def _require_success(
        self, sandbox: Any, *args: str, label: str, **kwargs: Any
    ) -> tuple[str, str]:
        stdout, stderr, returncode = self._exec(sandbox, *args, **kwargs)
        if returncode != 0:
            raise AdjudicationError(
                f"Modal {label} failed with exit {returncode}: {stderr or stdout}"
            )
        return stdout, stderr

    def _upload_mock_rewardkit(self, sandbox: Any, task_name: str) -> None:
        if self.mock_rewards is None:
            raise AdjudicationError("mock reward payload is unavailable")
        reward, details = self.mock_rewards[task_name]
        script = """#!/bin/sh
set -eu
output=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output" ]; then
    shift
    output="$1"
  fi
  shift
done
test -n "$output"
mkdir -p "$(dirname "$output")"
cp /mock/reward.json "$output"
cp /mock/reward-details.json "$(dirname "$output")/reward-details.json"
"""
        sandbox.filesystem.write_text(
            json.dumps(reward, indent=2) + "\n", "/mock/reward.json"
        )
        sandbox.filesystem.write_text(
            json.dumps(details, indent=2) + "\n", "/mock/reward-details.json"
        )
        sandbox.filesystem.write_text(script, "/mock-bin/rewardkit")
        self._require_success(
            sandbox,
            "chmod",
            "0755",
            "/mock-bin/rewardkit",
            label="mock RewardKit setup",
        )

    def run(
        self,
        task_name: str,
        corrected_task: Path,
        workspace: Path,
        logs_dir: Path,
    ) -> ModalRuntimeResult:
        del corrected_task
        if task_name not in self.images:
            raise AdjudicationError(f"Modal image was not prepared for {task_name}")
        deliverable = DELIVERABLES[task_name]
        local_artifact = workspace / deliverable
        remote_artifact = f"/app/{deliverable}"
        sandbox = None
        sandbox_record: dict[str, Any] = {
            "network_policy": (
                "blocked" if self.is_mock else "allowlist:openrouter.ai"
            ),
            "secret_scope": (
                "none"
                if self.is_mock
                else "ephemeral OPENROUTER_API_KEY injected only into verifier exec"
            ),
            "cpu": 2.0,
            "memory_mib": 4096,
            "vm_runtime": True,
            "artifact_remote_path": remote_artifact,
        }
        result: ModalRuntimeResult | None = None
        started = time.monotonic()
        try:
            create_kwargs: dict[str, Any] = {
                "app": self.app,
                "image": self.images[task_name],
                "timeout": 3900,
                "cpu": (2.0, 2.0),
                "memory": (4096, 4096),
                "workdir": "/app",
                "experimental_options": {"vm_runtime": True},
                "tags": {
                    "compute-bazaar.kind": "adjudication-replay",
                    "compute-bazaar.task": task_name,
                    "compute-bazaar.mode": (
                        "mock-preflight" if self.is_mock else "paid-adjudication"
                    ),
                },
            }
            if self.is_mock:
                create_kwargs["block_network"] = True
            else:
                create_kwargs["outbound_domain_allowlist"] = ["openrouter.ai"]
                create_kwargs["outbound_cidr_allowlist"] = []
            sandbox = self.modal.Sandbox.create(
                "sh", "-c", "sleep infinity", **create_kwargs
            )
            sandbox_record["sandbox_object_id"] = sandbox.object_id
            self._require_success(
                sandbox,
                "sh",
                "-c",
                "mkdir -p /app /logs/verifier /mock /mock-bin && "
                "chmod 0777 /app /logs /logs/verifier",
                label="workspace setup",
            )
            sandbox.filesystem.copy_from_local(local_artifact, remote_artifact)
            self._require_success(
                sandbox,
                "sh",
                "-c",
                f"chown 0:0 {remote_artifact} && chmod 0444 {remote_artifact}",
                label="artifact permission setup",
            )
            stat_stdout, _ = self._require_success(
                sandbox,
                "stat",
                "-c",
                "%u:%g:%a:%n",
                remote_artifact,
                label="artifact stat",
            )
            sandbox_record["artifact_stat"] = stat_stdout.strip()
            before_stdout, _ = self._require_success(
                sandbox,
                "sha256sum",
                remote_artifact,
                label="artifact pre-hash",
            )
            remote_before = before_stdout.split()[0]
            sandbox_record["artifact_sha256_before"] = remote_before
            if remote_before != sha256_file(local_artifact):
                raise AdjudicationError("Modal staged artifact hash mismatch")

            exec_env = {
                "HARBOR_TESTS_DIR": "/tests",
                "HARBOR_WORKSPACE": "/app",
                "HARBOR_VERIFIER_LOG_DIR": "/logs/verifier",
                "LITELLM_DROP_PARAMS": "True",
            }
            exec_kwargs: dict[str, Any] = {"timeout": 3600, "env": exec_env}
            if self.is_mock:
                self._upload_mock_rewardkit(sandbox, task_name)
                exec_env["PATH"] = "/mock-bin:/usr/local/bin:/usr/bin:/bin"
                _, _, secret_probe = self._exec(
                    sandbox,
                    "sh",
                    "-c",
                    'test -z "${OPENROUTER_API_KEY+x}"',
                )
                sandbox_record["secret_absent"] = secret_probe == 0
                _, _, network_probe = self._exec(
                    sandbox,
                    "python3",
                    "-c",
                    "import urllib.request; urllib.request.urlopen("
                    "'https://openrouter.ai', timeout=3)",
                    timeout=10,
                )
                sandbox_record["network_probe_blocked"] = network_probe != 0
                _, _, write_probe = self._exec(
                    sandbox,
                    "su",
                    "nobody",
                    "-s",
                    "/bin/sh",
                    "-c",
                    f"printf x >> {remote_artifact}",
                )
                sandbox_record["unprivileged_write_denied"] = write_probe != 0
                if not all(
                    sandbox_record[key]
                    for key in (
                        "secret_absent",
                        "network_probe_blocked",
                        "unprivileged_write_denied",
                    )
                ):
                    raise AdjudicationError(
                        "Modal mock preflight boundary probe did not fail closed"
                    )
            else:
                exec_kwargs["secrets"] = [
                    self.modal.Secret.from_dict(
                        {"OPENROUTER_API_KEY": self.openrouter_key}
                    )
                ]

            process = sandbox.exec(
                "su",
                "nobody",
                "-s",
                "/bin/bash",
                "-c",
                "/tests/test.sh",
                **exec_kwargs,
            )
            stdout, stderr, returncode = self._read_process(process)

            after_stdout, _ = self._require_success(
                sandbox,
                "sha256sum",
                remote_artifact,
                label="artifact post-hash",
            )
            remote_after = after_stdout.split()[0]
            sandbox_record["artifact_sha256_after"] = remote_after
            if remote_after != remote_before:
                raise AdjudicationError("Modal verifier mutated the preserved artifact")

            logs_dir.mkdir(parents=True, exist_ok=True)
            for filename in ("reward.json", "reward-details.json"):
                remote = f"/logs/verifier/{filename}"
                exists_stdout, _, exists_code = self._exec(
                    sandbox, "sh", "-c", f"test -f {remote} && printf yes"
                )
                if exists_code == 0 and exists_stdout == "yes":
                    sandbox.filesystem.copy_to_local(remote, logs_dir / filename)
            sandbox_record["verifier_returncode"] = returncode
            result = ModalRuntimeResult(
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
                runtime_identity={},
            )
        finally:
            sandbox_record["wall_seconds"] = time.monotonic() - started
            if sandbox is not None:
                try:
                    sandbox_record["termination_returncode"] = sandbox.terminate(
                        wait=True
                    )
                    sandbox_record["terminated"] = True
                except Exception as error:
                    sandbox_record["terminated"] = False
                    sandbox_record["termination_error"] = str(error)
                try:
                    sandbox.detach()
                    sandbox_record["detached"] = True
                except Exception as error:
                    sandbox_record["detached"] = False
                    sandbox_record["detach_error"] = str(error)
            self.last_runs[task_name] = sandbox_record
        if result is None:
            raise AdjudicationError("Modal verifier produced no runtime result")
        return ModalRuntimeResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            runtime_identity=self.identity(task_name),
        )
