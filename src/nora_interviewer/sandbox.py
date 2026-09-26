from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

from pydantic import Field

from .models import StrictModel


class SandboxUnavailable(RuntimeError):
    pass


class SandboxLimits(StrictModel):
    timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    memory_mb: int = Field(default=256, ge=64, le=2048)
    cpus: float = Field(default=0.5, gt=0, le=4)
    pids_limit: int = Field(default=64, ge=16, le=512)


class SandboxProducedArtifact(StrictModel):
    name: str = Field(min_length=1, max_length=500)
    media_type: str = Field(min_length=1, max_length=200)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reference: str | None = Field(default=None, max_length=2000)


class SandboxResult(StrictModel):
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    duration_ms: int = Field(ge=0)
    provider_id: str = Field(default="unknown", min_length=1, max_length=200)
    execution_id: str | None = Field(default=None, max_length=500)
    artifacts: list[SandboxProducedArtifact] = Field(default_factory=list)


class SandboxRunner(Protocol):
    async def run_python(
        self,
        *,
        source: str,
        harness: str,
        limits: SandboxLimits,
    ) -> SandboxResult: ...


class DisabledSandboxRunner:
    async def run_python(
        self,
        *,
        source: str,
        harness: str,
        limits: SandboxLimits,
    ) -> SandboxResult:
        raise SandboxUnavailable(
            "Code execution is disabled. Configure NORA_SANDBOX_MODE=docker "
            "or provide an external SandboxRunner."
        )


class DockerSandboxRunner:
    """Run Python submissions inside a constrained disposable Docker container.

    This is suitable for local development and CI experiments. It is not a
    complete hostile-code isolation boundary for high-stakes production use.
    Production deployments should prefer a dedicated remote sandbox service.
    """

    def __init__(self, image: str = "python:3.12-alpine") -> None:
        self.image = image

    async def run_python(
        self,
        *,
        source: str,
        harness: str,
        limits: SandboxLimits,
    ) -> SandboxResult:
        with tempfile.TemporaryDirectory(prefix="nora-sandbox-") as tmp:
            root = Path(tmp)
            solution_path = root / "solution.py"
            harness_path = root / "harness.py"
            solution_path.write_text(source, encoding="utf-8")
            harness_path.write_text(harness, encoding="utf-8")

            # The container deliberately runs as an unprivileged uid. Make only
            # the temporary challenge directory readable/traversable by it.
            root.chmod(0o755)
            solution_path.chmod(0o444)
            harness_path.chmod(0o444)

            command = [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--pids-limit",
                str(limits.pids_limit),
                "--ulimit",
                "nofile=64:64",
                "--env",
                "PYTHONDONTWRITEBYTECODE=1",
                "--memory",
                f"{limits.memory_mb}m",
                "--cpus",
                str(limits.cpus),
                "--user",
                "65534:65534",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=64m",
                "--mount",
                f"type=bind,src={root},dst=/workspace,readonly",
                "--workdir",
                "/workspace",
                self.image,
                "python",
                "/workspace/harness.py",
            ]

            started = perf_counter()
            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError as exc:
                raise SandboxUnavailable("Docker executable was not found.") from exc

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=limits.timeout_seconds,
                )
                timed_out = False
            except asyncio.TimeoutError:
                process.kill()
                stdout, stderr = await process.communicate()
                timed_out = True

            duration_ms = max(0, round((perf_counter() - started) * 1000))
            return SandboxResult(
                exit_code=process.returncode,
                stdout=stdout.decode("utf-8", errors="replace")[-20_000:],
                stderr=stderr.decode("utf-8", errors="replace")[-20_000:],
                timed_out=timed_out,
                duration_ms=duration_ms,
                provider_id="docker",
            )



