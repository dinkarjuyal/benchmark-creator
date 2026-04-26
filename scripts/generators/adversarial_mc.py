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
from scripts.generators.runtime import ExecutionRuntime, PythonRuntime

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
You are designing a behavioral quiz about a software library. \
Propose a TRUE rule about the library's behavior that most practitioners have learned.

Respond using ONLY these tags — no other text:

<rule>One-sentence true rule about the library</rule>
<snippet>
Short runnable code snippet demonstrating the rule \
(include necessary imports, print exactly one line)
</snippet>"""

_PLAYER1_USER = """\
Family: {family_name} — {family_description}
Seed rule to build on: "{seed_rule}"
Library install: {install_line}
Language: {language}

Requirements:
- Rule must be specific enough to make a clear prediction
- Snippet must be runnable {language} code, after: {install_line}
- Snippet must print exactly one line
- Keep snippet under 6 lines of code"""

_PLAYER2_SYSTEM = """\
You are an adversary designing trick questions about a software library. \
Given a rule that a model believes, find a case where the rule BREAKS non-obviously \
— where the model would confidently apply the rule and get the wrong answer.

Respond using ONLY these tags — no other text:

<snippet>
Short runnable code snippet that VIOLATES the rule non-obviously \
(include necessary imports, print one line)
</snippet>
<why_wrong>One sentence: which part of the rule the model incorrectly applies here</why_wrong>
<rule_predicts>The EXACT output string the model would expect — no explanation</rule_predicts>"""

_PLAYER2_USER = """\
Rule: "{rule}"
Language: {language}

Confirming case (rule HOLDS here):
{confirming_snippet}
Actual output: {confirming_output}

Find a variation where a model would expect the rule to apply, but the output differs.

Requirements:
- Use the same library API as the confirming case
- Must look superficially similar to the confirming case
- Must NOT be a trivially obvious edge case
- Snippet must be runnable {language} code and print exactly one line"""

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
You are a Python library behavioral archaeologist. Your job is to extract deep,
causally-grounded behavioral traps that real users encounter — not surface facts,
but the WHY behind surprising behavior.

You may receive multiple evidence sources: README excerpts, real GitHub bug reports,
and fix commits. Treat each bug report and fix commit as a confirmed real-world
confounder — a place where a practitioner's mental model failed.

Apply the 5 Whys framework before writing each seed_rule:
  Why 1: What is the observable symptom?
  Why 2: What immediate mechanism causes it?
  Why 3: Why was that mechanism designed that way?
  Why 4: What deeper constraint forced that design?
  Why 5: What is the root-cause trap for a practitioner?

BAD seed_rule (surface fact):
  "NaN != NaN is True"
GOOD seed_rule (causal mechanism):
  "NaN != NaN returns True because pandas float NaN follows IEEE 754 float semantics —
   but pd.NA != pd.NA returns pd.NA (not True) because pd.NA uses Python object-identity
   semantics, not float arithmetic. The same-looking inequality silently changes behavior
   depending on which NA type the column contains."

Respond using ONLY these tags, repeated once per family (3–6 families total).
Show your 5-Whys reasoning in a <reasoning> block before each <family>:

<reasoning>Your 5-Whys analysis for this family (scratchpad — not shown to users)</reasoning>
<family>
<name>short_snake_case_name</name>
<description>one-line description of the behavioral area</description>
<seed_rule>A causally-grounded rule encoding the WHY, not just the WHAT</seed_rule>
<seed_rule>Another causally-grounded rule</seed_rule>
<seed_rule>A third rule, ideally grounded in a bug report or fix commit</seed_rule>
<install>pip install package_name</install>
</family>"""

