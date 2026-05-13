# CDBench Project — Claude Guidelines

## De-risk before scaling (mandatory)

Before launching any full training run or large eval:

1. **Overfit a tiny batch first**: Run 5–10 training steps on 2–3 examples. Confirm loss moves, reward signal is non-zero, outputs look right.
2. **Inspect intermediate outputs**: Print raw model output, parsed fixes, and reward values for 2–3 samples. Confirm the parser extracts what you expect, the scorer returns sensible numbers.
3. **Only then scale**: Once overfit + output inspection passes, launch the full run.

This applies to every new format, prompt change, scorer change, or training variant. The cost of a 5-min sanity check is nothing compared to 4 wasted GPU-hours.

## Project overview

- **Benchmark**: CDBench — multi-fault debugging on sklearn via SGS-generated corruptions
- **Server**: 8×H100 80GB, ubuntu@34.86.165.36, SSH key: ~/.ssh/nodeset3_ed25519
- **Repo on server**: ~/cdbench/repo/
- **Python env**: conda activate cdbench
- **Key paths**:
  - SGS corruptions: results/sgs_corruptions_sklearn.json (173 total, 139 healthy)
  - Train pool: 112 corruptions, held-out pool: 27 (20% split, saved in eval_results.json)
  - T_fail cache: /mnt/localssd/cdbench/tfail_cache/
  - HF cache: /mnt/localssd/cdbench/hf_cache/
  - Eval results: results/local_eval/
  - Checkpoints: checkpoints/
  - Logs: logs/

## Output format (current: FILE/FIND/FIX find-replace)

Models output one block per bug:
```
FILE: path/to/file.py
FIND: exact buggy line(s) as they appear in the corrupted file
FIX:  corrected version
```

Multiple bugs → multiple FILE/FIND/FIX blocks. Parser (`extract_findreplace_fixes`) is flexible,
accepts BUGGY/WRONG/REPLACE/CORRECTED variations.

Scoring: `_apply_findreplace_to_sandbox` (1) builds corrupted in-memory text from clean sandbox,
(2) applies model's FIND→FIX substitution, (3) writes to sandbox, (4) runs T_fail tests.
**CRITICAL**: must apply corruption in-memory first (sandbox is always clean).

## Key findings (confirmed, paper-ready)

### Baselines — no few-shot
- 3B: n1=40±32%, n3=17±18%, n5=8±10%
- 7B: n1=60±32%, n3=3±7%, n5=4±5%

### Baselines — with 2-bug few-shot example
- 3B+fs: n1=30±30% (WORSE than no-fs!), n3=10±20%, n5=2±4%
- 7B+fs: n1=70±30%, n3=30±27%, n5=40±17% (dramatic improvement on n3/n5)
- 32B+fs: n1=100±0%, n3=87±26%, n5=68±24% (near-perfect ceiling)

### Post-RL (no few-shot, balanced 33/33/33, 100 steps)
- 3B seed 42: n1=70%, n3=17%, n5=4% → +30pp on n1, no regression on n3
- 7B seed 42: n1=60%, n3=10%, n5=12% → RL shifts gains to multi-fault regime

### Few-shot size sensitivity (novel paper contribution)
- 7B benefits enormously from few-shot (n3: 3→30%, n5: 4→40%)
- 3B is harmed by few-shot (n1: 40→30%) — lacks in-context learning capacity
- 3B few-shot RL training breaks (clipped_ratio=0.875, reward stuck at 0.125)
- Do NOT use few-shot when training 3B with RL

## Running jobs protocol

- Use `screen` for all long-running jobs
- Log to `logs/<job_name>.log` with `2>&1 | tee logs/<name>.log`
- Always `source /home/ubuntu/miniconda3/etc/profile.d/conda.sh && conda activate cdbench` inside screen
- Check GPU allocation before launching: `nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits`
- Post-RL eval: use `--held-out-ids checkpoints/<name>/eval_results.json` to prevent leakage

## Useful commands

```bash
# Check all running screens
screen -ls

# Check step progress from log
grep -o '[0-9]\+/100' logs/train_*.log | tail -1

# Read TensorBoard metrics (reward, clipping)
python3 -c "
from tensorboard.backend.event_processing import event_accumulator
ea = event_accumulator.EventAccumulator('checkpoints/<name>/runs/<run_dir>')
ea.Reload()
for e in ea.Scalars('train/reward'): print(e.step, e.value)
"
```
