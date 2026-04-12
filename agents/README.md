Reusable agent configs live here.

Each config selects:

- an adapter name from `harness/agents/registry.py`
- optional environment variables to pass into the container
- adapter-specific settings under `adapter_config`

Examples:

- `mini_deterministic.yaml`: local smoke-test config for the example task
- `mini_claude_haiku_4_5.yaml`: Anthropic-backed `mini-swe-agent` config

These files are benchmark-agnostic. The harness loads them at runtime with
`--agent <name>` or `--agent-config <path>`.
