# Scrapy Candidate Ranking

This ranking applies the rubric from `TASK_GENERATION_PROCESS.md` to the
expanded mined pool in `candidate_inventory.jsonl`.

Scored dimensions:

- `agent_weakness_relevance`
- `determinism`
- `locality`
- `anti_saturation`
- `implementation_cost`
- `guardrailability`
- `hardness_quality`

Weighted score:

`2 * agent_weakness_relevance + 2 * anti_saturation + 2 * hardness_quality + locality + determinism`

Here `agent_weakness_relevance` is not a freehand intuition score. It is
derived from the hard-direction tags in `candidate_inventory.jsonl`, such as:

- `cross_file_causality`
- `implicit_invariants`
- `environment_and_context`
- `async_or_lifecycle_ordering`
- `behavioral_parity`
- `state_aliasing`

This keeps the methodology systematic: we first tag the candidate with the
failure directions that are hard for current agents, and only then derive the
aggregate relevance score.

## Top Tier

These are the best immediate task sources.

| Rank | Candidate | Score | Why it stands out |
| --- | --- | --- | --- |
| 1 | `#7340` / `#7260` `genspider --edit` project-context behavior | 34 | Very strong subprocess and environment/context task with a crisp contract and strong guardrails. |
| 1 | `#7029` wait for item pipelines from `start()` | 34 | Excellent async lifecycle task with cross-file causality and deterministic validation. |
| 3 | `#7092` pipeline `from_crawler` error surfacing | 32 | Strong startup/component-loading task with clear user-visible failure semantics. |
| 4 | `#7404` async HTTP cache storages | 31 | Large recent PR with multiple narrow async/cache slices and strong anti-saturation value. |
| 4 | `#7069` downloader middleware `download_async()` migration | 31 | High-value async API migration family with non-local compatibility constraints. |
| 6 | `#7409` shell event loop handling | 30 | Rich lifecycle reasoning task source if sliced carefully to avoid investigation sprawl. |
| 6 | `#7175` AutoThrottle compatibility work | 30 | Strong compatibility-preserving policy source with good guardrail potential. |
| 6 | `#7159` bounded `_parallel_asyncio()` queue behavior | 30 | Likely strong bounded-concurrency task if validator avoids flakiness. |

## Strong Second Tier

These are good sources, but need more slicing or are slightly less compelling
than the top tier.

| Candidate | Score | Notes |
| --- | --- | --- |
| `#7344` / `#7030` `pyproject.toml` project discovery | 29 | Very benchmarkable config-precedence family; slightly easier than the best async/context tasks. |
| `#7164` async API for download handlers | 29 | Strong compatibility family with several plausible narrow slices. |
| `#7151` deprecate Deferreds from spider callbacks/errbacks | 29 | Promising agent-hard compatibility source. |
| `#7292` response request header exception | 28 | Good narrow bug once exact triggering behavior is captured. |
| `#7149` pipeline Deferred warning | 28 | Likely benchmarkable as a warning/compatibility slice with guardrails. |
| `#7407` `ensure_awaitable()` follow-on work | 27 | Valuable source, but still broad and needs careful narrowing. |

## Watch List

These should stay in the pool, but they are not the best next tasks.

| Candidate | Score | Notes |
| --- | --- | --- |
| `#7286` Request object update | 25 | Good family source, but not yet specific enough. |
| `#7036` Request `__slots__` / lazy evaluation | 24 | Useful mutation-guided and invariant source, but older. |
| `#7252` `httpx` production-ready | 23 | Broad reservoir, not a task as-is. |
| `#7077` `LOG_ENABLED=False` vs stdlib logging | 23 | Interesting settings interaction but lower skill value. |
| `#7001` `getwithbase()` precedence behavior | 23 | Clean but relatively easy. |
| `#7161` `send_catch_log_deferred()` deprecation | 22 | May end up too warning-oriented. |
| `#7247` HttpCache time-sensitive flake | 20 | Only useful if reframed as deterministic expiration logic. |

## Defer

| Candidate | Score | Why deferred |
| --- | --- | --- |
| `#7044` replace `MailSender` | 15 | Too architectural and open-ended for the first benchmark wave. |

## Recommended Next 10 To Slice

If we want the best task-generation yield from the current pool, the next 10 to
convert into concrete task specs should be:

1. `#7029`
2. `#7340`
3. `#7092`
4. `#7404`
5. `#7069`
6. `#7409`
7. `#7175`
8. `#7344`
9. `#7151`
10. `#7292`

This set gives good coverage across:

- async lifecycle and ordering
- CLI and project context
- configuration precedence
- compatibility-preserving API migrations
- request/state invariants
- policy logic

## Notes

- Issue/PR pairs like `#7260` + `#7340` and `#7030` + `#7344` are especially
  valuable because they provide both user-facing motivation and likely fix
  surface.
- Large PRs such as `#7404`, `#7069`, and `#7164` are usually best treated as
  task reservoirs that yield multiple narrow slices rather than as one task each.
- Some lower-ranked candidates should still stay in the pool because they are
  good sources for mutation-guided generation even if they are not top manual
  picks.
- The benchmark is explicitly optimized for directions that are hard for
  current agents, not generic bug difficulty. The ranking should be read through
  that lens.