_REPO_ANALYZER_USER = """\
Library: {library_name}

{readme_section}

{issues_section}

{commits_section}

Extract 3–6 behavioral families where a practitioner might overgeneralize a known rule.
Focus on: default parameter values, dtype/type coercion, alignment semantics, copy-vs-view,
NaN/null handling, ordering guarantees, or any library-specific gotcha area.

Bug reports and fix commits are confirmed real confounders — prioritize families that
appear in the issue/commit data over purely README-derived families.
Show your 5-Whys reasoning in <reasoning> blocks. seed_rules must encode causal
mechanisms ("because X due to Y"), not just observable facts."""

# ── Probe prompts (used by RepoAnalyzer.probe_and_filter) ────────────────────

_PROBE_BATCH_SYSTEM = """\
Given a list of seed rules about a Python library, generate one probe snippet per rule
that CONFIRMS the rule holds for the currently installed version.

Respond ONLY with numbered probe blocks, one per rule:

<probe_1>
<snippet>self-contained executable Python — include imports, print exactly one line</snippet>
<expected>exact string that would be printed if the rule holds</expected>
</probe_1>
<probe_2>...</probe_2>
(continue for all N rules)"""

_PROBE_BATCH_USER = """\
Library: {install}
Rules to probe ({n} total):
{numbered_rules}

For each rule write a minimal probe snippet that CONFIRMS it is true.
Requirements:
- Each snippet must be self-contained (include all imports)
- Each snippet must print exactly one line
- expected must be the EXACT printed string if the rule holds (no explanation)"""


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


