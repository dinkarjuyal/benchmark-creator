"""Adversarial two-player confounding question generator.

The game:
  Player 1 (Proposer)  — Claude establishes a belief: a rule about a library that practitioners know.
  Player 2 (Adversary) — Claude finds a confounder: where that belief breaks non-obviously.
  Python executor      — verifies the confounder actually produces surprising output.

Repo-agnostic: families and seed rules are either supplied directly or extracted from a
repo README/docs by RepoAnalyzer.

Output: MCTaskCandidate objects compatible with the existing write_mc_task / harness pipeline.

Usage:
    # With explicit families (pandas default)
    gen = AdversarialMCGenerator(api_key="sk-ant-...")
    candidates = gen.generate(n_per_family=3)

    # Pointed at any repo
    families = RepoAnalyzer(api_key="sk-ant-...").extract_families(readme_text)
    candidates = gen.generate(families=families, n_per_family=3)
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from typing import Any

import anthropic

from scripts.generators.pandas_mc import MCTaskCandidate

# ── Families to probe ──────────────────────────────────────────────────────────
FAMILIES: list[dict] = [
    {
        "name": "groupby_semantics",
        "description": "groupby sort, observed, dropna, transform vs agg",
        "seed_rules": [
            "sort=False makes group keys appear in insertion order",
            "transform() returns a Series aligned to the original index",
            "observed=False includes groups for unused Categorical categories",
        ],
    },
    {
        "name": "dtype_coercion",
        "description": "int/float promotion, apply dtype reconstruction, nullable int",
        "seed_rules": [
            "Series.apply() with a scalar-returning lambda can change the dtype",
            "Adding a float to an int Series promotes the dtype to float64",
            "pd.array with dtype='Int64' (capital I) can hold NA; 'int64' cannot",
        ],
    },
    {
        "name": "nan_semantics",
        "description": "NaN in groupby, arithmetic, comparisons, fillna",
        "seed_rules": [
            "NaN != NaN is True in Python (float IEEE semantics)",
            "groupby by default drops NaN keys (dropna=True)",
            "fillna(method='ffill') does not fill the first element if it is NaN",
        ],
    },
    {
        "name": "index_alignment",
        "description": "concat, merge, arithmetic index alignment",
        "seed_rules": [
            "Adding two Series aligns on index labels, not position",
            "pd.concat ignores the original index when ignore_index=True",
            "merge on key columns drops the index; join() preserves it",
        ],
    },
    {
        "name": "copy_semantics",
        "description": "view vs copy, chained assignment, copy(deep=False)",
        "seed_rules": [
            "df.copy() with default deep=True returns a fully independent copy",
            "Slicing a DataFrame with iloc returns a view, not a copy",
            "Assigning to df['col'][mask] may not modify df (chained assignment)",
        ],
    },
]


# ── Prompts ───────────────────────────────────────────────────────────────────

_PLAYER1_SYSTEM = """\
You are designing a Python/pandas quiz. Propose a TRUE rule about pandas behavior \
that most ML practitioners have likely learned.

Respond using ONLY these tags — no other text:

<rule>One-sentence true pandas rule</rule>
<snippet>
Short Python snippet demonstrating the rule (include necessary imports, print exactly one line)
</snippet>"""

_PLAYER1_USER = """\
Family: {family_name} — {family_description}
Seed rule to build on: "{seed_rule}"
Library install: {install_line}

Requirements:
- Rule must be specific enough to make a clear prediction
- Snippet must be runnable after: {install_line}
- Snippet must print exactly one line
- Keep snippet under 6 lines of code"""

_PLAYER2_SYSTEM = """\
You are an adversary designing Python/pandas trick questions. \
Given a rule that a model believes, find a case where the rule BREAKS non-obviously \
— where the model would confidently apply the rule and get the wrong answer.

Respond using ONLY these tags — no other text:

<snippet>
Short Python snippet that VIOLATES the rule non-obviously (include necessary imports, print one line)
</snippet>
<why_wrong>One sentence: which part of the rule the model incorrectly applies here</why_wrong>
<rule_predicts>The EXACT output string the model would expect (e.g. "[1, 2, 3]" or "float64") — no explanation</rule_predicts>"""

_PLAYER2_USER = """\
Rule: "{rule}"

Confirming case (rule HOLDS here):
{confirming_snippet}
Actual output: {confirming_output}

Find a variation where a model would expect the rule to apply, but the output differs.

Requirements:
- Use the same pandas API as the confirming case
- Must look superficially similar to the confirming case
- Must NOT be a trivially obvious edge case
- Snippet must run with only pandas + numpy and print exactly one line"""

_DISTRACTORS_SYSTEM = """\
You are building a multiple-choice question. Given the correct answer, generate \
two plausible wrong answers representing different misconceptions.

Respond using ONLY these tags — no other text:

<distractor_c>wrong answer text</distractor_c>
<misconception_c>one-sentence explanation of the wrong mental model</misconception_c>
<distractor_d>wrong answer text</distractor_d>
<misconception_d>one-sentence explanation of the wrong mental model</misconception_d>"""

_DISTRACTORS_USER = """\
Rule: {rule}
Code snippet:
{snippet}
Correct output: {correct_output}
Hard negative (rule naively applied): {rule_predicts}

Requirements:
- Neither distractor should equal the correct output or the hard negative
- Each represents a specific wrong mental model
- Format as printed output (e.g. "float64" or "[1, 2, 3]")"""


_REPO_ANALYZER_SYSTEM = """\
You are analyzing a Python library to design a behavioral benchmark.
Extract the behavioral families that are most likely to produce confident-but-wrong answers
— areas where practitioners learn a rule that has non-obvious exceptions.

Respond using ONLY these tags, repeated once per family (3–6 families total):

<family>
<name>short_snake_case_name</name>
<description>one-line description of the behavioral area</description>
<seed_rule>A true rule a practitioner would know</seed_rule>
<seed_rule>Another true rule in this family</seed_rule>
<seed_rule>A third true rule</seed_rule>
<install>pip install package_name</install>
</family>"""

_REPO_ANALYZER_USER = """\
Library: {library_name}
README / documentation excerpt (first 3000 chars):
{readme_excerpt}

Extract 3–6 behavioral families where a practitioner might overgeneralize a known rule.
Focus on: default parameter values, dtype/type coercion, alignment semantics, copy-vs-view,
NaN/null handling, ordering guarantees, or any library-specific gotcha area."""


# ── Core execution ────────────────────────────────────────────────────────────

def _run_snippet(snippet: str, timeout: int = 10) -> tuple[bool, str]:
    """Execute snippet in a subprocess. Returns (success, stdout_or_error)."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"ERROR: timed out after {timeout}s"
    if result.returncode != 0:
        return False, f"ERROR: {result.stderr.strip()[:200]}"
    return True, result.stdout.strip()


def _task_id_from_rule(rule: str, family: str) -> str:
    h = hashlib.md5(f"{family}:{rule}".encode()).hexdigest()[:8]
    slug = rule.lower()[:40]
    slug = "".join(c if c.isalnum() else "_" for c in slug).strip("_")
    slug = "_".join(p for p in slug.split("_") if p)[:30]
    return f"adv_{family[:8]}_{slug}_{h}"


def _tag_all(text: str, tag: str) -> list[str]:
    """Extract all occurrences of <tag>...</tag> from text."""
    results = []
    open_tag, close_tag = f"<{tag}>", f"</{tag}>"
    pos = 0
    while True:
        start = text.find(open_tag, pos)
        if start == -1:
            break
        end = text.find(close_tag, start)
        if end == -1:
            break
        results.append(text[start + len(open_tag):end].strip())
        pos = end + len(close_tag)
    return results


class RepoAnalyzer:
    """Extract behavioral families and seed rules from a repo's README/docs.

    This makes AdversarialMCGenerator repo-agnostic: point it at any Python
    library and it will discover the behavioral areas most likely to produce
    confident-but-wrong answers.

    Usage:
        analyzer = RepoAnalyzer(api_key="sk-ant-...")
        readme = Path("path/to/README.md").read_text()
        families = analyzer.extract_families(readme, library_name="requests")
        # → list[dict] compatible with AdversarialMCGenerator.generate(families=...)
    """

    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-6"):
        self.client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self.model = model

    def extract_families(self, readme_text: str, library_name: str = "the library") -> list[dict]:
        """Return families list compatible with AdversarialMCGenerator."""
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=_REPO_ANALYZER_SYSTEM,
            messages=[{"role": "user", "content": _REPO_ANALYZER_USER.format(
                library_name=library_name,
                readme_excerpt=readme_text[:3000],
            )}],
        )
        raw = msg.content[0].text

        families = []
        for block in _tag_all(raw, "family"):
            name = next(iter(_tag_all(block, "name")), "")
            description = next(iter(_tag_all(block, "description")), "")
            seed_rules = _tag_all(block, "seed_rule")
            install = next(iter(_tag_all(block, "install")), "")
            if name and seed_rules:
                families.append({
                    "name": name,
                    "description": description,
                    "seed_rules": seed_rules,
                    "install": install,  # e.g. "pip install requests" for snippet preamble
                })
        return families

    @staticmethod
    def from_github(repo_url: str) -> str:
        """Fetch README text from a GitHub repo URL (converts to raw content URL)."""
        import urllib.request
        # Convert https://github.com/user/repo → raw README
        repo_url = repo_url.rstrip("/")
        if "github.com" in repo_url:
            parts = repo_url.split("github.com/")[-1].split("/")
            owner, name = parts[0], parts[1]
            for branch in ("main", "master"):
                for fname in ("README.md", "README.rst", "README.txt", "README"):
                    raw_url = f"https://raw.githubusercontent.com/{owner}/{name}/{branch}/{fname}"
                    try:
                        with urllib.request.urlopen(raw_url, timeout=10) as r:
                            return r.read().decode("utf-8", errors="replace")
                    except Exception:
                        continue
        raise ValueError(f"Could not fetch README from {repo_url}")


# ── Shared prompts for knowledge component ───────────────────────────────────

_KNOWLEDGE_DISTRACTORS_SYSTEM = """\
You are building a multiple-choice quiz. Given a Python snippet and its correct output,
generate three plausible wrong answers — each representing a specific misconception.

Respond using ONLY these tags:

<distractor_b>wrong answer text</distractor_b>
<misconception_b>one-sentence wrong mental model</misconception_b>
<distractor_c>wrong answer text</distractor_c>
<misconception_c>one-sentence wrong mental model</misconception_c>
<distractor_d>wrong answer text</distractor_d>
<misconception_d>one-sentence wrong mental model</misconception_d>"""

_KNOWLEDGE_DISTRACTORS_USER = """\
Rule: {rule}
Snippet:
{snippet}
Correct output: {correct_output}

Generate three wrong answers. Requirements:
- Each must be distinct from the correct output and from each other
- Each represents a plausible but wrong mental model about this API
- Format as printed output strings"""


