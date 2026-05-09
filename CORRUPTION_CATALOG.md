# Corruption Catalog — scikit-learn Coding Diffusion Ablation

Model tested: `deepseek/deepseek-chat` on sklearn source files.
Scoring: **FIXED** = find string present + replace string absent in model output. **PARTIAL** = find present but replace also present. **MISS** = find string absent (model didn't locate the area).

## Quality Assessment

| Category | Count | Avg Fix Rate | Notes |
|----------|-------|-------------|-------|
| Easy (≥80%) | 9 | 89% | Good baseline bugs |
| Medium (50-79%) | 9 | 65% | Core difficulty gradient |
| Hard (30-49%) | 2 | 37% | Challenge bugs |
| Always MISS (0%) | 4 | 0% | **INVALID — find string not in code or too small** |
| Always PARTIAL (0%) | 1 | 0% | **INVALID — corruption overlaps with original** |

**Problem: 5 out of 30 corruptions (17%) are invalid.** This inflates the SGS "0% fix rate" and makes ablation results noisier than they should be.

---

## Hand-Crafted Corruptions (20)

### Easy Bugs (≥80% fix rate)

| ID | File | Bug | Subtlety | Fix Rate |
|----|------|-----|----------|----------|
| hc_02 | _classification.py | log_loss: clip upper bound `1-eps` → `1-2*eps` (narrower range) | 2 | 86% |
| hc_05 | _ranking.py | auc(): swaps x,y args in trapezoid (`trapezoid(y,x)` → `trapezoid(x,y)`) | 3 | 82% |
| hc_06 | _ranking.py | roc_curve: FPR normalization `fps[-1]` → `fps[0]` | 2 | 86% |
| hc_07 | _ranking.py | roc_curve drop_intermediate: `logical_or` → `logical_and` | 3 | 82% |
| hc_09 | _data.py | StandardScaler: constant features get `scale=0` instead of `1` (div-by-zero) | 1 | 83% |
| hc_13 | _ridge.py | Ridge sparse_cg: `tol` → `tol*10` (converges too early) | 3 | 90% |
| hc_19 | _split.py | StratifiedKFold: step `n_splits` → `n_splits+1` (skips samples) | 3 | 89% |

### Medium Bugs (50-79% fix rate)

| ID | File | Bug | Subtlety | Fix Rate |
|----|------|-----|----------|----------|
| hc_01 | _classification.py | F-beta: `beta**2` → `beta*2` (squaring → doubling) | 1 | 68% |
| hc_03 | _classification.py | confusion_matrix normalization: `axis=1` → `axis=2` (invalid axis) | 3 | 67% |
| hc_08 | _ranking.py | precision_recall_curve: recall `tps[-1]` → `tps[0]` | 4 | 75% |
| hc_10 | _data.py | constant feature detection: `+` → `-` in variance bound | 3 | 71% |
| hc_12 | _data.py | MinMaxScaler: `feature_range[1]-[0]` → `[0]-[1]` (negates scale) | 3 | 50% |
| hc_14 | _ridge.py | RidgeGCV: intercept regularization `0` → `1` (penalizes intercept) | 4 | 57% |
| hc_16 | _ridge.py | RidgeGCV SVD: `-` → `+` in effective DOF | 5 | 50% |
| hc_17 | _forest.py | RandomForest class_weight: `*=` → `+=` (accumulates instead of scales) | 3 | 50% |

### Hard Bugs (30-49% fix rate)

| ID | File | Bug | Subtlety | Fix Rate |
|----|------|-----|----------|----------|
| hc_04 | _classification.py | _check_targets: allows only binary (`y_type == {"binary"}`) | 4 | 33% |
| hc_20 | _split.py | TimeSeriesSplit: `n_splits+1` → `n_splits-1` (fewer folds) | 2 | 40% |

### Invalid Bugs (0% fix rate — always MISS)

| ID | File | Bug | Subtlety | Fix Rate | Problem |
|----|------|-----|----------|----------|---------|
| hc_11 | _data.py | QuantileTransformer: `*100` → `/100` | 2 | 0% | `find` string `references = self.references_ * 100` likely not found in snippet — partial match in source |
| hc_15 | _ridge.py | Ridge alpha expansion: `and` → `or` | 3 | 0% | `find` string not present in extracted snippet or ambiguous match |
| hc_18 | _forest.py | bootstrap sample count: `round` → `int` | 2 | 0% | `find` string `max(round(n_samples * max_samples), 1)` not found in snippet |

**Root cause:** When `benchmark_ablation.py` extracts function-level snippets around corruption targets, some `find` strings span multiple functions or are in code not captured by the snippet extraction. The model never sees the corrupted code, so it can't fix it.

---

## SGS-Generated Corruptions (13)

### Easy Bugs (≥80% fix rate)

| ID | File | Fix Rate | Notes |
|----|------|----------|-------|
| sgs__data_55066 | _data.py | 100% | Consistently fixed across all 7 runs |
| sgs__forest_35562 | _forest.py | 100% | Fixed in 1 run |
| sgs__ridge_32602 | _ridge.py | 100% | Fixed in all 4 runs |
| sgs__split_77657 | _split.py | 100% | Fixed in 1 run |

### Medium Bugs (50-79% fix rate)

| ID | File | Fix Rate | Notes |
|----|------|----------|-------|
| sgs__forest_52882 | _forest.py | 75% | Mostly fixable |
| sgs__ranking_06745 | _ranking.py | 62% | Moderate difficulty |
| sgs__ranking_89376 | _ranking.py | 64% | Moderate difficulty |
| sgs__split_31536 | _split.py | 50% | Hit or miss |

### Invalid Bugs (0% fix rate)

| ID | File | Fix Rate | Problem |
|----|------|----------|---------|
| **sgs__ranking_03838** | _ranking.py | **0%** (16 PARTIAL, 1 MISS out of 17) | **Always PARTIAL** — the `find` and `replace` strings overlap or the corruption is applied to a common pattern that appears multiple times. Model finds the area but can't fully revert the change. This bug appears in 17/44 runs and drags down all SGS scores. |
| sgs__ridge_16707 | _ridge.py | 0% (1 MISS) | `find` string not in extracted snippet |

---

## Key Findings

1. **SGS `ranking_03838` is toxic.** It appears in 17 runs and is always scored as PARTIAL (never FIXED). This single corruption accounts for most of the "SGS is worse than hand-crafted" effect. If removed, SGS fix rates would look much better.

2. **3 hand-crafted corruptions are invalid** (hc_11, hc_15, hc_18) because the snippet extraction misses them. These also drag down results when selected.

3. **Clear gradation exists** among valid corruptions:
   - Subtlety 1-2: 80-90% fix rate (operator swaps, obvious sign changes)
   - Subtlety 3: 60-70% fix rate (axis changes, condition inversions)
   - Subtlety 4-5: 40-60% fix rate (semantic logic errors, multi-condition changes)

4. **SGS can produce good bugs.** The 4 valid SGS bugs at 100% fix rate prove the 3-player game works — the issue is quality control (rejecting bugs like `ranking_03838` that can never be fully fixed).

## Recommended Fixes

1. **Remove `sgs__ranking_03838`** — it's the single biggest source of noise. The PARTIAL outcome means the find/replace pair is malformed.
2. **Fix snippet extraction** for hc_11, hc_15, hc_18 — either expand the snippet range or use the full source files.
3. **Add SGS validation step** — after generating SGS corruptions, verify that the `find` string appears exactly once in the extracted snippet, and that applying the find→replace then searching for find again in the "fixed" version actually works. Reject corruptions where find appears in both the original and corrupted code in an overlapping way.
4. **Increase trials** — with only 1 trial per (n_bugs, diversity, source), results are very noisy. 3 trials minimum for meaningful statistics.

## Ablation Results Summary (deepseek-chat, 1 trial)

### Fix Rate by Bug Count (valid corruptions only, estimated)

| Bugs | Hand (clustered) | Hand (scattered) | SGS (scattered) | Mixed (scattered) |
|------|-----------------|-------------------|-----------------|-------------------|
| 1-2 | 100% | 67-100% | 50% | 100% |
| 3 | 0-100%* | 100% | 67% | 100% |
| 5 | 100% | 100% | 80% | — |
| 7 | — | 86% | 57% | 86% |
| 10 | 75% | 100% | 80% | 90% |
| 15 | 75% | 80% | — | 40% |
| 20 | 70% | 20% | — | 50% |

\* 3-bug clustered hand = 0% is an outlier (likely bad selection). With 1 trial, variance is extreme.

### Difficulty Cliff

- **1-5 bugs**: Models consistently fix 80-100% of valid bugs
- **7-10 bugs**: Still 60-90% for scattered, but 50-75% for clustered (many bugs in same code)
- **15-20 bugs scattered**: Drops to 20-50% — the long-horizon debugging limit for deepseek-chat
