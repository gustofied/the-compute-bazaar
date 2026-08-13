"""Build, deploy, and verify the Windmill worker from one Git revision."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="SSH host, for example ec2-user@host")
    parser.add_argument(
        "--identity",
        default=".secrets/compute-bazaar-automq-runtime.pem",
        help="SSH identity file",
    )
    parser.add_argument("--revision", default="HEAD", help="Committed revision to deploy")
    args = parser.parse_args()

    revision = _git("rev-parse", "--verify", f"{args.revision}^{{commit}}")
    short_revision = revision[:12]
    image = f"compute-bazaar-windmill-worker:revision-{short_revision}"
    identity = str(Path(args.identity))

    archive = subprocess.Popen(
        ["git", "archive", "--format=tar", revision],
        stdout=subprocess.PIPE,
    )
    assert archive.stdout is not None
    build = subprocess.run(
        [
            "ssh",
            "-i",
            identity,
            "-o",
            "BatchMode=yes",
            args.host,
            (
                "sudo docker build "
                "-f infra/windmill/self-host/Dockerfile.worker "
                f"--build-arg COMPUTE_BAZAAR_REVISION={revision} "
                f"-t {image} -"
            ),
        ],
        stdin=archive.stdout,
        check=False,
    )
    archive.stdout.close()
    archive_status = archive.wait()
    if archive_status or build.returncode:
        raise SystemExit("Worker image build failed")

    deploy = (
        "set -eu; "
        f"image={image}; revision={revision}; "
        "cd /opt/windmill; "
        "sudo cp .env .env.pre-deploy; "
        "sudo sed -i \"s|^WM_WORKER_IMAGE=.*|WM_WORKER_IMAGE=$image|\" .env; "
        "sudo docker compose up -d --no-deps --force-recreate windmill_worker; "
        "actual=$(sudo docker inspect windmill-windmill_worker-1 "
        "--format '{{index .Config.Labels \"org.opencontainers.image.revision\"}}'); "
        "test \"$actual\" = \"$revision\"; "
        "sudo docker inspect windmill-windmill_worker-1 "
        "--format '{{range .Config.Env}}{{println .}}{{end}}' "
        "| grep -Fx \"COMPUTE_BAZAAR_REVISION=$revision\"; "
        "runtime=$(sudo docker exec windmill-windmill_worker-1 "
        "/opt/compute-bazaar/.venv/bin/python -c "
        "'from the_compute_bazaar.build_info import build_revision; "
        "print(build_revision())'); "
        "test \"$runtime\" = \"$revision\"; "
        "sudo docker compose ps windmill_worker; "
        "printf 'deployed_revision=%s\\nruntime_revision=%s\\n' "
        "\"$actual\" \"$runtime\""
    )
    subprocess.run(
        ["ssh", "-i", identity, "-o", "BatchMode=yes", args.host, deploy],
        check=True,
    )


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise SystemExit(f"Git returned an invalid revision: {value!r}")
    return value


if __name__ == "__main__":
    main()
