"""Plugin registry for benchmark generation strategies.

Any module can register a new strategy with the @register_strategy decorator.
The CLI discovers strategies at import time by importing adversarial_mc (which
registers all built-in strategies at module load).

Usage:
    from scripts.generators.strategy_registry import get_strategy, list_strategies

    StrategyCls = get_strategy("sgs")
    strategy = StrategyCls(api_key="sk-ant-...")
    candidates = strategy.generate(families=families, n_per_family=3)

To add a new strategy:
    from scripts.generators.strategy_registry import register_strategy, GenerationStrategy

    @register_strategy("my_strategy")
    class MyStrategy(GenerationStrategy):
        \"\"\"One-line description shown in --help.\"\"\"
        def __init__(self, api_key, verbose=False, seed=None):
            ...
        def generate(self, families, n_per_family=3):
            ...
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scripts.generators.pandas_mc import MCTaskCandidate


class GenerationStrategy(ABC):
    """Plugin interface for benchmark question generation.

    Each strategy encapsulates a complete method for producing MCTaskCandidate
    objects from pre-extracted behavioral families. All strategies share the
    same input/output contract — RepoAnalyzer (upstream) and write_mc_task
    (downstream) are strategy-agnostic.

    Required class attribute:
        name (str): registry key, e.g. "adversarial", "knowledge", "sgs"

    Constructor convention (for CLI compatibility):
        __init__(self, api_key: str, verbose: bool = False, seed: int | None = None)
    """

    name: str  # set by @register_strategy decorator

    @abstractmethod
    def generate(
        self,
        families: list[dict],
        n_per_family: int = 3,
    ) -> list["MCTaskCandidate"]:
        """Generate question candidates from behavioral families.

        Args:
            families: list of family dicts with keys:
                name (str), description (str), seed_rules (list[str]),
                install (str), library_name (str)
            n_per_family: target number of questions per family per seed rule

        Returns:
            list of MCTaskCandidate objects, execution-verified
        """
        ...

    @classmethod
    def description(cls) -> str:
        """One-line description for --help output."""
        if cls.__doc__:
            return cls.__doc__.strip().splitlines()[0]
        return getattr(cls, "name", cls.__name__)


# ── Registry ──────────────────────────────────────────────────────────────────

_REGISTRY: dict[str, type[GenerationStrategy]] = {}


def register_strategy(name: str):
    """Class decorator: register a GenerationStrategy subclass under `name`.

    Usage:
        @register_strategy("my_strategy")
        class MyStrategy(GenerationStrategy):
            ...
    """
    def decorator(cls: type[GenerationStrategy]) -> type[GenerationStrategy]:
        cls.name = name
        _REGISTRY[name] = cls
        return cls
    return decorator


def get_strategy(name: str) -> type[GenerationStrategy]:
    """Look up a strategy class by name.

    Raises ValueError with available names if `name` is not registered.
    """
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY)) or "(none registered)"
        raise ValueError(
            f"Unknown strategy {name!r}. Available: {available}"
        )
    return _REGISTRY[name]


def list_strategies() -> list[str]:
    """Return sorted list of all registered strategy names."""
    return sorted(_REGISTRY)
