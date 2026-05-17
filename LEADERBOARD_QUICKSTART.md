# 🚀 Leaderboard Quick Start

## What was created?

Three new components for visualizing benchmark results:

### 1. 📊 **CLI Tool** - `scripts/leaderboard_cli.py`

Command-line tool to aggregate and export benchmark results.

```bash
# View table
python3 -m scripts.leaderboard_cli results/runs

# View detailed breakdown
python3 -m scripts.leaderboard_cli results/runs --format detailed

# Export to JSON
python3 -m scripts.leaderboard_cli results/runs --format json --output leaderboard.json

# Filter by agent
python3 -m scripts.leaderboard_cli results/runs --agent claude
```

**Features:**
- ✅ Scans results directory automatically
- ✅ Aggregates pass rates & average scores
- ✅ Groups by benchmark
- ✅ Multiple output formats (table, detailed, JSON, tasks)
- ✅ Agent filtering

### 2. 🌐 **Next.js Web Dashboard** - `packages/leaderboard-web/`

Beautiful interactive dashboard for visualizing results.

```bash
cd packages/leaderboard-web
npm install
npm run dev
# Visit http://localhost:3000
```

**Features:**
- ✅ Real-time leaderboard with rankings
- ✅ Interactive charts (bar, line)
- ✅ Per-benchmark breakdown
- ✅ Dark theme UI
- ✅ Responsive design (mobile, tablet, desktop)
- ✅ Click agents for detailed view

### 3. 🧪 **Sample CDBench Benchmark** - `benchmarks/cdbench_demo/`

3 debugging/repair tasks to demonstrate the system:

```
benchmarks/cdbench_demo/
├── debug_list_comprehension_01     # Fix filtering logic (1 fault)
├── debug_dict_merge_02             # Fix dict merge (2 faults)
└── debug_string_format_03          # Fix None handling (1 fault)
```

Run a sample task:
```bash
python3 -m harness.run_task benchmarks/cdbench_demo/tasks/debug_list_comprehension_01 \
  --agent mini_claude_haiku_4_5 \
  --runtime local
```

Results appear in leaderboard immediately!

## File Structure

```
benchmark-creator/
├── scripts/
│   ├── leaderboard_cli.py          ✨ CLI aggregator (new)
│   └── demo_leaderboard.sh         ✨ Demo script (new)
│
├── packages/
│   └── leaderboard-web/            ✨ Next.js dashboard (new)
│       ├── app/
│       │   ├── page.tsx            Main leaderboard page
│       │   ├── globals.css         Styling
│       │   └── api/leaderboard/    API endpoint
│       ├── package.json
│       ├── tailwind.config.js
│       └── README.md
│
├── benchmarks/
│   └── sample_demo/                ✨ Demo benchmark (new)
│       ├── benchmark.json
│       └── tasks/
│           ├── basic_list_...
│           ├── dict_merge_...
│           └── string_format_...
│
└── LEADERBOARD.md                  ✨ Full documentation (new)
```

## Quick Commands

```bash
# Show leaderboard (table)
python3 -m scripts.leaderboard_cli results/runs

# Show detailed breakdown
python3 -m scripts.leaderboard_cli results/runs --format detailed

# Export as JSON
python3 -m scripts.leaderboard_cli results/runs --format json > leaderboard.json

# Run web dashboard
cd packages/leaderboard-web && npm install && npm run dev

# Run sample task
python3 -m harness.run_task benchmarks/sample_demo/tasks/basic_list_comprehension_01 \
  --agent mini_claude_haiku_4_5 --runtime local
```

## Integration Points

### CLI → Web Dashboard

The web dashboard at `/api/leaderboard` calls the Python CLI tool to fetch real-time data:

```typescript
// packages/leaderboard-web/app/api/leaderboard/route.ts
const output = execSync(`python3 -m scripts.leaderboard_cli results/runs --format json`)
return NextResponse.json(JSON.parse(output))
```

### Results → CLI

The CLI scans `results/runs/` and parses `result.json` files:

```
results/runs/
└── task_id/
    └── run_id/
        ├── result.json          ← parsed here
        ├── setup_stdout.txt
        └── agent_logs/
```

### Benchmark Tasks → Results

When you run a task with the harness, it creates a result:

```bash
python3 -m harness.run_task benchmarks/sample_demo/tasks/basic_list_comprehension_01 \
  --agent mini_claude_haiku_4_5 --runtime local
# → creates results/runs/basic_list_comprehension_01/...
```

## Data Flow

```
              Run Benchmark
                    ↓
         results/runs/task_id/run_id/
                    ↓
              CLI Aggregator
                    ↓
         Table / JSON / Detailed
                    ↓
              Next.js API
                    ↓
          Web Dashboard (page.tsx)
                    ↓
    Charts, Table, Agent Details
```

## Example Output

### Table Format
```
🏆 BENCHMARK LEADERBOARD 🏆

Rank   Agent                          Tasks      Pass Rate    Avg Score   
----------------------------------------------------------------------
1      claude-opus                    32/35      91.4%        0.9180
2      gpt-4                          28/35      80.0%        0.8050
3      claude-haiku                   22/35      62.9%        0.6450
```

### Web Dashboard
- **Summary Stats**: Total agents, tasks, average pass rate
- **Leaderboard Table**: Ranked performance with bars
- **Charts**: Pass rates and average scores by agent
- **Detail View**: Per-benchmark breakdown when clicking agent

## Tech Stack

| Component | Stack | Key Libs |
|-----------|-------|----------|
| **CLI** | Python 3.9+ | json, pathlib, dataclasses |
| **Web** | Next.js 15 + React 19 | Tailwind CSS, Recharts, TypeScript |
| **Data** | JSON | result.json files in results/runs |

## Next Steps

1. **Generate benchmarks** - Use the existing `benchmark_creator` CLI to create tasks
2. **Run evaluations** - Use `harness.run_tasks` to run against multiple agents
3. **View results** - Use the leaderboard CLI or web dashboard
4. **Iterate** - Improve prompts/tasks based on performance patterns

See `LEADERBOARD.md` for full documentation.