class REPLSession:
    """A long-running Python process that amortizes library import cost.

    Instead of spawning a fresh `python3 -c` process per snippet (which pays
    the full import cost each time), REPLSession keeps one process alive and
    sends snippets over stdin/stdout. For heavy libraries (pandas, sklearn)
    this eliminates 0.5–1s of startup overhead per snippet.

    Usage:
        with REPLSession("pip install pandas numpy") as repl:
            ok, out = repl.run("import pandas as pd; s = pd.Series([1,2]); print(s.sum())")
            ok, out = repl.run("import pandas as pd; print(pd.Series([]).dtype)")

    Note: Uses select.select for non-blocking reads (Unix only). Windows would
    need a threading fallback — add if cross-platform support is required.
    """

    _SENTINEL = "__REPL_DONE__"
    _END_MARKER = "__END__"

    # Bootstrap code runs in the subprocess — reads snippets from stdin, executes
    # each in a shared namespace, writes result + sentinel back to stdout.
    # Shared namespace (g) means pre-warmed imports persist across all snippets.
    _BOOTSTRAP = '''\
import sys, io, contextlib

SENTINEL = "__REPL_DONE__"
END = "__END__"
g = {}  # shared namespace — imports and variables persist across snippets
while True:
    lines = []
    while True:
        line = sys.stdin.readline()
        if not line or line.rstrip() == END:
            break
        lines.append(line)
    if not lines:
        break
    code = "".join(lines)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(code, "<snippet>", "exec"), g)
        result = "OK:" + buf.getvalue().strip()
    except Exception as exc:
        result = "ERR:" + repr(exc)[:200]
    sys.stdout.write(result + SENTINEL + "\\n")
    sys.stdout.flush()
'''

    def __init__(self, install: str = "", timeout: int = 15):
        self._proc = subprocess.Popen(
            [sys.executable, "-u", "-c", self._BOOTSTRAP],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._timeout = timeout
        # Pre-warm: import the library so all subsequent snippets skip import cost
        if install:
            libs = [w for w in install.split() if not w.startswith(("-", "pip", "install"))]
            if libs:
                self._exec(f"import {', '.join(libs)}")

    def _exec(self, snippet: str) -> tuple[bool, str]:
        import select
        payload = (snippet.strip() + f"\n{self._END_MARKER}\n").encode()
        self._proc.stdin.write(payload)
        self._proc.stdin.flush()
        output = ""
        deadline = time.time() + self._timeout
        while self._SENTINEL not in output:
            if time.time() > deadline:
                return False, f"ERROR: timed out after {self._timeout}s"
            rlist, _, _ = select.select([self._proc.stdout], [], [], 0.1)
            if rlist:
                output += self._proc.stdout.readline().decode()
        result = output.replace(self._SENTINEL, "").strip()
        if result.startswith("OK:"):
            return True, result[3:]
        if result.startswith("ERR:"):
            return False, result[4:]
        return False, result

    def run(self, snippet: str) -> tuple[bool, str]:
        try:
            return self._exec(snippet)
        except Exception as e:
            return False, str(e)

    def close(self) -> None:
        try:
            self._proc.stdin.close()
            self._proc.wait(timeout=2)
        except Exception:
            self._proc.kill()

    def __enter__(self) -> "REPLSession":
        return self

    def __exit__(self, *args) -> None:
        self.close()


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

    # ── Data source fetchers ──────────────────────────────────────────────────

    @staticmethod
    def _parse_owner_name(repo_url: str) -> tuple[str, str]:
        """Extract (owner, name) from a GitHub URL."""
        parts = repo_url.rstrip("/").split("github.com/")[-1].split("/")
        if len(parts) < 2 or not parts[0] or not parts[1]:
            raise ValueError(f"Cannot parse owner/name from: {repo_url}")
        return parts[0], parts[1]

    @staticmethod
    def from_github(repo_url: str) -> str:
        """Fetch README text from a GitHub repo URL."""
        import urllib.request
        repo_url = repo_url.rstrip("/")
        if "github.com" not in repo_url:
            raise ValueError(f"Not a GitHub URL: {repo_url}")
        owner, name = RepoAnalyzer._parse_owner_name(repo_url)
        for branch in ("main", "master"):
            for fname in ("README.md", "README.rst", "README.txt", "README"):
                raw_url = f"https://raw.githubusercontent.com/{owner}/{name}/{branch}/{fname}"
                try:
                    with urllib.request.urlopen(raw_url, timeout=10) as r:
                        return r.read().decode("utf-8", errors="replace")
                except Exception:
                    continue
        raise ValueError(f"Could not fetch README from {repo_url}")

    @staticmethod
    def from_github_issues(
        repo_url: str,
        max_issues: int = 20,
        token: str | None = None,
    ) -> str:
        """Fetch closed bug-labeled issues + keyword-matched issues.

        Returns a formatted string for LLM context, or "" on any failure.
        Requires only public repo access (60 unauthenticated req/hour; pass token
        for 5000/hour).
        """
        import urllib.request, urllib.error, json as _json
        if "github.com" not in repo_url:
            return ""
        try:
            owner, name = RepoAnalyzer._parse_owner_name(repo_url)

            def _fetch(url: str) -> list[dict]:
                req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
                if token:
                    req.add_header("Authorization", f"Bearer {token}")
                with urllib.request.urlopen(req, timeout=10) as r:
                    return _json.loads(r.read().decode())

            base = f"https://api.github.com/repos/{owner}/{name}/issues"

            # Fetch 1: bug-labeled closed issues
            labeled = _fetch(f"{base}?state=closed&labels=bug&per_page={max_issues}")

            # Fetch 2: all closed issues, client-side keyword filter
            keywords = {"unexpected", "surprising", "behavior", "gotcha", "wrong", "incorrect"}
            all_closed = _fetch(f"{base}?state=closed&per_page=50")
            keyword_matched = [
                i for i in all_closed
                if any(kw in i.get("title", "").lower() for kw in keywords)
            ]

            # Deduplicate by issue number
            seen: set[int] = set()
            entries: list[str] = []
            for issue in labeled + keyword_matched:
                num = issue.get("number", 0)
                if num in seen:
                    continue
                seen.add(num)
                title = issue.get("title", "")
                body = (issue.get("body") or "")[:300].replace("\r\n", " ").replace("\n", " ")
                entries.append(f"#{num}: {title}\n  {body}")
                if len(entries) >= max_issues:
                    break

            if not entries:
                return ""
            return "=== GITHUB ISSUES (closed bugs / unexpected behavior reports) ===\n" + "\n\n".join(entries)
        except Exception:
            return ""

    @staticmethod
    def from_github_commits(
        repo_url: str,
        max_commits: int = 30,
        token: str | None = None,
    ) -> str:
        """Fetch recent commits, filter for fix/bug messages.

        Returns a formatted string or "" on failure.
        """
        import urllib.request, json as _json
        if "github.com" not in repo_url:
            return ""
        try:
            owner, name = RepoAnalyzer._parse_owner_name(repo_url)
            url = f"https://api.github.com/repos/{owner}/{name}/commits?per_page={max_commits}"
            req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
            if token:
                req.add_header("Authorization", f"Bearer {token}")
            with urllib.request.urlopen(req, timeout=10) as r:
                commits = _json.loads(r.read().decode())

            fix_prefixes = ("fix:", "bug:", "fix ", "fixes ", "fixed ")
            entries: list[str] = []
            for c in commits:
                msg = c.get("commit", {}).get("message", "")
                subject = msg.split("\n")[0]
                if not subject.lower().startswith(fix_prefixes):
                    continue
                sha = c.get("sha", "")[:7]
                body_lines = [l.strip() for l in msg.split("\n")[1:] if l.strip()]
                body = " ".join(body_lines)[:200]
                entry = f"[{sha}] {subject}"
                if body:
                    entry += f"\n  {body}"
                entries.append(entry)

            if not entries:
                return ""
            return "=== RECENT FIX COMMITS ===\n" + "\n\n".join(entries)
        except Exception:
            return ""

    # ── Family extraction ─────────────────────────────────────────────────────

    def extract_families(
        self,
        sources: "dict[str, str] | str",
        library_name: str = "the library",
    ) -> list[dict]:
        """Return families list compatible with AdversarialMCGenerator.

        sources: dict with keys "readme", "issues", "commits" (all optional).
                 For backward compatibility, a bare str is treated as {"readme": s}.
        """
        # Backward compat: existing callers pass readme_text directly
        if isinstance(sources, str):
            sources = {"readme": sources}

        readme_section = (
            f"README / documentation excerpt (first 3000 chars):\n{sources['readme'][:3000]}"
            if sources.get("readme") else ""
        )
        issues_section = (
            f"GITHUB ISSUES (real user bug reports — each is a confirmed confounder):\n{sources['issues']}"
            if sources.get("issues") else ""
        )
        commits_section = (
            f"RECENT FIX COMMITS (confirmed bugs that were fixed):\n{sources['commits']}"
            if sources.get("commits") else ""
        )

        user_content = _REPO_ANALYZER_USER.format(
            library_name=library_name,
            readme_section=readme_section,
            issues_section=issues_section,
            commits_section=commits_section,
        ).strip()

        msg = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=_REPO_ANALYZER_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
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
                    "install": install,
                })
        return families

    # ── Probe verification ────────────────────────────────────────────────────

    def _chat(self, system: str, user: str) -> str:
        for attempt in range(3):
            try:
                msg = self.client.messages.create(
                    model=self.model,
                    max_tokens=1024,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                return msg.content[0].text.strip()
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError("unreachable")

    def probe_and_filter(
        self,
        families: list[dict],
        timeout: int = 15,
        verbose: bool = True,
    ) -> list[dict]:
        """Verify seed_rules by running probe snippets. Drop rules that fail or contradict.
        Drop families with fewer than 2 surviving rules.

        Cost: 1 LLM call + 1 REPLSession per family (not per rule).
        This is the correct granularity: amortize import cost within a family,
        batch the LLM call across all rules in the family.
        """
        kept_families = []
        for family in families:
            rules = family["seed_rules"]
            install = family.get("install", "")
            n = len(rules)

            # One LLM call for all rules in this family
            numbered = "\n".join(f"{i+1}. {r}" for i, r in enumerate(rules))
            try:
                raw = self._chat(
                    _PROBE_BATCH_SYSTEM,
                    _PROBE_BATCH_USER.format(install=install, n=n, numbered_rules=numbered),
                )
            except Exception as e:
                if verbose:
                    print(f"  [probe] LLM call failed for family '{family['name']}': {e}")
                kept_families.append(family)  # keep as-is on LLM failure
                continue

            # Parse probe_i blocks
            probes: list[tuple[str, str] | None] = []
            for i in range(1, n + 1):
                block = _tag(raw, f"probe_{i}")
                if block:
                    snip = _tag(block, "snippet")
                    exp = _tag(block, "expected")
                    probes.append((snip, exp) if snip and exp else None)
                else:
                    probes.append(None)

            # One REPLSession for the whole family — imports once, runs all probes
            surviving_rules: list[str] = []
            with REPLSession(install=install, timeout=timeout) as repl:
                for rule, probe in zip(rules, probes):
                    if probe is None:
                        if verbose:
                            print(f"  [probe] no snippet generated for: {rule[:55]}")
                        continue
                    snip, expected = probe
                    ok, actual = repl.run(snip)
                    if not ok:
                        if verbose:
                            print(f"  [probe] ✗ execution error for: {rule[:55]}")
                        continue
                    if actual.strip() != expected.strip():
                        if verbose:
                            print(f"  [probe] ✗ expected {expected!r}, got {actual!r} — dropping: {rule[:45]}")
                        continue
                    if verbose:
                        print(f"  [probe] ✓ {rule[:65]}")
                    surviving_rules.append(rule)

            if len(surviving_rules) >= 2:
                kept_families.append({**family, "seed_rules": surviving_rules})
            else:
                if verbose:
                    print(f"  [probe] dropping family '{family['name']}' — {len(surviving_rules)}/2 rules survived")

        return kept_families


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
        runtime: ExecutionRuntime | None = None,
    ):
        self.client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self.model = model
        self.max_retries = max_retries
        self.verbose = verbose
        self.seed = seed
        self._runtime = runtime or PythonRuntime()

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
        ok, actual = self._runtime.run(snippet)
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
        runtime: ExecutionRuntime | None = None,
    ):
        self.client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self.model = model
        self.max_retries = max_retries
        self.verbose = verbose
        self.seed = seed
        self._runtime = runtime or PythonRuntime()

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
        install_line = family.get("install") or self._runtime.setup_hint()
        language = family.get("language") or self._runtime.language
        raw = self._chat(
            _PLAYER1_SYSTEM,
            _PLAYER1_USER.format(
                family_name=family["name"],
                family_description=family["description"],
                seed_rule=seed_rule,
                install_line=install_line,
                language=language,
            ),
        )
        rule = self._tag(raw, "rule")
        snippet = self._tag(raw, "snippet")
        if not rule or not snippet:
            if self.verbose:
                print(f"  [P1] missing tags in response: {raw[:120]}")
            return None

        ok, actual = self._runtime.run(snippet)
        if not ok:
            if self.verbose:
                print(f"  [P1] snippet error: {actual}")
            return None
        return {"rule": rule, "confirming_snippet": snippet, "confirming_output": actual}

    def _player2_confound(self, proposal: dict, family: dict) -> dict | None:
        """Player 2: find where the rule breaks."""
        language = family.get("language") or self._runtime.language
        raw = self._chat(
            _PLAYER2_SYSTEM,
            _PLAYER2_USER.format(
                rule=proposal["rule"],
                confirming_snippet=proposal["confirming_snippet"],
                confirming_output=proposal["confirming_output"],
                language=language,
            ),
        )
        snippet = self._tag(raw, "snippet")
        why_wrong = self._tag(raw, "why_wrong")
        rule_predicts = self._tag(raw, "rule_predicts")

        if not snippet or not why_wrong or not rule_predicts:
            if self.verbose:
                print(f"  [P2] missing tags in response: {raw[:120]}")
            return None

        ok, actual = self._runtime.run(snippet)
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
                "language": self._runtime.language,
                "generation_date": __import__("datetime").datetime.utcnow().isoformat(),
            },
        )

    def _run_one_round(
        self, family: dict, seed_rule: str
    ) -> "_RoundResult | None":
        """Run one adversarial round. Returns the intermediate _RoundResult so
        callers (e.g. AdversarialSGSStrategy) can inspect/score it before
        building the final MCTaskCandidate.
        """
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

        return _RoundResult(
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
                        result = self._run_one_round(family, seed_rule)
                    except Exception as e:
                        if self.verbose:
                            print(f"  [error] {e}")
                        result = None

                    if result is None:
                        failures += 1
                        continue
                    cand = self._build_candidate(
                        result,
                        library_name=family.get("library_name", "the library"),
                    )
                    if cand.task_id in seen_ids:
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


# ── Guide scorer (SGS-inspired) ───────────────────────────────────────────────

_GUIDE_SYSTEM = """\
You are a Guide in an adversarial benchmark generation game.
A Proposer wrote a rule about a Python library. An Adversary wrote a confounder
snippet supposed to reveal a non-obvious edge case where that rule breaks.

Score this confounder on three axes (each 1–5):
  relevance:   Does it exploit the SPECIFIC mechanism described in the rule,
               not just any different output?
  elegance:    Is the variation minimal and surface-similar to the confirming
               case (not a completely different API)?
  non_trivial: Is it NOT a trivially broken snippet — no import errors, no
               syntax errors, no completely unrelated API call?

Respond ONLY with these tags:
<relevance>N</relevance>
<elegance>N</elegance>
<non_trivial>N</non_trivial>
<reject_reason>One sentence if any score < 3, else leave empty</reject_reason>"""

_GUIDE_USER = """\
Rule: {rule}

Confirming snippet (rule holds here):
{confirming}

Confounder snippet (rule allegedly breaks here):
{confounder}

Why wrong: {why_wrong}"""


class GuideScorer:
    """SGS-inspired Guide that scores confounder quality.

    Rejects degenerate confounders (import errors, unrelated APIs, trivially
    different outputs) that technically pass the execution verifier but don't
    reveal practitioner misconceptions.

    Cost: 1 LLM call per confounder (uses haiku for speed/cost).
    """

    MIN_SCORE = 3  # reject if any axis is strictly below this

    def __init__(self, client: anthropic.Anthropic, verbose: bool = False):
        self._client = client
        self.verbose = verbose

    def score(
        self,
        rule: str,
        confirming: str,
        confounder: str,
        why_wrong: str,
    ) -> tuple[bool, str]:
        """Evaluate confounder quality.

        Returns:
            (accept, reject_reason)
            accept=True  → confounder passes quality gate
            accept=False → reject_reason describes which axis failed
        """
        raw = self._client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=_GUIDE_SYSTEM,
            messages=[{
                "role": "user",
                "content": _GUIDE_USER.format(
                    rule=rule,
                    confirming=confirming,
                    confounder=confounder,
                    why_wrong=why_wrong,
                ),
            }],
        ).content[0].text

        def _int_tag(t: str) -> int:
            v = _tag(raw, t)
            try:
                return int((v or "0").strip())
            except ValueError:
                return 0

        scores = {
            "relevance":   _int_tag("relevance"),
            "elegance":    _int_tag("elegance"),
            "non_trivial": _int_tag("non_trivial"),
        }
        reason = _tag(raw, "reject_reason") or ""
        accept = all(v >= self.MIN_SCORE for v in scores.values())
        if self.verbose:
            status = "✓ guide" if accept else f"✗ guide ({reason.strip()[:60]})"
            print(f"    [{status}] scores={scores}")
        return accept, reason.strip()


