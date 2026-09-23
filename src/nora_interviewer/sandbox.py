from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from time import perf_counter
from typing import Protocol

from pydantic import Field

from .models import StrictModel


class SandboxUnavailable(RuntimeError):
    pass


class SandboxLimits(StrictModel):
    timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    memory_mb: int = Field(default=256, ge=64, le=2048)
    cpus: float = Field(default=0.5, gt=0, le=4)
    pids_limit: int = Field(default=64, ge=16, le=512)


class SandboxResult(StrictModel):
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    duration_ms: int = Field(ge=0)


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
            (root / "solution.py").write_text(source, encoding="utf-8")
            (root / "harness.py").write_text(harness, encoding="utf-8")

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
            )


def default_sandbox_runner() -> SandboxRunner:
    mode = os.getenv("NORA_SANDBOX_MODE", "disabled").strip().lower()
    if mode == "disabled":
        return DisabledSandboxRunner()
    if mode == "docker":
        image = os.getenv("NORA_SANDBOX_IMAGE", "python:3.12-alpine").strip()
        return DockerSandboxRunner(image=image)
    raise RuntimeError(f"Unsupported NORA_SANDBOX_MODE: {mode}")
