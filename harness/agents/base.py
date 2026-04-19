"""Core agent abstractions for the reusable harness.

The harness treats an agent as a small strategy object:
- `AgentConfig` captures the registry-loaded configuration for one agent.
- `AgentRunContext` captures per-run execution details such as mounts and image.
- `AgentAdapter` subclasses know how to translate that context into the
  concrete command needed to run one agent inside the task container.

This keeps the task runner generic. `harness/run_task.py` resolves an agent
config, looks up the corresponding adapter class in the registry, and then
calls `adapter.run(...)` for the agent step.
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class AgentConfig:
    name: str | None
    adapter: str
    env_passthrough: list[str]
    env_set: dict[str, str]
    adapter_config: dict[str, str]


@dataclass
class AgentRunContext:
    root: Path
    image: str
    runtime: str
    task_id: str
    task_description: str
    artifact_dir: Path
    run_dir: Path
    task_mount_dir: Path
    timeout_sec: int
    allow_network: bool


def parse_agent_config(path: Path) -> AgentConfig:
    """Parse the lightweight YAML subset used by agent config files.

    We intentionally keep this parser small because agent configs are simple
    and we want the harness to stay easy to run in minimal environments.
    """
    data: dict[str, Any] = {
        "name": None,
        "adapter": "",
        "env_passthrough": [],
        "env_set": {},
        "adapter_config": {},
    }
    section: str | None = None
    for raw_line in path.read_text().splitlines():
        if not raw_line.strip() or raw_line.strip().startswith("#"):
            continue
        if not raw_line.startswith(" "):
            if ":" not in raw_line:
                continue
            key, value = raw_line.split(":", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if value:
                data[key] = value
                section = None
            else:
                section = key
            continue
        if section == "env_passthrough":
            stripped = raw_line.strip()
            if stripped.startswith("- "):
                data["env_passthrough"].append(stripped[2:].strip().strip("'\""))
        elif section in {"env_set", "adapter_config"}:
            stripped = raw_line.strip()
            if ":" in stripped:
                key, value = stripped.split(":", 1)
                data[section][key.strip()] = value.strip().strip("'\"")
    if not data["adapter"]:
        raise ValueError(f"Agent config {path} is missing 'adapter'")
    return AgentConfig(
        name=data["name"],
        adapter=data["adapter"],
        env_passthrough=list(data["env_passthrough"]),
        env_set=dict(data["env_set"]),
        adapter_config=dict(data["adapter_config"]),
    )


class AgentAdapter(ABC):
    adapter_name: str = ""

    def __init__(self, config: AgentConfig):
        self.config = config

    @property
    def display_name(self) -> str:
        return self.config.name or self.adapter_name

    @property
    def env_passthrough(self) -> list[str]:
        return self.config.env_passthrough

    @property
    def env_set(self) -> dict[str, str]:
        return self.config.env_set

    @abstractmethod
    def build_agent_command(self, context: AgentRunContext) -> str:
        """Return the shell command executed inside the task container."""
        raise NotImplementedError

    def run(self, context: AgentRunContext) -> dict[str, Any]:
        """Run the adapter-managed agent step inside Docker or a local fallback."""
        started_at = time.time()
        stdout_path = context.artifact_dir / "agent_stdout.txt"
        stderr_path = context.artifact_dir / "agent_stderr.txt"
        command = self.build_agent_command(context)

        if context.runtime == "local":
            # Rewrite Docker paths (/work, /task, /agent_tools, /artifacts) to host paths
            _path_map = {
                "/agent_tools": str(context.root / "harness" / "agents"),
                "/work": str(context.run_dir),
                "/task": str(context.task_mount_dir),
                "/artifacts": str(context.artifact_dir),
            }
            for docker_path, host_path in _path_map.items():
                command = command.replace(docker_path, host_path)

            env = os.environ.copy()
            env["TASK_ID"] = context.task_id
            env["TASK_DESCRIPTION"] = context.task_description
            env["HARNESS_WORK_DIR"] = str(context.run_dir)
            env["HARNESS_TASK_DIR"] = str(context.task_mount_dir)
            env["HARNESS_ARTIFACT_DIR"] = str(context.artifact_dir)
            for env_var in self.env_passthrough:
                if os.getenv(env_var):
                    env[env_var] = os.getenv(env_var, "")
            for env_var, value in self.env_set.items():
                env[env_var] = value
            completed = subprocess.run(
                ["/bin/bash", "-lc", command],
                cwd=str(context.run_dir),
                text=True,
                capture_output=True,
                env=env,
                timeout=context.timeout_sec,
            )
            stdout_path.write_text(completed.stdout)
            stderr_path.write_text(completed.stderr)
            return {
                "step": "agent",
                "command": command,
                "container_name": None,
                "exit_code": completed.returncode,
                "timed_out": False,
                "duration_sec": round(time.time() - started_at, 3),
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
            }

        container_name = f"harness_{context.task_id}_agent_{uuid.uuid4().hex[:10]}"
        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "--network",
            "bridge" if context.allow_network else "none",
            "-v",
            f"{context.task_mount_dir}:/task:ro",
            "-v",
            f"{context.run_dir}:/work",
            "-v",
            f"{context.root / 'harness' / 'agents'}:/agent_tools:ro",
            "-w",
            "/work",
            "-e",
            f"TASK_ID={context.task_id}",
            "-e",
            f"TASK_DESCRIPTION={context.task_description}",
        ]
        for env_var in self.env_passthrough:
            if os.getenv(env_var):
                docker_cmd.extend(["-e", env_var])
        for env_var, value in self.env_set.items():
            docker_cmd.extend(["-e", f"{env_var}={value}"])
        docker_cmd.extend([context.image, "/bin/bash", "-lc", command])

        proc = subprocess.Popen(
            docker_cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        timed_out = False
        try:
            stdout, stderr = proc.communicate(timeout=context.timeout_sec)
        except subprocess.TimeoutExpired:
            timed_out = True
            subprocess.run(["docker", "rm", "-f", container_name], text=True, capture_output=True)
            stdout, stderr = proc.communicate()
        stdout_path.write_text(stdout)
        stderr_path.write_text(stderr)
        return {
            "step": "agent",
            "command": command,
            "container_name": container_name,
            "exit_code": None if timed_out else proc.returncode,
            "timed_out": timed_out,
            "duration_sec": round(time.time() - started_at, 3),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }
