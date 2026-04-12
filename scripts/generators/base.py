"""Base types shared by all task generators."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TaskCandidate:
    """Everything needed to emit one harness-compatible task directory."""

    task_id: str
    task_type: str          # invariant_recovery | contract_extension | noop | impossible |
                            # behavioral_refactor | semantic_equivalence | structural_mining
    family: str             # scheduler | middleware | request | response | settings |
                            # pipeline | spider | selector
    difficulty: int         # 1-5 (dependency depth, not code volume)
    prompt: str             # text shown to agent
    # {relative_path: new_content} — patches applied on top of pinned scrapy checkout
    start_state_patches: dict[str, str] = field(default_factory=dict)
    visible_tests: list[str] = field(default_factory=list)   # shown to agent
    hidden_tests: list[str] = field(default_factory=list)    # only run by validator
    structural_checks: list[str] = field(default_factory=list)  # AST assertions as Python snippets
    generation_recipe: str = ""   # human-readable description of how this was generated
    is_noop: bool = False
    is_impossible: bool = False
    extra_template_files: dict[str, str] = field(default_factory=dict)  # other files for template/
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def score_bands(self) -> str:
        return (
            "0.0-0.2: invalid/broken setup | "
            "0.2-0.6: partial behavior recovery | "
            "0.6-0.9: core fixed but regressions remain | "
            "0.9-1.0: semantically correct and regression-safe"
        )


class BaseGenerator(ABC):
    """Abstract base for all task generators."""

    def __init__(self, scrapy_root: Path) -> None:
        self.scrapy_root = scrapy_root

    @abstractmethod
    def generate(self) -> list[TaskCandidate]:
        """Return a list of TaskCandidate instances."""
        ...

    def _read(self, relative_path: str) -> str:
        return (self.scrapy_root / relative_path).read_text()

    def _exists(self, relative_path: str) -> bool:
        return (self.scrapy_root / relative_path).exists()
