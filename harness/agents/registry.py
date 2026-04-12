"""Registry of agent adapter classes.

Agent configs name an adapter, for example `mini_swe_agent`. The harness loads
the config, looks up the corresponding adapter class here, and instantiates it
before running the task's agent step.
"""

from __future__ import annotations

from harness.agents.base import AgentAdapter, AgentConfig
from harness.agents.mini_swe_agent import MiniSweAgentAdapter


_REGISTRY: dict[str, type[AgentAdapter]] = {
    MiniSweAgentAdapter.adapter_name: MiniSweAgentAdapter,
}


def get_agent_adapter(config: AgentConfig) -> AgentAdapter:
    try:
        adapter_cls = _REGISTRY[config.adapter]
    except KeyError as exc:
        raise ValueError(f"Unknown agent adapter: {config.adapter!r}") from exc
    return adapter_cls(config)