class RemoteSandboxRunner:
    """Dispatch execution to a dedicated Nora sandbox service.

    Protocol: nora.sandbox.v1
    Endpoint: POST {base_url}/v1/executions/python
    """

    provider_id = "remote"

    def __init__(
        self,
        *,
        base_url: str,
        token: str | None = None,
        request_timeout_seconds: float = 35.0,
    ) -> None:
        base_url = base_url.rstrip("/")
        if not base_url:
            raise ValueError("remote sandbox base_url is required")
        if request_timeout_seconds <= 0:
            raise ValueError(
                "remote sandbox request timeout must be positive"
            )
        self.base_url = base_url
        self.token = token
        self.request_timeout_seconds = request_timeout_seconds

    async def run_python(
        self,
        *,
        source: str,
        harness: str,
        limits: SandboxLimits,
    ) -> SandboxResult:
        try:
            import httpx
        except ImportError as exc:
            raise SandboxUnavailable(
                "Remote sandbox requires httpx"
            ) from exc

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.token:
            headers["Authorization"] = (
                "Bearer " + self.token
            )

        payload: dict[str, Any] = {
            "protocol": "nora.sandbox.v1",
            "language": "python",
            "source": source,
            "harness": harness,
            "limits": limits.model_dump(
                mode="json"
            ),
            "policy": {
                "network_access": False,
                "filesystem": "ephemeral",
                "privileged": False,
                "max_output_bytes": 20000,
            },
        }

        try:
            async with httpx.AsyncClient(
                timeout=self.request_timeout_seconds,
            ) as client:
                response = await client.post(
                    self.base_url
                    + "/v1/executions/python",
                    headers=headers,
                    json=payload,
                )
        except (
            httpx.TimeoutException,
            httpx.RequestError,
        ) as exc:
            raise SandboxUnavailable(
                "Remote sandbox is unavailable"
            ) from exc

        if response.status_code in {
            408,
            429,
            502,
            503,
            504,
        }:
            raise SandboxUnavailable(
                "Remote sandbox is temporarily unavailable"
            )
        if response.status_code < 200 or response.status_code >= 300:
            raise SandboxUnavailable(
                "Remote sandbox rejected the execution request"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise SandboxUnavailable(
                "Remote sandbox returned invalid JSON"
            ) from exc
        if not isinstance(body, dict):
            raise SandboxUnavailable(
                "Remote sandbox returned an invalid response"
            )
        if body.get("protocol") != "nora.sandbox.v1":
            raise SandboxUnavailable(
                "Remote sandbox protocol version mismatch"
            )

        result_payload = body.get(
            "result"
        )
        if not isinstance(result_payload, dict):
            raise SandboxUnavailable(
                "Remote sandbox response is missing result"
            )
        result_payload = dict(result_payload)
        result_payload["provider_id"] = str(
            body.get("provider_id")
            or "remote"
        )
        execution_id = body.get(
            "execution_id"
        )
        if execution_id is not None:
            result_payload[
                "execution_id"
            ] = str(execution_id)

        try:
            result = SandboxResult.model_validate(
                result_payload
            )
        except Exception as exc:
            raise SandboxUnavailable(
                "Remote sandbox result failed contract validation"
            ) from exc

        result.stdout = result.stdout[
            -20_000:
        ]
        result.stderr = result.stderr[
            -20_000:
        ]
        return result


def default_sandbox_runner() -> SandboxRunner:
    mode = os.getenv("NORA_SANDBOX_MODE", "disabled").strip().lower()
    if mode == "disabled":
        return DisabledSandboxRunner()
    if mode == "docker":
        image = os.getenv("NORA_SANDBOX_IMAGE", "python:3.12-alpine").strip()
        return DockerSandboxRunner(image=image)
    if mode == "remote":
        base_url = os.getenv(
            "NORA_SANDBOX_REMOTE_URL",
            "",
        ).strip()
        token = os.getenv(
            "NORA_SANDBOX_REMOTE_TOKEN"
        )
        allow_insecure = os.getenv(
            "NORA_SANDBOX_REMOTE_ALLOW_INSECURE",
            "false",
        ).strip().lower() in {"1", "true", "yes", "on"}
        if not base_url:
            raise RuntimeError(
                "NORA_SANDBOX_REMOTE_URL is required in remote mode"
            )
        if (
            not base_url.startswith("https://")
            and not allow_insecure
        ):
            raise RuntimeError(
                "NORA_SANDBOX_REMOTE_URL must use https:// unless "
                "NORA_SANDBOX_REMOTE_ALLOW_INSECURE=true"
            )
        try:
            request_timeout = float(
                os.getenv(
                    "NORA_SANDBOX_REMOTE_TIMEOUT_SECONDS",
                    "35",
                )
            )
        except ValueError as exc:
            raise RuntimeError(
                "NORA_SANDBOX_REMOTE_TIMEOUT_SECONDS must be numeric"
            ) from exc
        try:
            return RemoteSandboxRunner(
                base_url=base_url,
                token=token,
                request_timeout_seconds=request_timeout,
            )
        except ValueError as exc:
            raise RuntimeError(
                f"Invalid remote sandbox configuration: {exc}"
            ) from exc
    raise RuntimeError(f"Unsupported NORA_SANDBOX_MODE: {mode}")