# ── Strategy wrappers + registration ─────────────────────────────────────────

from scripts.generators.strategy_registry import (  # noqa: E402
    GenerationStrategy,
    register_strategy,
)


@register_strategy("adversarial")
class AdversarialStrategy(GenerationStrategy):
    """Classic two-player adversarial game (no Guide filter)."""

    def __init__(
        self,
        api_key: str | None = None,
        verbose: bool = False,
        seed: int | None = None,
        runtime: ExecutionRuntime | None = None,
    ):
        self._gen = AdversarialMCGenerator(
            api_key=api_key, verbose=verbose, seed=seed, runtime=runtime
        )

    def generate(
        self, families: list[dict], n_per_family: int = 3
    ) -> list[MCTaskCandidate]:
        return self._gen.generate(families=families, n_per_family=n_per_family)


@register_strategy("knowledge")
class KnowledgeStrategy(GenerationStrategy):
    """Direct behavioral-prediction questions (calibration baseline)."""

    def __init__(
        self,
        api_key: str | None = None,
        verbose: bool = False,
        seed: int | None = None,
        runtime: ExecutionRuntime | None = None,
    ):
        self._gen = KnowledgeMCGenerator(
            api_key=api_key, verbose=verbose, seed=seed, runtime=runtime
        )

    def generate(
        self, families: list[dict], n_per_family: int = 3
    ) -> list[MCTaskCandidate]:
        return self._gen.generate(families=families, n_per_family=n_per_family)