class KnowledgeMCGenerator:
    """Generate direct behavioral-prediction MC questions for any Python library.

    Uses the same Player 1 flow as AdversarialMCGenerator (rule + confirming snippet +
    execution-verified output) but skips Player 2 — the question is simply
    "what does this code print?" rather than a confounder.

    This is the generic replacement for the pandas-specific PANDAS_INJECTIONS list.
    Any repo whose families are extracted by RepoAnalyzer works here.

    Usage:
        families = RepoAnalyzer(api_key="...").extract_families(readme, library_name="requests")
        gen = KnowledgeMCGenerator(api_key="...", seed=42)
        candidates = gen.generate(families=families, n_per_family=3)
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-6",
        max_retries: int = 3,
        verbose: bool = True,
        seed: int | None = None,
    ):
        self.client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self.model = model
        self.max_retries = max_retries
        self.verbose = verbose
        self.seed = seed

    def _chat(self, system: str, user: str) -> str:
        for attempt in range(self.max_retries):
            try:
                msg = self.client.messages.create(
                    model=self.model,
                    max_tokens=1024,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                return msg.content[0].text.strip()
            except Exception as e:
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError("unreachable")

    def _propose(self, family: dict, seed_rule: str) -> dict | None:
        """Player 1 only: get a rule + snippet + verified output."""
        install_line = family.get("install") or "pip install pandas numpy"
        raw = self._chat(
            _PLAYER1_SYSTEM,
            _PLAYER1_USER.format(
                family_name=family["name"],
                family_description=family["description"],
                seed_rule=seed_rule,
                install_line=install_line,
            ),
        )
        rule = _tag(raw, "rule")
        snippet = _tag(raw, "snippet")
        if not rule or not snippet:
            if self.verbose:
                print(f"  [know P1] missing tags: {raw[:80]}")
            return None
        ok, actual = _run_snippet(snippet)
        if not ok:
            if self.verbose:
                print(f"  [know P1] snippet error: {actual}")
            return None
        return {"rule": rule, "snippet": snippet, "correct_output": actual}

    def _distractors(self, proposal: dict) -> tuple[str, str, str] | None:
        raw = self._chat(
            _KNOWLEDGE_DISTRACTORS_SYSTEM,
            _KNOWLEDGE_DISTRACTORS_USER.format(
                rule=proposal["rule"],
                snippet=proposal["snippet"],
                correct_output=proposal["correct_output"],
            ),
        )
        b = _tag(raw, "distractor_b") or "Raises TypeError"
        c = _tag(raw, "distractor_c") or "Raises ValueError"
        d = _tag(raw, "distractor_d") or "None"
        return b, c, d

    def _build_candidate(self, proposal: dict, family: dict) -> MCTaskCandidate:
        import random
        task_id = _task_id_from_rule(proposal["rule"], "know_" + family["name"])

        raw_choices = [
            {"text": proposal["correct_output"], "type": "correct"},
            {"text": proposal.get("distractor_b", "Raises TypeError"), "type": "plausible_misconception"},
            {"text": proposal.get("distractor_c", "Raises ValueError"), "type": "plausible_misconception"},
            {"text": proposal.get("distractor_d", "None"),              "type": "plausible_misconception"},
        ]
        rng_seed = hash(task_id) ^ (self.seed if self.seed is not None else 0)
        rng = random.Random(rng_seed)
        rng.shuffle(raw_choices)
        labeled = [{"id": chr(65 + i), "text": c["text"], "type": c["type"]} for i, c in enumerate(raw_choices)]
        correct_id = next(lc["id"] for lc, orig in zip(labeled, raw_choices) if orig["type"] == "correct")

        return MCTaskCandidate(
            task_id=task_id,
            question_type="knowledge_mc",
            family=family["name"],
            difficulty=1,
            description=f"Knowledge: {proposal['rule'][:80]}",
            is_hard_negative=False,
            curriculum_note=f"Direct behavioral prediction: {proposal['rule']}",
            source_excerpt=f"# {proposal['rule']}\n",
            proposed_change="(No change — this is a direct behavioral prediction question)",
            snippet=proposal["snippet"],
            question_stem="What does the following code print?",
            choices=labeled,
            correct_id=correct_id,
            explanation=f"Output is {proposal['correct_output']!r}. Rule: {proposal['rule']}",
            metadata={
                "rule": proposal["rule"],
                "correct_output": proposal["correct_output"],
                "generation_recipe": "knowledge_mc_player1_only",
                "library_name": family.get("library_name", "the library"),
            },
        )

    def generate(
        self,
        families: list[dict] | None = None,
        n_per_family: int = 3,
    ) -> list[MCTaskCandidate]:
        families = families or FAMILIES
        candidates: list[MCTaskCandidate] = []
        seen_ids: set[str] = set()

        for family in families:
            produced = 0
            for seed_rule in family["seed_rules"]:
                if produced >= n_per_family:
                    break
                proposal = self._propose(family, seed_rule)
                if proposal is None:
                    continue
                distractors = self._distractors(proposal)
                if distractors is None:
                    continue
                proposal["distractor_b"], proposal["distractor_c"], proposal["distractor_d"] = distractors

                cand = self._build_candidate(proposal, family)
                if cand.task_id in seen_ids:
                    continue
                seen_ids.add(cand.task_id)
                candidates.append(cand)
                produced += 1
                if self.verbose:
                    print(f"  [know] ✓ {cand.task_id}")

        return candidates


def _tag(text: str, tag: str) -> str | None:
    """Module-level helper: extract first <tag>...</tag> from text."""
    open_tag, close_tag = f"<{tag}>", f"</{tag}>"
    start = text.find(open_tag)
    end = text.find(close_tag)
    if start == -1 or end == -1:
        return None
    return text[start + len(open_tag):end].strip()


# ── Generator ─────────────────────────────────────────────────────────────────

@dataclass
class _RoundResult:
    """Intermediate result for one adversarial round."""
    rule: str
    confirming_snippet: str
    confirming_output: str
    confounder_snippet: str
    why_wrong: str
    rule_predicts: str
    actual_output: str
    distractor_c: str
    distractor_d: str
    misconception_c: str
    misconception_d: str
    family: str
    seed_rule: str


class AdversarialMCGenerator:
    """Run the two-player adversarial game to produce MCTaskCandidate questions."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-6",
        max_retries: int = 3,
        verbose: bool = True,
        seed: int | None = None,
    ):
        self.client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self.model = model
        self.max_retries = max_retries
        self.verbose = verbose
        self.seed = seed

    def _chat(self, system: str, user: str) -> str:
        for attempt in range(self.max_retries):
            try:
                msg = self.client.messages.create(
                    model=self.model,
                    max_tokens=1024,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                return msg.content[0].text.strip()
            except Exception as e:
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError("unreachable")

    @staticmethod
    def _tag(text: str, tag: str) -> str | None:
        return _tag(text, tag)

    def _player1_propose(self, family: dict, seed_rule: str) -> dict | None:
        """Player 1: propose a belief + confirming snippet."""
        install_line = family.get("install") or "pip install pandas numpy"
        raw = self._chat(
            _PLAYER1_SYSTEM,
            _PLAYER1_USER.format(
                family_name=family["name"],
                family_description=family["description"],
                seed_rule=seed_rule,
                install_line=install_line,
            ),
        )
        rule = self._tag(raw, "rule")
        snippet = self._tag(raw, "snippet")
        if not rule or not snippet:
            if self.verbose:
                print(f"  [P1] missing tags in response: {raw[:120]}")
            return None

        ok, actual = _run_snippet(snippet)
        if not ok:
            if self.verbose:
                print(f"  [P1] snippet error: {actual}")
            return None
        return {"rule": rule, "confirming_snippet": snippet, "confirming_output": actual}

    def _player2_confound(self, proposal: dict, family: dict) -> dict | None:
        """Player 2: find where the rule breaks."""
        raw = self._chat(
            _PLAYER2_SYSTEM,
            _PLAYER2_USER.format(
                rule=proposal["rule"],
                confirming_snippet=proposal["confirming_snippet"],
                confirming_output=proposal["confirming_output"],
            ),
        )
        snippet = self._tag(raw, "snippet")
        why_wrong = self._tag(raw, "why_wrong")
        rule_predicts = self._tag(raw, "rule_predicts")

        if not snippet or not why_wrong or not rule_predicts:
            if self.verbose:
                print(f"  [P2] missing tags in response: {raw[:120]}")
            return None

        ok, actual = _run_snippet(snippet)
        if not ok:
            if self.verbose:
                print(f"  [P2] confounder error: {actual}")
            return None

        # Reject if actual == rule_predicts (exact or contained — model would be right)
        if actual.strip() == rule_predicts.strip() or actual.strip() in rule_predicts:
            if self.verbose:
                print(f"  [P2] not a confounder — actual matches rule_predicts: {actual!r}")
            return None

        if actual.strip() == proposal["confirming_output"].strip():
            if self.verbose:
                print(f"  [P2] trivial confounder — same output as confirming case")
            return None

        return {
            "confounder_snippet": snippet,
            "why_model_gets_it_wrong": why_wrong,
            "rule_predicts": rule_predicts,
            "actual_output": actual,
        }

    def _generate_distractors(
        self, proposal: dict, confounder: dict
    ) -> tuple[str, str, str, str] | None:
        """Generate 2 additional wrong answers + misconceptions."""
        raw = self._chat(
            _DISTRACTORS_SYSTEM,
            _DISTRACTORS_USER.format(
                rule=proposal["rule"],
                snippet=confounder["confounder_snippet"],
                correct_output=confounder["actual_output"],
                rule_predicts=confounder.get("rule_predicts", ""),
            ),
        )
        c_text = self._tag(raw, "distractor_c") or "Raises TypeError"
        d_text = self._tag(raw, "distractor_d") or "Raises ValueError"
        c_mis = self._tag(raw, "misconception_c") or ""
        d_mis = self._tag(raw, "misconception_d") or ""
        return c_text, d_text, c_mis, d_mis

    def _build_candidate(self, r: _RoundResult, library_name: str = "the library") -> MCTaskCandidate:
        """Assemble MCTaskCandidate with shuffled choices."""
        import random
        task_id = _task_id_from_rule(r.rule, r.family)

        # Build the 4 choices deterministically shuffled (seed-mixed for fresh draws)
        raw_choices = [
            {"text": r.actual_output,  "type": "correct",             "explanation": "Actual execution output — rule breaks here"},
            {"text": r.rule_predicts,  "type": "hard_negative",       "explanation": r.why_wrong},
            {"text": r.distractor_c,   "type": "plausible_misconception", "explanation": r.misconception_c},
            {"text": r.distractor_d,   "type": "plausible_misconception", "explanation": r.misconception_d},
        ]
        rng_seed = hash(task_id) ^ (self.seed if self.seed is not None else 0)
        rng = random.Random(rng_seed)
        rng.shuffle(raw_choices)

        labeled = [
            {"id": chr(65 + i), "text": c["text"], "type": c["type"]}
            for i, c in enumerate(raw_choices)
        ]
        correct_id = next(
            lc["id"]
            for lc, orig in zip(labeled, raw_choices)
            if orig["type"] == "correct"
        )

        source_excerpt = (
            f"# Rule being tested:\n"
            f"# {r.rule}\n"
            f"#\n"
            f"# Confirming case (rule holds):\n"
        )
        for line in r.confirming_snippet.splitlines():
            source_excerpt += f"# {line}\n"
        source_excerpt += f"# → prints: {r.confirming_output}\n"

        proposed_change = (
            f"Replace the confirming snippet above with the following:\n"
            f"  {r.confounder_snippet.splitlines()[1] if len(r.confounder_snippet.splitlines()) > 1 else r.confounder_snippet}\n"
            f"(full snippet shown in question below)"
        )

        return MCTaskCandidate(
            task_id=task_id,
            question_type="adversarial_confounder",
            family=r.family,
            difficulty=3,
            description=f"Confounder: {r.why_wrong[:80]}",
            is_hard_negative=False,
            curriculum_note=(
                f"Rule '{r.rule}' holds in the obvious case but breaks here. "
                f"Distractor B is the hard negative — the rule naively applied."
            ),
            source_excerpt=source_excerpt,
            proposed_change=proposed_change,
            snippet=r.confounder_snippet,
            question_stem=(
                "The rule above holds for the confirming case. "
                "What does the following snippet actually print? "
                "(It looks like the rule should apply — but does it?)"
            ),
            choices=labeled,
            correct_id=correct_id,
            explanation=(
                f"The rule '{r.rule}' does NOT hold here. {r.why_wrong}"
            ),
            metadata={
                "rule": r.rule,
                "seed_rule": r.seed_rule,
                "confirming_snippet": r.confirming_snippet,
                "confirming_output": r.confirming_output,
                "rule_predicts": r.rule_predicts,
                "actual_output": r.actual_output,
                "why_model_gets_it_wrong": r.why_wrong,
                "generation_recipe": "adversarial_two_player",
                "library_name": library_name,
            },
        )

    def _run_one_round(
        self, family: dict, seed_rule: str
    ) -> MCTaskCandidate | None:
        if self.verbose:
            print(f"\n[{family['name']}] Seed: {seed_rule[:60]}")

        # Player 1
        proposal = self._player1_propose(family, seed_rule)
        if proposal is None:
            return None
        if self.verbose:
            print(f"  [P1] Rule: {proposal['rule'][:70]}")
            print(f"  [P1] Confirming output: {proposal['confirming_output']!r}")

        # Player 2
        confounder = self._player2_confound(proposal, family)
        if confounder is None:
            return None
        if self.verbose:
            print(f"  [P2] Rule predicts: {confounder.get('rule_predicts', '?')!r}")
            print(f"  [P2] Actual output:  {confounder['actual_output']!r} ← DIFFERENT")
            print(f"  [P2] Why wrong: {confounder.get('why_model_gets_it_wrong', '')[:70]}")

        # Distractors
        distractors = self._generate_distractors(proposal, confounder)
        if distractors is None:
            return None
        c_text, d_text, c_mis, d_mis = distractors

        round_result = _RoundResult(
            rule=proposal["rule"],
            confirming_snippet=proposal["confirming_snippet"],
            confirming_output=proposal["confirming_output"],
            confounder_snippet=confounder["confounder_snippet"],
            why_wrong=confounder.get("why_model_gets_it_wrong", ""),
            rule_predicts=confounder.get("rule_predicts", ""),
            actual_output=confounder["actual_output"],
            distractor_c=c_text,
            distractor_d=d_text,
            misconception_c=c_mis,
            misconception_d=d_mis,
            family=family["name"],
            seed_rule=seed_rule,
        )
        return self._build_candidate(round_result, library_name=family.get("library_name", "the library"))

    def generate(
        self,
        families: list[dict] | None = None,
        n_per_family: int = 3,
        max_failures_per_seed: int = 2,
    ) -> list[MCTaskCandidate]:
        """Run the adversarial game and return verified MCTaskCandidate list."""
        families = families or FAMILIES
        candidates: list[MCTaskCandidate] = []
        seen_ids: set[str] = set()

        for family in families:
            produced = 0
            for seed_rule in family["seed_rules"]:
                if produced >= n_per_family:
                    break
                failures = 0
                while produced < n_per_family and failures < max_failures_per_seed:
                    try:
                        cand = self._run_one_round(family, seed_rule)
                    except Exception as e:
                        if self.verbose:
                            print(f"  [error] {e}")
                        cand = None

                    if cand is None or cand.task_id in seen_ids:
                        failures += 1
                        continue

                    seen_ids.add(cand.task_id)
                    candidates.append(cand)
                    produced += 1
                    if self.verbose:
                        print(f"  ✓ Added: {cand.task_id}")

        if self.verbose:
            print(f"\nGenerated {len(candidates)} adversarial questions.")
        return candidates
