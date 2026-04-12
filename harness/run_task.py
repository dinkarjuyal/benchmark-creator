#!/usr/bin/env python3
"""Run one benchmark task inside Docker and score the resulting workspace.

Task contract:
- Each task lives in its own directory and includes a `task.json`.
- Public task assets live in files that the agent/setup step may read, such as
  `prompt.txt` and anything under `public/`.
- Private validation assets live outside that public surface and are only
  mounted into the validator step.
- Optional starter files under `template/` are copied into a fresh per-run
  workspace before execution.

Execution model:
1. Prepare an isolated workspace and artifact directory for one trial.
2. Mount public task assets plus the workspace into a Docker container.
3. Optionally run task-specific setup in the container.
4. Resolve the requested agent config to an adapter class via the agent registry.
5. Call `adapter.run(...)` so the adapter can run the agent in the same base
   image against the workspace.
6. Write runtime context for the validator, including prompt text and step logs.
7. Mount the full task directory only for the validator step and parse the
   validator's JSON output as the task score.

Directory roles:
- `/work` is the editable task workspace. The agent is expected to read and
  modify files here.
- `/task` is the task mount. During setup/agent it contains only public assets
  such as `prompt.txt` and `public/`. During validation it contains the full
  task directory, including private validator code.
- `/agent_tools` is a read-only mount for harness-provided agent adapters.
- `/artifacts` is the per-run output directory for logs, metadata, prompt
  snapshots, and any auxiliary outputs. It is mounted for setup and validation,
  but intentionally not mounted for the agent step so validators and run
  metadata are not exposed there.

Credential handling:
- Common model-provider credentials from the host environment are passed through
  to the container by variable name only, e.g. `ANTHROPIC_API_KEY`. The secret
  value is not embedded into the task spec or recorded in the step command.

Assumptions:
- The Docker image already contains any runtime needed by setup, agent, and
  validator commands.
- Normal runs select an agent adapter at runtime via `--agent` or
  `--agent-config`. The harness maps that config to an adapter class from the
  registry and calls its `run(...)` method.
- Validators must print a JSON object to stdout containing at least `score`.
- Real API-backed agents may require outbound network access. Use
  `--allow-agent-network` when you want the agent step to reach remote model
  APIs; setup and validator still run with network disabled.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness.agents.base import AgentRunContext, parse_agent_config
from harness.agents.registry import get_agent_adapter


ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "results" / "runs"
PASSTHROUGH_ENV_VARS = [
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENROUTER_API_KEY",
    "LITELLM_API_KEY",
]


class HarnessError(RuntimeError):
    pass


@dataclass
class TaskSpec:
    task_dir: Path
    task_id: str
    description: str
    image: str
    dockerfile: Path | None
    timeout_sec: int
    prompt_file: Path | None
    public_dir: Path | None
    setup_command: str | None
    validator_command: str | None
    template_dir: Path | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a task in Docker and validate the result."
    )
    parser.add_argument("task", help="Path to a task directory that contains task.json")
    parser.add_argument(
        "--agent-command",
        help="Escape hatch for directly specifying the agent step command.",
    )
    parser.add_argument(
        "--agent-config",
        help="Path to an agent_config.yaml that selects the adapter and adapter settings.",
    )
    parser.add_argument(
        "--agent",
        help="Agent config name under --agent-registry, without the .yaml suffix.",
    )
    parser.add_argument(
        "--agent-registry",
        default=str(ROOT / "agents"),
        help="Directory containing reusable agent_config.yaml files.",
    )
    parser.add_argument(
        "--results-dir",
        default=str(RESULTS_DIR),
        help="Directory where run artifacts are written.",
    )
    parser.add_argument(
        "--build-missing-image",
        action="store_true",
        help="Build the task image from task.json if it is missing locally.",
    )
    parser.add_argument(
        "--keep-run-dir",
        action="store_true",
        help="Keep the copied workspace under the result directory for inspection.",
    )
    parser.add_argument(
        "--trial-index",
        type=int,
        default=0,
        help="Optional trial index recorded in the result metadata.",
    )
    parser.add_argument(
        "--allow-agent-network",
        action="store_true",
        help="Allow outbound network access during the agent step.",
    )
    return parser.parse_args()


def load_task(task_dir: Path) -> TaskSpec:
    config_path = task_dir / "task.json"
    if not config_path.exists():
        raise HarnessError(f"Missing task definition: {config_path}")

    raw = json.loads(config_path.read_text())
    task_id = raw["id"]
    template_dir = task_dir / raw["template_dir"] if raw.get("template_dir") else None
    dockerfile = task_dir / raw["dockerfile"] if raw.get("dockerfile") else None
    prompt_file = task_dir / raw["prompt_file"] if raw.get("prompt_file") else None
    public_dir = task_dir / raw["public_dir"] if raw.get("public_dir") else None

    if template_dir and not template_dir.exists():
        raise HarnessError(f"Missing template directory: {template_dir}")
    if dockerfile and not dockerfile.exists():
        raise HarnessError(f"Missing dockerfile: {dockerfile}")
    if prompt_file and not prompt_file.exists():
        raise HarnessError(f"Missing prompt file: {prompt_file}")
    if public_dir and not public_dir.exists():
        raise HarnessError(f"Missing public directory: {public_dir}")
    if raw.get("validator_command") is None:
        raise HarnessError("task.json must define validator_command")

    return TaskSpec(
        task_dir=task_dir,
        task_id=task_id,
        description=raw.get("description", ""),
        image=raw["image"],
        dockerfile=dockerfile,
        timeout_sec=int(raw.get("timeout_sec", 300)),
        prompt_file=prompt_file,
        public_dir=public_dir,
        setup_command=raw.get("setup_command"),
        validator_command=raw.get("validator_command"),
        template_dir=template_dir,
    )


def run_checked(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            check=True,
            text=True,
            capture_output=True,
            **kwargs,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise HarnessError(detail) from exc


def ensure_docker_available() -> None:
    probe = subprocess.run(
        ["docker", "info"],
        text=True,
        capture_output=True,
    )
    if probe.returncode != 0:
        detail = probe.stderr.strip() or probe.stdout.strip()
        raise HarnessError(
            "Docker is unavailable. Start the Docker daemon and retry. "
            f"Details: {detail}"
        )


def ensure_image(task: TaskSpec, build_missing: bool) -> None:
    inspect = subprocess.run(
        ["docker", "image", "inspect", task.image],
        text=True,
        capture_output=True,
    )
    if inspect.returncode == 0:
        return
    if not build_missing:
        raise HarnessError(
            f"Docker image '{task.image}' is missing. Re-run with --build-missing-image."
        )
    if task.dockerfile is None:
        raise HarnessError(
            f"Docker image '{task.image}' is missing and no dockerfile is configured."
        )

    print(f"Building image {task.image} from {task.dockerfile}...", flush=True)
    run_checked(
        [
            "docker",
            "build",
            "-t",
            task.image,
            "-f",
            str(task.dockerfile),
            str(ROOT),
        ]
    )


def prepare_run_dir(task: TaskSpec, results_root: Path, keep_run_dir: bool) -> tuple[Path, Path]:
    run_id = f"{task.task_id}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    artifact_dir = results_root / task.task_id / run_id
    artifact_dir.mkdir(parents=True, exist_ok=False)

    if keep_run_dir:
        run_dir = artifact_dir / "workspace"
        run_dir.mkdir()
    else:
        run_dir = Path(tempfile.mkdtemp(prefix=f"{task.task_id}_", dir=str(results_root)))

    if task.template_dir:
        shutil.copytree(task.template_dir, run_dir, dirs_exist_ok=True)

    return artifact_dir, run_dir


def prepare_public_task_dir(task: TaskSpec, artifact_dir: Path) -> Path:
    public_task_dir = artifact_dir / "task_public"
    public_task_dir.mkdir()

    if task.prompt_file is not None:
        shutil.copy2(task.prompt_file, public_task_dir / task.prompt_file.name)
    if task.public_dir is not None:
        shutil.copytree(task.public_dir, public_task_dir / task.public_dir.name, dirs_exist_ok=True)

    return public_task_dir


def redact_agent_config_text(agent_config_path: Path) -> str:
    lines = agent_config_path.read_text().splitlines()
    redacted_lines: list[str] = []
    in_block = False
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            redacted_lines.append(raw_line)
            continue
        if not in_block:
            redacted_lines.append(raw_line)
            if stripped == "env_set:":
                in_block = True
            continue
        if raw_line.startswith("  ") and ":" in stripped:
            key = stripped.split(":", 1)[0]
            indent = raw_line[: len(raw_line) - len(raw_line.lstrip(" "))]
            redacted_lines.append(f"{indent}{key}: REDACTED")
            continue
        in_block = False
        redacted_lines.append(raw_line)
    return "\n".join(redacted_lines) + ("\n" if lines else "")


def resolve_agent_runtime(args: argparse.Namespace) -> tuple[Path | None, str, str | None, list[str], Any | None]:
    provided = sum(bool(value) for value in [args.agent_command, args.agent_config, args.agent])
    if provided != 1:
        raise HarnessError(
            "Provide exactly one of --agent-command, --agent-config, or --agent."
        )

    if args.agent_command:
        return None, "custom_command", args.agent_command, PASSTHROUGH_ENV_VARS, None

    if args.agent:
        agent_config_path = Path(args.agent_registry).resolve() / f"{args.agent}.yaml"
    else:
        agent_config_path = Path(args.agent_config).resolve()

    if not agent_config_path.exists():
        raise HarnessError(f"Missing agent config: {agent_config_path}")
    parsed_config = parse_agent_config(agent_config_path)
    agent_name = parsed_config.name or parsed_config.adapter
    requested_envs = parsed_config.env_passthrough
    missing_envs = [env_var for env_var in requested_envs if not os.getenv(env_var)]
    if missing_envs:
        raise HarnessError(
            f"Missing required agent env vars on the host: {', '.join(missing_envs)}"
        )
    adapter = get_agent_adapter(parsed_config)
    return agent_config_path, agent_name, None, requested_envs, adapter


def run_container_step(
    task: TaskSpec,
    command: str,
    artifact_dir: Path,
    run_dir: Path,
    task_mount_dir: Path,
    agent_config_path: Path | None,
    agent_env_vars: list[str],
    step_name: str,
    timeout_sec: int,
    mount_artifacts: bool,
    allow_network: bool,
) -> dict[str, Any]:
    started_at = time.time()
    container_name = f"harness_{task.task_id}_{step_name}_{uuid.uuid4().hex[:10]}"
    stdout_path = artifact_dir / f"{step_name}_stdout.txt"
    stderr_path = artifact_dir / f"{step_name}_stderr.txt"

    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--network",
        "bridge" if allow_network else "none",
        "-v",
        f"{task_mount_dir}:/task:ro",
        "-v",
        f"{run_dir}:/work",
        "-v",
        f"{ROOT / 'harness' / 'agents'}:/agent_tools:ro",
    ]
    if agent_config_path is not None:
        docker_cmd.extend(["-v", f"{agent_config_path}:/agent_config/agent_config.yaml:ro"])
    if mount_artifacts:
        docker_cmd.extend(["-v", f"{artifact_dir}:/artifacts"])
    docker_cmd.extend(
        [
            "-w",
            "/work",
            "-e",
            f"TASK_ID={task.task_id}",
            "-e",
            f"TASK_DESCRIPTION={task.description}",
            "-e",
            "HARNESS_AGENT_TOOLS_DIR=/agent_tools",
        ]
    )
    for env_var in agent_env_vars:
        if os.getenv(env_var):
            docker_cmd.extend(["-e", env_var])
    docker_cmd.extend(
        [
            task.image,
            "/bin/bash",
            "-lc",
            command,
        ]
    )

    proc = subprocess.Popen(
        docker_cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        timed_out = True
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            text=True,
            capture_output=True,
        )
        stdout, stderr = proc.communicate()
    duration_sec = round(time.time() - started_at, 3)

    stdout_path.write_text(stdout)
    stderr_path.write_text(stderr)

    return {
        "step": step_name,
        "command": command,
        "container_name": container_name,
        "exit_code": None if timed_out else proc.returncode,
        "timed_out": timed_out,
        "duration_sec": duration_sec,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }


def write_runtime_context(
    task: TaskSpec,
    artifact_dir: Path,
    run_dir: Path,
    prompt_text: str | None,
    step_results: list[dict[str, Any]],
) -> Path:
    context = {
        "task_id": task.task_id,
        "description": task.description,
        "task_dir": str(task.task_dir),
        "run_dir": str(run_dir),
        "artifact_dir": str(artifact_dir),
        "container_task_dir": "/task",
        "container_run_dir": "/work",
        "container_artifact_dir": "/artifacts",
        "prompt": prompt_text,
        "steps": step_results,
    }
    context_path = artifact_dir / "runtime_context.json"
    context_path.write_text(json.dumps(context, indent=2))
    return context_path


def parse_validation_output(stdout: str) -> dict[str, Any]:
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise HarnessError(f"Validator did not return valid JSON:\n{stdout}") from exc


def load_prompt_text(task: TaskSpec) -> str | None:
    if task.prompt_file is None:
        return None
    return task.prompt_file.read_text()


def collect_agent_logs(run_dir: Path, artifact_dir: Path) -> str | None:
    source = run_dir / ".agent_logs"
    if not source.exists():
        return None
    destination = artifact_dir / "agent_logs"
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return str(destination)


def main() -> int:
    args = parse_args()
    task_dir = Path(args.task).resolve()
    results_root = Path(args.results_dir).resolve()
    results_root.mkdir(parents=True, exist_ok=True)

    try:
        task = load_task(task_dir)
        ensure_docker_available()
        ensure_image(task, build_missing=args.build_missing_image)

        artifact_dir, run_dir = prepare_run_dir(task, results_root, args.keep_run_dir)
        public_task_dir = prepare_public_task_dir(task, artifact_dir)
        agent_config_path, agent_name, agent_command, agent_env_vars, agent_adapter = resolve_agent_runtime(args)
        redacted_agent_config_path = None
        if agent_config_path is not None:
            redacted_agent_config_path = artifact_dir / "agent_config.redacted.yaml"
            redacted_agent_config_path.write_text(redact_agent_config_text(agent_config_path))
        prompt_text = load_prompt_text(task)
        if prompt_text is not None:
            (artifact_dir / "prompt.txt").write_text(prompt_text)

        step_results: list[dict[str, Any]] = []

        if task.setup_command:
            step_results.append(
                run_container_step(
                    task,
                    task.setup_command,
                    artifact_dir,
                    run_dir,
                    public_task_dir,
                    agent_config_path,
                    agent_env_vars,
                    step_name="setup",
                    timeout_sec=task.timeout_sec,
                    mount_artifacts=True,
                    allow_network=False,
                )
            )

        if agent_adapter is None:
            step_results.append(
                run_container_step(
                    task,
                    agent_command,
                    artifact_dir,
                    run_dir,
                    public_task_dir,
                    agent_config_path,
                    agent_env_vars,
                    step_name="agent",
                    timeout_sec=task.timeout_sec,
                    mount_artifacts=False,
                    allow_network=args.allow_agent_network,
                )
            )
        else:
            step_results.append(
                agent_adapter.run(
                    AgentRunContext(
                        root=ROOT,
                        image=task.image,
                        task_id=task.task_id,
                        task_description=task.description,
                        artifact_dir=artifact_dir,
                        run_dir=run_dir,
                        task_mount_dir=public_task_dir,
                        timeout_sec=task.timeout_sec,
                        allow_network=args.allow_agent_network,
                    )
                )
            )
        agent_logs_dir = collect_agent_logs(run_dir, artifact_dir)

        context_path = write_runtime_context(task, artifact_dir, run_dir, prompt_text, step_results)
        validator_step = run_container_step(
            task,
            task.validator_command,
            artifact_dir,
            run_dir,
            task.task_dir,
            agent_config_path,
            agent_env_vars,
            step_name="validator",
            timeout_sec=task.timeout_sec,
            mount_artifacts=True,
            allow_network=False,
        )
        step_results.append(validator_step)
        validation = parse_validation_output(Path(validator_step["stdout_path"]).read_text())

        result = {
            "task_id": task.task_id,
            "trial_index": args.trial_index,
            "agent_name": agent_name,
            "description": task.description,
            "artifact_dir": str(artifact_dir),
            "run_dir": str(run_dir),
            "public_task_dir": str(public_task_dir),
            "agent_config_path": str(agent_config_path) if agent_config_path else None,
            "agent_config_redacted_path": (
                str(redacted_agent_config_path) if redacted_agent_config_path else None
            ),
            "agent_env_vars": agent_env_vars,
            "prompt_path": str(artifact_dir / "prompt.txt") if prompt_text is not None else None,
            "agent_logs_dir": agent_logs_dir,
            "runtime_context_path": str(context_path),
            "steps": step_results,
            "validation": validation,
        }
        (artifact_dir / "result.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))

        if not args.keep_run_dir and run_dir.exists():
            shutil.rmtree(run_dir)

        return 0 if float(validation.get("score", 0.0)) >= 1.0 else 1
    except HarnessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