@register_strategy("sgs")
class AdversarialSGSStrategy(GenerationStrategy):
    """SGS-guided adversarial game: Guide scorer filters degenerate confounders.

    Wraps the classic adversarial game and adds a Guide LLM call (haiku) per
    confounder candidate. Confounders that score below the quality threshold on
    relevance, elegance, or non-triviality are rejected and P2 is asked to retry
    (up to max_guide_retries times per P1 proposal).

    Cost vs classic: ~1 additional haiku call per confounder attempt.
    Typical overhead: 20–40% more LLM calls, significantly fewer degenerate
    confounders (import errors, unrelated API calls).
    """

    def __init__(
        self,
        api_key: str | None = None,
        verbose: bool = False,
        seed: int | None = None,
        max_guide_retries: int = 2,
        runtime: ExecutionRuntime | None = None,
    ):
        self._gen = AdversarialMCGenerator(
            api_key=api_key, verbose=verbose, seed=seed, runtime=runtime
        )
        self._guide = GuideScorer(
            client=anthropic.Anthropic(
                api_key=api_key or os.environ["ANTHROPIC_API_KEY"]
            ),
            verbose=verbose,
        )
        self._max_retries = max_guide_retries

    def generate(
        self, families: list[dict], n_per_family: int = 3
    ) -> list[MCTaskCandidate]:
        """Generate candidates, gating each confounder through the Guide scorer."""
        original_run = self._gen._run_one_round

        def _guided_run(family: dict, seed_rule: str) -> "_RoundResult | None":
            for attempt in range(self._max_retries + 1):
                result = original_run(family, seed_rule)
                if result is None:
                    # P1 or executor failed — no point retrying with Guide
                    return None
                accept, reason = self._guide.score(
                    rule=result.rule,
                    confirming=result.confirming_snippet,
                    confounder=result.confounder_snippet,
                    why_wrong=result.why_wrong,
                )
                if accept:
                    return result
                if self._gen.verbose:
                    print(
                        f"  [sgs] attempt {attempt + 1}/{self._max_retries + 1} "
                        f"rejected: {reason[:70]}"
                    )
            return None  # all retries exhausted

        self._gen._run_one_round = _guided_run
        try:
            return self._gen.generate(families=families, n_per_family=n_per_family)
        finally:
            self._gen._run_one_round = original_run  # always restore
