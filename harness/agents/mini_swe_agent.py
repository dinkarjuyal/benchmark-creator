"""mini-SWE-agent adapter.

This module owns both:
- the `MiniSweAgentAdapter` class used by the harness registry
- the concrete mini-SWE-agent invocation logic used inside the task container

The harness itself only deals with the adapter class. The helper entrypoint at
the bottom exists purely so the adapter can invoke this same module inside the
container without duplicating logic elsewhere.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from harness.agents.base import AgentConfig, AgentRunContext

try:
    from harness.agents.base import AgentAdapter
except ModuleNotFoundError:
    AgentAdapter = object


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run mini-SWE-agent in the current container.")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--model")
    parser.add_argument("--model-class")
    parser.add_argument("--config", action="append", default=[])
    parser.add_argument("--output-name", default="mini.traj.json")
    return parser.parse_args()


def run_mini_swe_agent(
    *,
    workspace: str,
    prompt_file: str,
    model: str | None = None,
    model_class: str | None = None,
    config_specs: list[str] | None = None,
    output_name: str = "mini.traj.json",
) -> int:
    workspace_path = Path(workspace).resolve()
    prompt_path = Path(prompt_file).resolve()
    prompt = prompt_path.read_text()

    logs_dir = workspace_path / ".agent_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    output_path = logs_dir / output_name
    config_dir = logs_dir / "mini_config"
    config_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["MSWEA_GLOBAL_CONFIG_DIR"] = str(config_dir)
    env["MSWEA_SILENT_STARTUP"] = "1"
    env["MSWEA_CONFIGURED"] = "true"

    cmd = [
        "mini",
        "-c",
        "mini.yaml",
        "-c",
        f"environment.cwd={workspace_path}",
        "-o",
        str(output_path),
        "-t",
        prompt,
        "-y",
        "--exit-immediately",
    ]
    if model:
        cmd.extend(["-m", model])
    if model_class:
        cmd.extend(["--model-class", model_class])
    for config_spec in (config_specs or []):
        cmd.extend(["-c", config_spec])

    completed = subprocess.run(
        cmd,
        cwd=str(workspace_path),
        env=env,
        text=True,
        capture_output=True,
    )

    (logs_dir / "mini_stdout.txt").write_text(completed.stdout)
    (logs_dir / "mini_stderr.txt").write_text(completed.stderr)
    (logs_dir / "mini_command.json").write_text(json.dumps({"cmd": cmd}, indent=2))

    print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=os.sys.stderr)
    return completed.returncode


class MiniSweAgentAdapter(AgentAdapter):
    adapter_name = "mini_swe_agent"

    def build_agent_command(self, context: AgentRunContext) -> str:
        cmd = [
            "python",
            "/agent_tools/mini_swe_agent.py",
            "--workspace",
            "/work",
            "--prompt-file",
            "/task/prompt.txt",
        ]
        if model := self.config.adapter_config.get("model"):
            cmd.extend(["--model", model])
        if model_class := self.config.adapter_config.get("model_class"):
            cmd.extend(["--model-class", model_class])
        if output_name := self.config.adapter_config.get("output_name"):
            cmd.extend(["--output-name", output_name])
        config_specs = self.config.adapter_config.get("config_specs", "")
        if config_specs:
            for spec in [part.strip() for part in config_specs.split("||") if part.strip()]:
                cmd.extend(["--config", spec])
        return shlex.join(cmd)


def main() -> int:
    args = parse_args()
    return run_mini_swe_agent(
        workspace=args.workspace,
        prompt_file=args.prompt_file,
        model=args.model,
        model_class=args.model_class,
        config_specs=args.config,
        output_name=args.output_name,
    )


if __name__ == "__main__":
    raise SystemExit(main())
